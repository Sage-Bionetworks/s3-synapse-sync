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
Add two **SecureString** parameters containing Synapse credentials to SSM Parameter Store

| Parameter Name  | Value | Type |
| ------------- | ------------- | ------------- |
| `/HTAN/SynapseSync/username`  | Synapse service account username  | SecureString |
| `/HTAN/SynapseSync/apiKey`  | Synapse service account API Key | SecureString |

```
aws ssm put-parameter --name /HTAN/SynapseSync/<parameter> --value <value> --type SecureString
```

#### Environment Variables
This lambda requires the environment variable `BUCKET_VARIABLES`: a yaml-format string that defines for each HTAN bucket:

- The ID of the center's Synapse project
- Folders in the bucket to be synced to Synapse

Example:
```
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

config/prod/s3-synapse-sync.yaml
```yaml
template_path: "remote/s3-synapse-sync.yaml"
stack_name: "s3-synapse-sync"
stack_tags:
  Department: "Platform"
  Project: "Infrastructure"
  OwnerEmail: "it@sagebase.org"
hooks:
  before_launch:
    - !cmd "curl https://s3.amazonaws.com/bootstrap-awss3cloudformationbucket-19qromfd235z9/s3-synapse-sync/master/s3-synapse-sync.yaml --create-dirs -o templates/remote/s3-synapse-sync.yaml"
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
