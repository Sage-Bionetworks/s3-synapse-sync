import json
import os
from io import BytesIO
from unittest.mock import MagicMock, Mock, patch

import boto3
import pytest
from botocore.exceptions import ClientError
from botocore.stub import Stubber

# Mock boto3 clients before importing lambda_function to avoid AWS credential/network dependencies
# The module creates s3, ssm, s3_resource, and batch clients at import time (lines 31-34)
with patch('boto3.client'), patch('boto3.resource'):
    from s3_synapse_sync import lambda_function


@pytest.fixture
def s3_event_story_json():
    """S3 event fixture for story.json upload"""
    return {
        'Records': [{
            'eventName': 'ObjectCreated:Put',
            's3': {
                'bucket': {'name': 'test-bucket'},
                'object': {
                    'key': 'minerva/test-story.json',
                    'size': 1024,
                    'eTag': 'abc123def456'
                }
            }
        }]
    }


@pytest.fixture
def s3_event_ome_tiff():
    """S3 event fixture for OME-TIFF upload"""
    return {
        'Records': [{
            'eventName': 'ObjectCreated:Put',
            's3': {
                'bucket': {'name': 'test-bucket'},
                'object': {
                    'key': 'minerva/test-image.ome.tif',
                    'size': 10485760,
                    'eTag': '789ghi012jkl'
                }
            }
        }]
    }


@pytest.fixture
def s3_event_removed():
    """S3 event fixture for object removal"""
    return {
        'Records': [{
            'eventName': 'ObjectRemoved:Delete',
            's3': {
                'bucket': {'name': 'test-bucket'},
                'object': {
                    'key': 'minerva/test-file.txt',
                    'size': 512,
                    'eTag': 'mno345pqr678'
                }
            }
        }]
    }


@pytest.fixture
def env_vars():
    """Common environment variables"""
    return {
        'JOB_QUEUE': 'test-queue',
        'JOB_DEFINITION': 'test-definition',
        'BUCKET_VARIABLES': json.dumps({
            'test-bucket': {
                'SynapseProjectId': 'syn12345'
            }
        })
    }


@pytest.fixture
def mock_synapse_client(mocker):
    """Mock synapseclient.Synapse"""
    mock_syn = MagicMock()
    mock_syn.findEntityId.return_value = None
    mock_syn.restGET.return_value = {'locations': [123]}
    mock_syn.restPOST.return_value = {'id': 'file-handle-123'}
    mock_syn.store.return_value = {'id': 'syn67890'}
    mocker.patch('s3_synapse_sync.lambda_function.synapseclient.Synapse', return_value=mock_syn)
    mocker.patch('s3_synapse_sync.lambda_function.synapseclient.Folder')
    mocker.patch('s3_synapse_sync.lambda_function.synapseclient.File')
    mocker.patch('s3_synapse_sync.lambda_function.synapseclient.core.cache.CACHE_ROOT_DIR', '/tmp/.synapseCache')
    return mock_syn


def test_get_env_var_success(mocker):
    """Test _get_env_var with existing variable"""
    mocker.patch.dict(os.environ, {'TEST_VAR': 'test-value'})
    result = lambda_function._get_env_var('TEST_VAR')
    assert result == 'test-value'


def test_get_env_var_missing():
    """Test _get_env_var raises ValueError when variable is missing"""
    with pytest.raises(ValueError, match='missing environment variable MISSING_VAR'):
        lambda_function._get_env_var('MISSING_VAR')


def test_tiff_in_file(mocker):
    """Test extracting TIFF filename from story.json"""
    story_json_content = json.dumps({
        'in_file': 'path/to/test-image.ome.tiff'
    })

    mock_s3_resource = MagicMock()
    mock_object = MagicMock()
    mock_object.get.return_value = {
        'Body': MagicMock(read=lambda: story_json_content.encode('utf-8'))
    }
    mock_s3_resource.Object.return_value = mock_object

    mocker.patch.object(lambda_function, 's3_resource', mock_s3_resource)

    result = lambda_function.tiff_in_file('test-bucket', 'minerva/test-story.json')
    assert result == 'test-image.ome.tiff'


def test_tiff_in_file_windows_path(mocker):
    """Test extracting TIFF filename with Windows-style path separators"""
    story_json_content = json.dumps({
        'in_file': 'C:\\path\\to\\test-image.ome.tiff'
    })

    mock_s3_resource = MagicMock()
    mock_object = MagicMock()
    mock_object.get.return_value = {
        'Body': MagicMock(read=lambda: story_json_content.encode('utf-8'))
    }
    mock_s3_resource.Object.return_value = mock_object

    mocker.patch.object(lambda_function, 's3_resource', mock_s3_resource)

    result = lambda_function.tiff_in_file('test-bucket', 'minerva/test-story.json')
    assert result == 'test-image.ome.tiff'


def test_get_story_json(mocker):
    """Test finding story.json files that reference a given TIFF"""
    # Mock tiff_in_file to return the target filename
    mocker.patch.object(lambda_function, 'tiff_in_file', return_value='test-image.ome.tiff')

    mock_s3 = MagicMock()
    mock_s3.list_objects_v2.return_value = {
        'Contents': [
            {'Key': 'minerva/first-story.json'},
            {'Key': 'minerva/second-story.json'},
            {'Key': 'minerva/image.ome.tiff'},
        ]
    }

    mocker.patch.object(lambda_function, 's3', mock_s3)

    result = lambda_function.get_story_json('test-bucket', 'test-image.ome.tiff', 'minerva')
    assert 'minerva/first-story.json' in result
    assert 'minerva/second-story.json' in result
    assert len(result) == 2


def test_submit_batch_job(mocker, env_vars):
    """Test submitting a Batch job"""
    mocker.patch.dict(os.environ, env_vars)

    mock_batch = MagicMock()
    mock_batch.submit_job.return_value = {'jobId': 'job-123'}
    mocker.patch.object(lambda_function, 'batch', mock_batch)

    lambda_function.submit_batch_job('test-image.ome.tiff', 'test-story.json', 'test-bucket/minerva')

    mock_batch.submit_job.assert_called_once()
    call_args = mock_batch.submit_job.call_args
    assert call_args[1]['jobQueue'] == 'test-queue'
    assert call_args[1]['jobDefinition'] == 'test-definition'
    assert call_args[1]['containerOverrides']['environment'][0]['value'] == 'test-image.ome.tiff'
    assert call_args[1]['containerOverrides']['environment'][1]['value'] == 'test-story.json'
    assert call_args[1]['containerOverrides']['environment'][2]['value'] == 'test-bucket/minerva'


def test_get_md5_simple_etag(s3_event_story_json):
    """Test MD5 extraction from simple eTag (no multipart)"""
    header = {'Metadata': {}}
    result = lambda_function.get_md5(s3_event_story_json, header, 'test-bucket', 'minerva/test-story.json')
    assert result == 'abc123def456'


def test_get_md5_with_content_md5(s3_event_story_json):
    """Test MD5 extraction from content-md5 metadata"""
    import base64
    expected_md5 = 'fedcba9876543210'
    header = {
        'Metadata': {
            'content-md5': base64.b64encode(bytes.fromhex(expected_md5)).decode('utf-8')
        }
    }
    s3_event_story_json['Records'][0]['s3']['object']['eTag'] = 'multipart-etag'

    result = lambda_function.get_md5(s3_event_story_json, header, 'test-bucket', 'minerva/test-story.json')
    assert result == expected_md5


def test_get_md5_compute(mocker, s3_event_story_json):
    """Test MD5 computation for multipart uploads without metadata"""
    test_data = b'test file content'
    mock_s3 = MagicMock()
    mock_s3.get_object.return_value = {
        'Body': BytesIO(test_data)
    }
    mocker.patch.object(lambda_function, 's3', mock_s3)

    s3_event_story_json['Records'][0]['s3']['object']['eTag'] = 'multipart-etag'
    header = {'Metadata': {}}

    result = lambda_function.get_md5(s3_event_story_json, header, 'test-bucket', 'minerva/test-story.json')
    # MD5 of 'test file content'
    assert result == 'c785060c866796cc2a1708c997154c8e'


def test_get_parent_folder_root(mock_synapse_client):
    """Test getting parent folder returns project_id for root-level file"""
    result = lambda_function.get_parent_folder(mock_synapse_client, 'syn12345', 'test-file.txt')
    assert result == 'syn12345'


def test_get_parent_folder_existing(mock_synapse_client):
    """Test getting parent folder when folder already exists"""
    mock_synapse_client.findEntityId.return_value = 'syn-existing-folder'

    result = lambda_function.get_parent_folder(
        mock_synapse_client,
        'syn12345',
        'existing-folder/test-file.txt'
    )
    assert result == 'syn-existing-folder'
    mock_synapse_client.store.assert_not_called()


def test_get_parent_folder_no_create(mock_synapse_client):
    """Test getting parent folder without creating missing folders"""
    mock_synapse_client.findEntityId.return_value = None

    result = lambda_function.get_parent_folder(
        mock_synapse_client,
        'syn12345',
        'missing-folder/test-file.txt',
        create_folders=False
    )
    assert result is None


def test_delete_object_file(mock_synapse_client):
    """Test deleting a file from Synapse"""
    mock_synapse_client.findEntityId.side_effect = ['syn-folder', 'syn-file']

    lambda_function.delete_object(
        mock_synapse_client,
        'test-file.txt',
        'syn12345',
        'folder/test-file.txt'
    )
    mock_synapse_client.delete.assert_called_once_with('syn-file')


def test_delete_object_folder(mock_synapse_client):
    """Test deleting a folder from Synapse"""
    mock_synapse_client.findEntityId.return_value = 'syn-folder'

    lambda_function.delete_object(
        mock_synapse_client,
        '',
        'syn12345',
        'folder/'
    )
    mock_synapse_client.delete.assert_called_once_with('syn-folder')


def test_delete_object_missing_parent(mock_synapse_client):
    """Test deleting when parent folder doesn't exist in Synapse"""
    mock_synapse_client.findEntityId.return_value = None

    lambda_function.delete_object(
        mock_synapse_client,
        'test-file.txt',
        'syn12345',
        'missing-folder/test-file.txt'
    )
    mock_synapse_client.delete.assert_not_called()


def test_create_filehandle_root_level(mocker, mock_synapse_client, s3_event_story_json, env_vars):
    """Test create_filehandle skips root-level files"""
    mocker.patch.dict(os.environ, env_vars)

    mock_s3 = MagicMock()
    mock_s3.head_object.return_value = {'Metadata': {}}
    mocker.patch.object(lambda_function, 's3', mock_s3)

    # This should return early without creating a filehandle
    lambda_function.create_filehandle(
        mock_synapse_client,
        s3_event_story_json,
        'test-story.json',
        'test-bucket',
        'test-story.json',  # root-level key
        'syn12345'
    )

    mock_synapse_client.restPOST.assert_not_called()


def test_create_filehandle_new_file(mocker, mock_synapse_client, s3_event_story_json, env_vars):
    """Test creating a new file handle in Synapse"""
    mocker.patch.dict(os.environ, env_vars)

    mock_s3 = MagicMock()
    mock_s3.head_object.return_value = {'Metadata': {}}
    mocker.patch.object(lambda_function, 's3', mock_s3)

    mock_synapse_client.findEntityId.side_effect = ['syn-folder', None]

    lambda_function.create_filehandle(
        mock_synapse_client,
        s3_event_story_json,
        'test-story.json',
        'test-bucket',
        'minerva/test-story.json',
        'syn12345'
    )

    mock_synapse_client.restPOST.assert_called_once()
    mock_synapse_client.store.assert_called_once()


def test_create_filehandle_update_existing(mocker, mock_synapse_client, s3_event_story_json, env_vars):
    """Test updating an existing file handle when MD5 differs"""
    mocker.patch.dict(os.environ, env_vars)

    mock_s3 = MagicMock()
    mock_s3.head_object.return_value = {'Metadata': {}}
    mocker.patch.object(lambda_function, 's3', mock_s3)

    mock_synapse_client.findEntityId.side_effect = ['syn-folder', 'syn-existing-file']
    mock_synapse_client.get.return_value = {'md5': 'different-md5'}

    lambda_function.create_filehandle(
        mock_synapse_client,
        s3_event_story_json,
        'test-story.json',
        'test-bucket',
        'minerva/test-story.json',
        'syn12345'
    )

    mock_synapse_client.restPOST.assert_called_once()
    mock_synapse_client.store.assert_called_once()


def test_create_filehandle_skip_same_md5(mocker, mock_synapse_client, s3_event_story_json, env_vars):
    """Test skipping file handle creation when MD5 matches"""
    mocker.patch.dict(os.environ, env_vars)

    mock_s3 = MagicMock()
    mock_s3.head_object.return_value = {'Metadata': {}}
    mocker.patch.object(lambda_function, 's3', mock_s3)

    mock_synapse_client.findEntityId.side_effect = ['syn-folder', 'syn-existing-file']
    mock_synapse_client.get.return_value = {'md5': 'abc123def456'}

    lambda_function.create_filehandle(
        mock_synapse_client,
        s3_event_story_json,
        'test-story.json',
        'test-bucket',
        'minerva/test-story.json',
        'syn12345'
    )

    mock_synapse_client.restPOST.assert_not_called()
    mock_synapse_client.store.assert_not_called()


def test_sync_to_synapse_numeric_prefix(mocker, mock_synapse_client, s3_event_story_json, env_vars):
    """Test sync_to_synapse skips keys with numeric prefix"""
    mocker.patch.dict(os.environ, env_vars)

    mock_ssm = MagicMock()
    mock_ssm.get_parameter.return_value = {'Parameter': {'Value': 'test-pat'}}
    mocker.patch.object(lambda_function, 'ssm', mock_ssm)

    # Mock the helper functions directly to verify they're never called
    mock_create = mocker.patch.object(lambda_function, 'create_filehandle')
    mock_delete = mocker.patch.object(lambda_function, 'delete_object')

    # Use a key that starts with a digit - the guard checks key[0], not the filename
    s3_event_story_json['Records'][0]['s3']['object']['key'] = '123-folder/test-file.txt'

    lambda_function.sync_to_synapse(
        'test-bucket',
        s3_event_story_json,
        'ObjectCreated:Put',
        'test-file.txt',
        '123-folder/test-file.txt'
    )

    # The numeric prefix check should prevent these helpers from being called
    mock_create.assert_not_called()
    mock_delete.assert_not_called()


def test_lambda_handler_story_json(mocker, s3_event_story_json, env_vars, mock_synapse_client):
    """Test lambda_handler with story.json upload"""
    mocker.patch.dict(os.environ, env_vars)

    # Mock AWS clients
    mock_s3 = MagicMock()
    mock_s3.head_object.return_value = {'Metadata': {}}
    mocker.patch.object(lambda_function, 's3', mock_s3)

    mock_batch = MagicMock()
    mock_batch.submit_job.return_value = {'jobId': 'job-123'}
    mocker.patch.object(lambda_function, 'batch', mock_batch)

    mock_ssm = MagicMock()
    mock_ssm.get_parameter.return_value = {'Parameter': {'Value': 'test-pat'}}
    mocker.patch.object(lambda_function, 'ssm', mock_ssm)

    # Mock s3_resource and tiff_in_file
    story_json_content = json.dumps({'in_file': 'test-image.ome.tiff'})
    mock_s3_resource = MagicMock()
    mock_object = MagicMock()
    mock_object.get.return_value = {
        'Body': MagicMock(read=lambda: story_json_content.encode('utf-8'))
    }
    mock_s3_resource.Object.return_value = mock_object
    mocker.patch.object(lambda_function, 's3_resource', mock_s3_resource)

    mock_synapse_client.findEntityId.return_value = None

    lambda_function.lambda_handler(s3_event_story_json, {})

    # Verify batch job was submitted
    mock_batch.submit_job.assert_called_once()


def test_lambda_handler_ome_tiff(mocker, s3_event_ome_tiff, env_vars, mock_synapse_client):
    """Test lambda_handler with OME-TIFF upload"""
    mocker.patch.dict(os.environ, env_vars)

    # Mock AWS clients
    mock_s3 = MagicMock()
    mock_s3.head_object.return_value = {'Metadata': {}}
    mocker.patch.object(lambda_function, 's3', mock_s3)

    mock_batch = MagicMock()
    mock_batch.submit_job.return_value = {'jobId': 'job-123'}
    mocker.patch.object(lambda_function, 'batch', mock_batch)

    mock_ssm = MagicMock()
    mock_ssm.get_parameter.return_value = {'Parameter': {'Value': 'test-pat'}}
    mocker.patch.object(lambda_function, 'ssm', mock_ssm)

    # Mock get_story_json to return story files
    mocker.patch.object(lambda_function, 'get_story_json', return_value=['minerva/story1.json'])

    mock_synapse_client.findEntityId.return_value = None

    lambda_function.lambda_handler(s3_event_ome_tiff, {})

    # Verify batch job was submitted for each story.json found
    mock_batch.submit_job.assert_called_once()


def test_lambda_handler_removed_event(mocker, s3_event_removed, env_vars, mock_synapse_client):
    """Test lambda_handler with ObjectRemoved event"""
    mocker.patch.dict(os.environ, env_vars)

    mock_ssm = MagicMock()
    mock_ssm.get_parameter.return_value = {'Parameter': {'Value': 'test-pat'}}
    mocker.patch.object(lambda_function, 'ssm', mock_ssm)

    mock_synapse_client.findEntityId.side_effect = ['syn-folder', 'syn-file']

    lambda_function.lambda_handler(s3_event_removed, {})

    # Verify delete was called
    mock_synapse_client.delete.assert_called_once_with('syn-file')


def test_lambda_handler_missing_tiff(mocker, s3_event_story_json, env_vars, mock_synapse_client, caplog):
    """Test Lambda handles story.json referencing non-existent TIFF (404 path)"""
    mocker.patch.dict(os.environ, env_vars)

    # Mock AWS clients
    mock_s3 = MagicMock()
    # First call to s3_resource for tiff_in_file, then s3.head_object raises 404
    story_json_content = json.dumps({'in_file': 'missing-image.ome.tiff'})
    mock_s3_resource = MagicMock()
    mock_object = MagicMock()
    mock_object.get.return_value = {
        'Body': MagicMock(read=lambda: story_json_content.encode('utf-8'))
    }
    mock_s3_resource.Object.return_value = mock_object
    mocker.patch.object(lambda_function, 's3_resource', mock_s3_resource)

    # head_object: first call (checking TIFF) raises 404, second call (in create_filehandle) succeeds
    error_response = {'Error': {'Code': '404', 'Message': 'Not Found'}}
    mock_s3.head_object.side_effect = [
        ClientError(error_response, 'HeadObject'),  # First call for TIFF check
        {'Metadata': {}}  # Second call in create_filehandle for story.json
    ]
    mocker.patch.object(lambda_function, 's3', mock_s3)

    mock_batch = MagicMock()
    mocker.patch.object(lambda_function, 'batch', mock_batch)

    mock_ssm = MagicMock()
    mock_ssm.get_parameter.return_value = {'Parameter': {'Value': 'test-pat'}}
    mocker.patch.object(lambda_function, 'ssm', mock_ssm)

    mock_synapse_client.findEntityId.return_value = None

    # Lambda should handle gracefully, not crash
    lambda_function.lambda_handler(s3_event_story_json, {})

    # Batch job should NOT be submitted when TIFF is missing
    mock_batch.submit_job.assert_not_called()
    # Should still sync story.json to Synapse
    mock_synapse_client.restPOST.assert_called_once()


def test_lambda_handler_url_encoded_key(mocker, env_vars, mock_synapse_client):
    """Test Lambda handles URL-encoded S3 keys with spaces and special characters"""
    mocker.patch.dict(os.environ, env_vars)

    # S3 event with URL-encoded key (space as +)
    s3_event_encoded = {
        'Records': [{
            'eventName': 'ObjectCreated:Put',
            's3': {
                'bucket': {'name': 'test-bucket'},
                'object': {
                    'key': 'minerva/my+test+file.json',  # Space encoded as +
                    'size': 1024,
                    'eTag': 'abc123'
                }
            }
        }]
    }

    mock_s3 = MagicMock()
    mock_s3.head_object.return_value = {'Metadata': {}}
    mocker.patch.object(lambda_function, 's3', mock_s3)

    mock_ssm = MagicMock()
    mock_ssm.get_parameter.return_value = {'Parameter': {'Value': 'test-pat'}}
    mocker.patch.object(lambda_function, 'ssm', mock_ssm)

    mock_synapse_client.findEntityId.return_value = None

    lambda_function.lambda_handler(s3_event_encoded, {})

    # unquote_plus should convert 'my+test+file.json' to 'my test file.json'
    # Verify the filename passed to create_filehandle has spaces, not +
    assert mock_synapse_client.restPOST.called
    call_args = mock_synapse_client.restPOST.call_args
    file_handle = json.loads(call_args[0][1])
    assert file_handle['fileName'] == 'my test file.json'
    assert file_handle['key'] == 'minerva/my test file.json'


def test_lambda_handler_non_minerva_directory(mocker, env_vars, mock_synapse_client):
    """Test Lambda ignores files outside 'minerva' directory"""
    mocker.patch.dict(os.environ, env_vars)

    # S3 event with file in different directory
    s3_event_other = {
        'Records': [{
            'eventName': 'ObjectCreated:Put',
            's3': {
                'bucket': {'name': 'test-bucket'},
                'object': {
                    'key': 'other-folder/story.json',
                    'size': 1024,
                    'eTag': 'abc123'
                }
            }
        }]
    }

    mock_batch = MagicMock()
    mocker.patch.object(lambda_function, 'batch', mock_batch)

    mock_s3 = MagicMock()
    mock_s3.head_object.return_value = {'Metadata': {}}
    mocker.patch.object(lambda_function, 's3', mock_s3)

    mock_ssm = MagicMock()
    mock_ssm.get_parameter.return_value = {'Parameter': {'Value': 'test-pat'}}
    mocker.patch.object(lambda_function, 'ssm', mock_ssm)

    mock_synapse_client.findEntityId.return_value = None

    lambda_function.lambda_handler(s3_event_other, {})

    # Batch job should NOT be submitted for non-minerva files
    mock_batch.submit_job.assert_not_called()
    # But Synapse sync should still happen
    mock_synapse_client.restPOST.assert_called_once()


def test_lambda_handler_malformed_story_json(mocker, s3_event_story_json, env_vars, mock_synapse_client):
    """Test Lambda handles story.json with invalid JSON"""
    mocker.patch.dict(os.environ, env_vars)

    # Mock s3_resource to return invalid JSON
    mock_s3_resource = MagicMock()
    mock_object = MagicMock()
    mock_object.get.return_value = {
        'Body': MagicMock(read=lambda: b'{ invalid json }')
    }
    mock_s3_resource.Object.return_value = mock_object
    mocker.patch.object(lambda_function, 's3_resource', mock_s3_resource)

    mock_s3 = MagicMock()
    mock_s3.head_object.return_value = {'Metadata': {}}
    mocker.patch.object(lambda_function, 's3', mock_s3)

    mock_batch = MagicMock()
    mocker.patch.object(lambda_function, 'batch', mock_batch)

    mock_ssm = MagicMock()
    mock_ssm.get_parameter.return_value = {'Parameter': {'Value': 'test-pat'}}
    mocker.patch.object(lambda_function, 'ssm', mock_ssm)

    mock_synapse_client.findEntityId.return_value = None

    # Lambda should raise JSONDecodeError
    with pytest.raises(json.JSONDecodeError):
        lambda_function.lambda_handler(s3_event_story_json, {})


def test_sync_to_synapse_ssm_failure(mocker, s3_event_story_json, env_vars, mock_synapse_client):
    """Test sync_to_synapse handles SSM parameter retrieval failure"""
    mocker.patch.dict(os.environ, env_vars)

    # SSM parameter not found
    mock_ssm = MagicMock()
    error_response = {'Error': {'Code': 'ParameterNotFound', 'Message': 'Parameter not found'}}
    mock_ssm.get_parameter.side_effect = ClientError(error_response, 'GetParameter')
    mocker.patch.object(lambda_function, 'ssm', mock_ssm)

    # Should raise ClientError when SSM parameter is missing
    with pytest.raises(ClientError):
        lambda_function.sync_to_synapse(
            'test-bucket',
            s3_event_story_json,
            'ObjectCreated:Put',
            'test-file.txt',
            'minerva/test-file.txt'
        )


def test_submit_batch_job_missing_env_var(mocker):
    """Test submit_batch_job fails when required environment variables are missing"""
    # Don't set environment variables
    mocker.patch.dict(os.environ, {}, clear=True)

    mock_batch = MagicMock()
    mocker.patch.object(lambda_function, 'batch', mock_batch)

    # Should raise ValueError for missing JOB_QUEUE
    with pytest.raises(ValueError, match='missing environment variable JOB_QUEUE'):
        lambda_function.submit_batch_job('test.tiff', 'test.json', 'bucket/path')
