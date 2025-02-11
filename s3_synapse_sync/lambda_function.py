"""
Copyright 2020, Institute for Systems Biology

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

   http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""
import json
import os
import sys

from urllib.parse import unquote_plus
from botocore.errorfactory import ClientError
import base64
import boto3
import hashlib
import mimetypes
import re
import synapseclient
import tempfile
import uuid

s3 = boto3.client('s3')
ssm = boto3.client('ssm')
s3_resource = boto3.resource('s3')
batch = boto3.client('batch')
MD5_BLOCK_SIZE = 50 * 1024 ** 2

def lambda_handler(event, context):
    print(event)
    eventname = event['Records'][0]['eventName']
    bucket = event['Records'][0]['s3']['bucket']['name']
    key = unquote_plus(event['Records'][0]['s3']['object']['key'])

    filename = os.path.basename(key)
    dirname = os.path.dirname(key)
    filepath = bucket+'/'+dirname
    prefix='minerva'

    if dirname == prefix and key.endswith('story.json'):
        try:
            input_tiff = tiff_in_file(bucket,key)
            s3.head_object(Bucket=bucket, Key=dirname+'/'+input_tiff)
        except ClientError as e:
            if e.response['Error']['Code'] == "404":
                print("{} image not found.".format(input_tiff))
            else:
                raise
        else:
            submit_batch_job(input_tiff,filename,filepath)
    elif dirname == prefix and (key.endswith('ome.tif') or key.endswith('ome.tiff')):
        story_json_files = get_story_json(bucket,filename,prefix)
        for file in story_json_files:
            input_json = os.path.basename(file)
            submit_batch_job(filename,input_json,filepath)

    sync_to_synapse(bucket,event,eventname,filename,key)

def tiff_in_file(bucket,key):
    """
    Read story.json file to get name of corresponding ome-tiff image
    """
    content_object = s3_resource.Object(bucket, key)
    file_content = content_object.get()['Body'].read().decode('utf-8')
    json_content = json.loads(file_content)
    in_file = os.path.basename(json_content['in_file'].replace('\\',os.sep))

    return in_file

def get_story_json(bucket,filename,prefix):
    story_json = []

    file_list = s3.list_objects_v2(Bucket=bucket,Prefix=prefix)
    for obj in file_list.get('Contents', []):
        file = obj['Key']
        if file.endswith('story.json'):
            tiff_name = tiff_in_file(bucket,file)
            if tiff_name == filename:
                story_json.append(file)

    return story_json

def submit_batch_job(input_tiff,input_json,filepath):
    response = batch.submit_job(jobName=re.sub('[^0-9a-zA-Z]+', '-', input_json)+'-batch-minerva-processor',
                                jobQueue=_get_env_var('JOB_QUEUE'),
                                jobDefinition=_get_env_var('JOB_DEFINITION'),
                                containerOverrides={
                                    "environment": [
                                        {"name": "INPUT_TIFF", "value": input_tiff},
                                        {"name": "INPUT_JSON", "value": input_json},
                                        {"name": "DIR_NAME", "value": filepath}
                                    ]
                                })

    print("Job ID is {}.".format(response['jobId']))

def sync_to_synapse(bucket,event,eventname,filename,key):
    envvars = _get_env_var('BUCKET_VARIABLES')
    env_dict = json.loads(envvars)
    project_id = env_dict[bucket]['SynapseProjectId']

    ssm_pat = '/HTAN/SynapseSync/PAT'
    pat = ssm.get_parameter(Name=ssm_pat, WithDecryption=True)['Parameter']['Value']

    synapseclient.core.cache.CACHE_ROOT_DIR = '/tmp/.synapseCache'
    syn = synapseclient.Synapse()
    syn.login(authToken=pat)

    if key[0].isdigit() == False:
        if 'ObjectCreated' in eventname:
            create_filehandle(syn, event, filename, bucket, key, project_id)
        elif 'ObjectRemoved' in eventname:
            delete_object(syn, filename, project_id, key)

def create_filehandle(syn, event, filename, bucket, key, project_id):
    parent_id = get_parent_folder(syn, project_id, key)
    if parent_id == project_id:
        return   # Do not sync files at the root level

    header = s3.head_object(Bucket=bucket, Key=key)
    md5 = get_md5(event, header, bucket, key)
    file_id = syn.findEntityId(filename, parent_id)

    if file_id != None:
        targetMD5 = syn.get(file_id, downloadFile=False)['md5'];

    if file_id == None or md5 != targetMD5:
        size = event['Records'][0]['s3']['object']['size']
        contentType = mimetypes.guess_type(filename, strict=False)[0]
        storage_id = syn.restGET("/projectSettings/"+project_id+"/type/upload")['locations'][0]

        fileHandle = {'concreteType': 'org.sagebionetworks.repo.model.file.S3FileHandle',
                            'fileName'    : filename,
                            'contentSize' : size,
                            'contentType' : contentType,
                            'contentMd5'  : md5,
                            'bucketName'  : bucket,
                            'key'         : key,
                            'storageLocationId': storage_id}
        fileHandle = syn.restPOST('/externalFileHandle/s3', json.dumps(fileHandle), endpoint=syn.fileHandleEndpoint)
        f = synapseclient.File(parentId=parent_id, dataFileHandleId=fileHandle['id'], name=filename, synapseStore=False)
        f = syn.store(f)

def get_parent_folder(syn, project_id, key, create_folders=True):
    parent_id = project_id
    folders = key.split('/')
    folders.pop(-1)

    if folders:
        for f in folders:
            folder_id = syn.findEntityId(f, parent_id)
            if folder_id == None:
                if not create_folders:
                    return None

                folder_id = syn.store(synapseclient.Folder(name=f, parent=parent_id), forceVersion=False)['id']
            parent_id = folder_id

    return parent_id

def delete_object(syn, filename, project_id, key):
    parent_id = get_parent_folder(syn, project_id, key, False)
    if parent_id == None:  # Parent folder does not exist on Synapse
        return

    if not filename:   # Object is a folder
        syn.delete(parent_id)
    else:              # Delete file
        file_id = syn.findEntityId(filename, parent_id)
        syn.delete(file_id)

def get_md5(event, header, bucket, key):
    """
    Check if eTag is equivalent to md5 or md5 provided by user during upload. If not, compute md5.
    """
    eTag = event['Records'][0]['s3']['object']['eTag']
    if '-' not in eTag:
        md5 = eTag
    elif "content-md5" in header['Metadata']:
        md5 = base64.b64decode(header['Metadata']['content-md5']).hex()
    else:
        s3_object = s3.get_object(Bucket=bucket, Key=key)
        md5 = md5sum(s3_object["Body"])
    return md5

# Modified from Phil's code
def md5sum(file_obj=None, blocksize=None):
    """
    Compute md5sum of a file stream by reading it in blocks.
    :param file_obj: Stream to read.
    :param blocksize: Block size for each chunk read.
    :return: md5 sum
    """
    blocksize = blocksize or MD5_BLOCK_SIZE
    if file_obj is not None:
        hash = _block_hash(
            file_obj=file_obj,
            blocksize=blocksize)
    else:
        raise TypeError("Either filename or file_obj must be set.")
    hash = hash.hexdigest().encode("ascii")
    return hash.decode("utf-8")

def _block_hash(file_obj, blocksize, hash=None):
    if hash is None:
        hash = hashlib.md5()
    for block in iter(lambda: file_obj.read(blocksize), b""):
        hash.update(block)
    return hash

def _get_env_var(name):
    value = os.getenv(name)
    if not value:
        raise ValueError(('Lambda configuration error: '
            f'missing environment variable {name}'))
    return value
