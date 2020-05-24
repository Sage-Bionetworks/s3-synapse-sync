import json
import os
import sys

from urllib.parse import unquote_plus
import boto3
import mimetypes
import synapseclient
import tempfile
import uuid


synapseclient.core.cache.CACHE_ROOT_DIR = '/tmp/.synapseCache'
syn = synapseclient.Synapse()
syn.login(email=os.environ.get('username', 'username variable is not set.'),
        apiKey=os.environ.get('apiKey', 'apiKey variable is not set.'),silent=True)

def lambda_handler(event, context):
    """ Lambda Function to be triggered by S3 Storage.
    Args:
        event: The Lambda Functions event payload.
        context: Metadata of triggering event.
    """
    print(event)
    
    eventname = event['Records'][0]['eventName']
    bucket = event['Records'][0]['s3']['bucket']['name']
    key = unquote_plus(event['Records'][0]['s3']['object']['key'])
    filename = os.path.basename(key)
    project_id = os.environ.get('synapseProjectId', 'synapseProjectId variable is not set.')
    inclFolders = os.environ.get('foldersToSync', 'foldersToSync environment variable is not set.') 
    
    if key.split('/')[0] in inclFolders.split(','):
        if 'ObjectCreated' in eventname:
            create_filehandle(event, filename, bucket, key, project_id)
        elif 'ObjectRemoved' in eventname:
            delete_file(filename, project_id, key)

def create_filehandle(event, filename, bucket, key, project_id):
    parent = get_parent_folder(project_id, key)
    eTag = event['Records'][0]['s3']['object']['eTag']
    file_id = syn.findEntityId(filename, parent)
    
    if file_id != None:
        targetMD5 = syn.get(file_id, downloadFile=False)['md5'];

    # create filehandle if it does not exist in Synapse or if existing file was modified (check md5):
    if file_id == None or eTag != targetMD5: 
        size = event['Records'][0]['s3']['object']['size']
        contentType = mimetypes.guess_type(filename, strict=False)[0]
        storage_id = syn.restGET("/projectSettings/"+project_id+"/type/upload")['locations'][0]

        fileHandle = {'concreteType': 'org.sagebionetworks.repo.model.file.S3FileHandle',
                            'fileName'    : filename,
                            'contentSize' : size,
                            'contentType' : contentType,
                            'contentMd5'  : eTag,
                            'bucketName'  : bucket,
                            'key'         : key,
                            'storageLocationId': storage_id}
        fileHandle = syn.restPOST('/externalFileHandle/s3', json.dumps(fileHandle), endpoint=syn.fileHandleEndpoint)
        f = synapseclient.File(parentId=parent, dataFileHandleId=fileHandle['id'], name=filename, synapseStore=False)
        f = syn.store(f)

def get_parent_folder(project_id, key):
    parent_id = project_id
    folders = key.split('/')
    fn = folders.pop(-1)
    
    for f in folders:
        folder_id = syn.findEntityId(f, parent_id)
        if folder_id == None:
            # create folder: 
            folder_id = syn.store(synapseclient.Folder(name=f, parent=parent_id), forceVersion=False)['id']
        parent_id = folder_id

    return parent_id

def delete_file(filename, project_id, key):
    parent_id = get_parent_folder(project_id, key)
    file_id = syn.findEntityId(filename, parent_id)
    syn.delete(file_id)





