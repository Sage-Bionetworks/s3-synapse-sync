# s3-synapse-sync

Lambda function code to index files in S3 buckets by creating filehandles on Synapse, triggered by file changes to S3.


## Getting started

Confirm [center onboarding](https://docs.google.com/document/d/1cCRkfK6or6lwMNc96f5LTp9rK8aHEDqhyP0ISgSn9sI/edit) steps are complete, and a Synapse project has been created to which the bucket will be synced.

---

## Development

### Requirements
Run `pipenv install --dev` to install both production and development
requirements, and `pipenv shell` to activate the virtual environment. For more
information see the [pipenv docs](https://pipenv.pypa.io/en/latest/).

After activating the virtual environment, run `pre-commit install` to install
the [pre-commit](https://pre-commit.com/) git hook.

#### Parameters
Create a AWS KMS key to encrypte secure strings.

Create a sceptre s3-synapse-sync-kms-key.yaml file used to deploy cloudformation
template [s3-synapse-sync-kms-key.yaml](s3-synapse-sync-kms-key.yaml):
```yaml
template_path: "s3-synapse-sync-kms-key.yaml"
stack_name: "s3-synapse-sync-kms-key"
stack_tags:
  Department: "CompOnc"
  Project: "HTAN"
  OwnerEmail: "joe.smith@sagebase.org"
```
__Note__: You may need to add your user ARN to the policy principal in the
cloudformation template.

Deploy the stack using sceptre:
```shell script
sceptre --var "profile=my-profile" --var "region=us-east-1" launch prod/s3-synapse-sync-kms-key.yaml
```

Add two **SecureString** parameters containing Synapse credentials to SSM Parameter Store

| Parameter Name  | Value | Type |
| ------------- | ------------- | ------------- |
| `/HTAN/SynapseSync/username`  | `synapse-service-HTAN-lambda`  | SecureString |
| `/HTAN/SynapseSync/apiKey`  | Synapse service account API Key | SecureString |

```shell script
aws ssm put-parameter \
  --name /HTAN/SynapseSync/username \
  --value <synapse user name> \
  --type SecureString \
  --key-id alias/s3-synapse-sync-kms-key/kmskey
```

#### Environment Variables
This lambda requires the environment variable `BUCKET_VARIABLES`: a yaml-format string that defines for each HTAN bucket:

    - The ID of the center's Synapse project
    - Folders in the bucket to be synced to Synapse

s3-synapse-sync-bucket-vars.yaml:
```yaml
bucket-a:
  SynapseProjectId: syn11111
  FoldersToSync:
    - folderA
    - folderB
bucket-b:
  SynapseProjectId: syn22222
  FoldersToSync:
    - folderA
    - folderB
    - folderC
```

*Note: Buckets must be explicitly named and names must be globally unique across all AWS accounts*

Now [Install Lambda into AWS](#Install Lambda into AWS)

Create a sceptre s3-synapse-sync-bucket-a.yaml file used to deploy jinjaized
cloudformation template [s3-synapse-sync-bucket-a.yaml](s3-synapse-sync-bucket.j2):
```yaml
template_path: "remote/s3-synapse-sync-bucket.j2"
stack_name: "s3-synapse-sync-bucket-a"
stack_tags:
  Department: "CompOnc"
  Project: "HTAN"
  OwnerEmail: "joe.smith@sagebase.org"
hooks:
  before_launch:
    - !cmd "curl https://{{stack_group_config.admincentral_cf_bucket}}.s3.amazonaws.com/s3-synapse-sync/master/s3-synapse-sync-bucket.j2 --create-dirs -o templates/remote/s3-synapse-sync-bucket.j2"
dependencies:
  - "prod/s3-synapse-sync.yaml"
parameters:
  BucketName: "s3-synapse-sync-bucket-a"  # must match bucket name in s3-synapse-sync-bucket-vars.yaml
  SynapseIDs:
    - "1111111"
  S3UserARNs:
    - "arn:aws:sts::213235685529:assumed-role/sandbox-developer/joe.smith@sagebase.org"
  S3CanonicalUserId: "eab4436941f355ce866fcf7944db42020c385ad1f19df8a95704dc4d7552fa06"
  S3SynapseSyncFunctionArn: !stack_output_external "s3-synapse-sync::FunctionArn"
  S3SynapseSyncFunctionRoleArn: !stack_output_external "s3-synapse-sync::FunctionRoleArn"

# Due to circular dependency enabling bucket notification must be done after bucket creation
# https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-properties-s3-bucket-notificationconfig.html
sceptre_user_data:
  EnableNotificationConfiguration: "false"
```

Deploy with sceptre, Notification configuration is disabled on 1st deploy.
Deploy a 2nd time with `EnableNotificationConfiguration: "true"`

---

### Create a local build

```shell script
$ sam build --use-container
```

### Run locally

```shell script
$ sam local invoke HelloWorldFunction --event events/event.json
```

### Run unit tests
Tests are defined in the `tests` folder in this project. Use PIP to install the
[pytest](https://docs.pytest.org/en/latest/) and run unit tests.

```shell script
$ python -m pytest tests/ -v
```

## Deployment

### Build

```shell script
sam build
```

## Deploy Lambda to S3
This requires the correct permissions to upload to bucket
`bootstrap-awss3cloudformationbucket-19qromfd235z9` and
`essentials-awss3lambdaartifactsbucket-x29ftznj6pqw`

```shell script
sam package --template-file .aws-sam/build/template.yaml \
  --s3-bucket essentials-awss3lambdaartifactsbucket-x29ftznj6pqw \
  --output-template-file .aws-sam/build/s3-synapse-sync.yaml

aws s3 cp .aws-sam/build/s3-synapse-sync.yaml s3://bootstrap-awss3cloudformationbucket-19qromfd235z9/s3-synapse-sync/master/
```

## Install Lambda into AWS
Create the following [sceptre](https://github.com/Sceptre/sceptre) file

Create a sceptre s3-synapse-sync.yaml file used to deploy cloudformation
template [s3-synapse-sync.yaml](template.yaml):
```yaml
template_path: "remote/s3-synapse-sync.yaml"
stack_name: "s3-synapse-sync"
stack_tags:
  Department: "CompOnc"
  Project: "HTAN"
  OwnerEmail: "joe.smith@sagebase.org"
dependencies:
  - "prod/s3-synapse-sync-kms-key.yaml"
hooks:
  before_launch:
    - !cmd "curl https://{{stack_group_config.admincentral_cf_bucket}}.s3.amazonaws.com/s3-synapse-sync/master/s3-synapse-sync.yaml --create-dirs -o templates/remote/s3-synapse-sync.yaml"
parameters:
  BucketVariables: !file_contents "data/s3-synapse-sync-bucket-vars.yaml"
  KmsDecryptPolicyArn: !stack_output_external "s3-synapse-sync-kms-key::KmsDecryptPolicyArn"
```

Install the lambda using sceptre:
```shell script
sceptre --var "profile=my-profile" --var "region=us-east-1" launch prod/s3-synapse-sync.yaml
```

---

### To Test:
1. Place a file in one of the folders specified in the `foldersToSync` parameter
    - Include the `--grants` flag upon upload to grant full control of the object to both
        1. the Synapse account
            - Synapse canonical ID: `d9df08ac799f2859d42a588b415111314cf66d0ffd072195f33b921db966b440`
        2. the bucket owner account
            - i.e. Sage Sandbox (canonical ID: `9038e06f22b4c2611873a9ac491ce754aa2353b45e19ab508577ee99863128ed`)

Example `cp` and `put-object` commands:
```
aws s3 cp test.txt s3://MyBucket/test.txt --grants full=id=d9df08ac799f2859d42a588b415111314cf66d0ffd072195f33b921db966b440,id=9038e06f22b4c2611873a9ac491ce754aa2353b45e19ab508577ee99863128ed
```
```
aws s3api put-object --bucket MyBucket --key TestFolder/test.txt --body test.txt --grant-full-control id=d9df08ac799f2859d42a588b415111314cf66d0ffd072195f33b921db966b440,id=9038e06f22b4c2611873a9ac491ce754aa2353b45e19ab508577ee99863128ed
```

2. Check CloudWatch logs for the Lambda function to see if the function was triggered and completed successfully
3. Check Synapse project to see if filehandle was created
