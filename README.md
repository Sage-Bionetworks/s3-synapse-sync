# s3-synapse-sync

Lambda function code to index files in S3 buckets by creating filehandles on Synapse, triggered by file changes to S3.

## Requirements
- Python 3.6+

## Getting started

Confirm [center onboarding](https://docs.google.com/document/d/1cCRkfK6or6lwMNc96f5LTp9rK8aHEDqhyP0ISgSn9sI/edit) steps are complete, and a Synapse project has been created to which the bucket will be synced.

### Configure lambda and bucket policies

Note: The steps below outline the setup for a case where the Lambda function is deployed in **Account A** and **Account B** contains the bucket. Steps 5a and 6 may be omitted when the bucket and lambda are in the same account.

1. From **Account A**, create two IAM policies: `S3SynapseLambdaExecute` and `SSMParameterStore`
    - From the AWS Management Console, select **IAM** > **Policies** > **Create Policy**

`S3SynapseLambdaExecute` policy json:
```
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "logs:*"
            ],
            "Resource": "arn:aws:logs:*:*:*"
        },
        {
            "Effect": "Allow",
            "Action": [
                "s3:GetObject",
                "s3:PutObject",
                "s3:PutObjectAcl"
            ],
            "Resource": "arn:aws:s3:::*"
        }
    ]
}
```
`SSMParameterStore` policy json:
```
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "ssm:DescribeParameters"
            ],
            "Resource": "*"
        },
        {
            "Effect": "Allow",
            "Action": [
                "ssm:GetParameters",
                "ssm:GetParameter"
            ],
            "Resource": "arn:aws:ssm:us-east-1:<AccountA-AWS-id>:parameter/*"
        }
    ]
}
```
2. From **Account A**, create an execution role to allow the Lambda function permission to access AWS services
    - From the AWS Management Console, select the **IAM** > **Roles** > **Create Role**
    - Create a role with the following properties.
        - **Trusted entity** – AWS Lambda
        - **Permissions** – `S3SynapseLambdaExecute` & `SSMParameterStore`
        - **Role name** – `htan-lambda-s3-role`

3. From **Account A**, create the Lambda Function
    - From the AWS Management Console, select **Lambda** > **Create function**
    - Set **Runtime** to corresponding Python version
    - Under **Execution role**, choose ‘Use an existing role’ and select the newly created `htan-lambda-s3-role`
    - Note: Lambda and bucket must be in the same region

4. From **Account B**, create a bucket

    - *Bucket name must start with a letter and can only contain letters, numbers, and underscores*
    - Note: Lambda and bucket must be in the same region

5. From **Account B**, configure your bucket to be the external storage location of your Synapse project, as outlined in [Synapse documentation](https://docs.synapse.org/articles/custom_storage_location.html#toc-custom-storage-locations)

    5a. Add additional statements to the read-write bucket policy, as well as ARNs of external collaborators and any additional users to allow them CLI access to the bucket. Example policy below:

```
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {
                "AWS": [
                    "arn:aws:iam::325565585839:root",
                    "<external-collaborator-arn>",
                    "<additional-user-arn>"
                ]
            },
            "Action": [
                "s3:ListBucket*",
                "s3:GetBucketLocation"
            ],
            "Resource": "arn:aws:s3:::<bucket-name>"
        },
        {
            "Effect": "Allow",
            "Principal": {
                "AWS": [
                    "arn:aws:iam::325565585839:root",
                    "<external-collaborator-arn>",
                    "<additional-user-arn>"
                ]
            },
            "Action": [
                "s3:*Object*",
                "s3:*MultipartUpload*"
            ],
            "Resource": "arn:aws:s3:::<bucket-name>/*"
        },
        {
            "Effect": "Allow",
            "Principal": {
                "AWS": [
                    "arn:aws:iam::<accountA-accountID>:role/htan-lambda-s3-role",
                    "<external-collaborator-arn>",
                    "<additional-user-arn>"
                ]
            },
            "Action": [
                "s3:GetObject",
                "s3:PutObject",
                "s3:PutObjectAcl"
            ],
            "Resource": "arn:aws:s3:::<bucket-name>/*"
        },
        {
            "Effect": "Deny",
            "Principal": "*",
            "Action": "s3:PutObject",
            "Resource": "arn:aws:s3:::<bucket-name>/*",
            "Condition": {
                "StringNotEqualsIgnoreCase": {
                    "s3:x-amz-grant-full-control": "id=d9df08ac799f2859d42a588b415111314cf66d0ffd072195f33b921db966b440,id=9038e06f22b4c2611873a9ac491ce754aa2353b45e19ab508577ee99863128ed"
                },
                "StringNotEquals": {
                    "s3:x-amz-grant-full-control": "id=d9df08ac799f2859d42a588b415111314cf66d0ffd072195f33b921db966b440, id=9038e06f22b4c2611873a9ac491ce754aa2353b45e19ab508577ee99863128ed"
                }
            }
        }
    ]
}
```
6. Use the AWS CLI to grant permission for the **Account B** bucket to invoke the Lambda function in **Account A**:
```
aws lambda add-permission --function-name <accountA-functionName> --action lambda:InvokeFunction --statement-id <value> \
--principal s3.amazonaws.com --source-arn arn:aws:s3:::<accountB-bucketName> --source-account <accountB-accountID>
```
7. From the bucket console in **Account B**, add event notifications to trigger the Lambda function
    - From the bucket console, select **Properties** > **Events** > **Add Notification**
    - Select `All Object Create Events` and `All Object Delete Events`
    - Under **Send to**, select `Lambda function`
    - Enter the lambda function ARN, and save the notification

CLI:
```
aws s3api put-bucket-notification-configuration --bucket <bucket> --notification-configuration file://s3lambda_notif.json
```
s3lambda_notif.json:
```
{
  "LambdaFunctionConfigurations": [
    {
        "LambdaFunctionArn": "arn:aws:lambda:<region>:<AWS-account-ID>:function:<Lambda-name>",
        "Events": [
            "s3:ObjectCreated:*",
            "s3:ObjectRemoved:*"
      ]
    }
  ]
}
```


---

## Deploy Lambda function via AWS Console
#### Create a deployment package
1. Save `lambda_function.py` locally to \<your-project\>
2. Create a virtual environment
```
cd <your-project>
python -m venv venv
source venv/bin/activate
```
3. Install libraries in the virtual environment
```
(venv) pip install synapseclient
```
4. Create a deployment package with the contents of the installed libraries.
```
(venv) cd $VIRTUAL_ENV/lib/<python3.x>/site-packages
(venv) zip -r9 ${OLDPWD}/synapse_function.zip .
```
5. Add the handler code to the deployment package and deactivate the virtual environment.
```
(venv) cd ${OLDPWD}
(venv) zip -g synapse_function.zip lambda_function.py
(venv) deactivate
```

#### Deploy
1. From **Account A**, navigate to your Lambda function
    - In the Function code box under **Code entry type**, select 'Upload a .zip file'
    - Click 'Upload' to upload the `synapse_function.zip` deployment package
2. Initial (one time) setup: \
    From **Account A**, add parameters to SSM Parameter Store \
    Create **SecureString** parameters ensuring each parameter name aligns with the format specified below:

| Parameter Name  | Value Description | Type |
| ------------- | ------------- | ------------- |
| `/HTAN/SynapseSync/username`  | Synapse service account username  | SecureString |
| `/HTAN/SynapseSync/apiKey`  | Synapse API Key | SecureString |

```
aws ssm put-parameter --name /HTAN/SynapseSync/<parameter> --value <value> --type SecureString
```

3. From **Account A**, add bucket-specific environment variables for each subsequent bucket:

| Environment Variable Name  | Value Description |
| ------------- | ------------- |
| `<bucket_name>_synapseProjectId` | Synapse ID of project; an identifier with the format `syn12345678` |
| `<bucket_name>_foldersToSync` | Comma separated list of folders in bucket to be synchronized to Synapse |

```
aws lambda update-function-configuration --function-name <value> --environment Variables="{<bucket_name>_synapseProjectId=<value>,<bucket_name>_foldersToSync=<value>}"
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

---
### Sync Existing Files
To sync files already in a bucket, complete the steup and deployment steps above, then run the following command with your bucket and folder name. This will effectively "touch" all files within that folder by adding a metadata attribute, and trigger the Lambda function to sync the files to Synapse.

```
aws s3 cp --metadata {\"toSynapse\":\"true\"} s3://<MyBucket>/<folder-to-sync>/ s3://<MyBucket>/<folder-to-sync>/ --recursive
```

---

## Development

### Requirements
Run `pipenv install --dev` to install both production and development
requirements, and `pipenv shell` to activate the virtual environment. For more
information see the [pipenv docs](https://pipenv.pypa.io/en/latest/).

After activating the virtual environment, run `pre-commit install` to install
the [pre-commit](https://pre-commit.com/) git hook.

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
