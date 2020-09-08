import json
import os
import sys

from urllib.parse import unquote_plus
import base64
import boto3
import hashlib
import mimetypes
import synapseclient
import tempfile
import uuid
import yaml

s3 = boto3.client('s3')
ssm = boto3.client('ssm')
MD5_BLOCK_SIZE = 50 * 1024 ** 2

def lambda_handler(event, context):
    print(event)
    eventname = event['Records'][0]['eventName']
    bucket = event['Records'][0]['s3']['bucket']['name']
    key = unquote_plus(event['Records'][0]['s3']['object']['key'])
    filename = os.path.basename(key)

    ssm_user = '/HTAN/SynapseSync/username'
    ssm_api = '/HTAN/SynapseSync/apiKey'
    username = ssm.get_parameter(Name=ssm_user, WithDecryption=True)['Parameter']['Value']
    apiKey = ssm.get_parameter(Name=ssm_api, WithDecryption=True)['Parameter']['Value']

    envvars = _load_bucket_vars()
    project_id = envvars[bucket]['SynapseProjectId']
    inclFolders = envvars[bucket]['FoldersToSync']

    synapseclient.core.cache.CACHE_ROOT_DIR = '/tmp/.synapseCache'
    syn = synapseclient.Synapse()
    syn.login(email=username,apiKey=apiKey)

    if key.split('/')[0] in inclFolders:
        if 'ObjectCreated' in eventname:
            create_filehandle(syn, event, filename, bucket, key, project_id)
        elif 'ObjectRemoved' in eventname:
            delete_file(syn, filename, project_id, key)

def create_filehandle(syn, event, filename, bucket, key, project_id):
    print("filename: "+str(filename))
    parent = get_parent_folder(syn, project_id, key)
    header = s3.head_object(Bucket=bucket, Key=key)
    md5 = get_md5(event, header, bucket, key)
    file_id = syn.findEntityId(filename, parent)

    if file_id != None:
        targetMD5 = syn.get(file_id, downloadFile=False)['md5'];

    if file_id == None or md5 != targetMD5:
        size = event['Records'][0]['s3']['object']['size']
        contentType = mimetypes.guess_type(filename, strict=False)[0]
        storage_id = syn.restGET("/projectSettings/"+project_id+"/type/upload")['locations'][0]

        synapse_canonical_id = _get_env_var('SYNAPSE_CANONICAL_ID')
        boto3.resource('s3').ObjectAcl(bucket, key).put(GrantRead='id='+synapse_canonical_id)

        fileHandle = {'concreteType': 'org.sagebionetworks.repo.model.file.S3FileHandle',
                            'fileName'    : filename,
                            'contentSize' : size,
                            'contentType' : contentType,
                            'contentMd5'  : md5,
                            'bucketName'  : bucket,
                            'key'         : key,
                            'storageLocationId': storage_id}
        fileHandle = syn.restPOST('/externalFileHandle/s3', json.dumps(fileHandle), endpoint=syn.fileHandleEndpoint)
        f = synapseclient.File(parentId=parent, dataFileHandleId=fileHandle['id'], name=filename, synapseStore=False)
        f = syn.store(f)

def get_parent_folder(syn, project_id, key):
    parent_id = project_id
    folders = key.split('/')
    fn = folders.pop(-1)

    for f in folders:
        folder_id = syn.findEntityId(f, parent_id)
        if folder_id == None:
            folder_id = syn.store(synapseclient.Folder(name=f, parent=parent_id), forceVersion=False)['id']
        parent_id = folder_id

    return parent_id

def delete_file(syn, filename, project_id, key):
    parent_id = get_parent_folder(syn, project_id, key)
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

def _load_yaml(yaml_string, config_name=None):
    try:
        output = yaml.safe_load(yaml_string)
    except yaml.YAMLError as e:
        error_message = (
            f'There was an error when attempting to load {config_name}. '
            f'Error details: {e}'
        )
        raise Exception(error_message)
    return output

def _load_bucket_vars():
    return _load_yaml(
        _get_env_var('BUCKET_VARIABLES'),
        'bucket_variables'
        )
