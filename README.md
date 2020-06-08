## s3-synapse-sync

Lambda function code to index files in S3 bucket by creating filehandles on Synapse, triggered by file changes to S3.

### Requirements
- Python 3.6+

### Getting started
- Configure S3 bucket and Synapse project as outlined in [Synapse documentation](https://docs.synapse.org/articles/custom_storage_location.html#toc-custom-storage-locations)

---

## Deploy
### via AWS Serverless CLI
(See instructions for AWS Serverless setup at end of this README)

1. Clone this repository, and modify serverless.yml to define environment variables and S3 trigger bucket

    The function source code requires four input variables: 
    - `username`: Synapse account username 
    - `apiKey`: Synapse API Key. Can be found under Settings on Synapse
    - `synapseProjectId`: Synapse ID of project, a unique identifier with the format `syn12345678`
    - `foldersToSync`: Comma separated list of folders in bucket to be synchronized to Synapse 


2. Change directory to within the repository, and install the Python requirements plugin
``` 
serverless plugin install -n serverless-python-requirements
```
3. Deploy function
``` 
serverless deploy
```


### via AWS Console
#### Create a deployment package
- Verify your AWS IAM user policy includes Lambda, S3, and CloudWatch Logs access
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

#### Deploy Lambda Function
1. Create an execution role to allow Lambda functions permission to access AWS services
    - From the AWS Management Console, select the IAM resource
    - Under the ‘Roles’ page, select **Create Role**
    - Create a role with the following properties.
        - **Trusted entity** – AWS Lambda.
        - **Permissions** – AWSLambdaExecute.
        - **Role name** – `lambda-s3-role`
2. From the AWS Management Console, select the **Lambda** resource and **Create function**
    - Set **Runtime** to corresponding Python version
    - Under **Execution role**, choose ‘Use an existing role’ and select the newly created `lambda-s3-role` 
3. Select your function from the Lambda console and click **Add trigger** in the Designer box
    - To create 'Object Create' trigger:
        - Select `S3` from the dropdown menu
        - Select your S3 bucket
        - Under **Event type** select `All Object Create Events` 
    - To create 'Object Delete' trigger:
        - Select `S3` from the dropdown menu
        - Select your S3 bucket 
        - Under **Event type** select `All Object Delete Events` 
4. In the Function code box:
    - Under **Code entry type**, select 'Upload a .zip file'
    - Click 'Upload' to upload the `synapse_function.zip` deployment package
5. In the Environment variables box, define environment variables. The function source code requires four input variables: 
    - `username`: Synapse account username 
    - `apiKey`: Synapse API Key. Can be found under Settings on Synapse
    - `synapseProjectId`: Synapse ID of project, a unique identifier with the format `syn12345678`
    - `foldersToSync`: Comma separated list of folders in bucket to be synchronized to Synapse

---

### To Test: 
1. Place a file in one of the folders specified in `foldersToSync` environment variable
2. Check CloudWatch logs for the Lambda function to see if the function was triggered and completed successfully 
3. Check Synapse project to see if filehandle was created

---

### Installing Serverless and Configuring AWS Profile
1. Install [Serverless framework](https://www.serverless.com/framework/docs/getting-started/) 
```
npm install -g serverless 
```
2. Enable permissions
- On the AWS console under the IAM resource, click **Policies** --> **Create policy**
    - Select the JSON tab and add `IAMPolicy.json` file
    - Give policy a descriptive name i.e. 'serverless-agent'
- Under the IAM resource, click **Users**
    - Create a new user, or apply 'serverless-agent' policy to existing user, ensuring Programmatic access is enabled
    - Save user credentials (Access Key ID and Secret Access Key) 
        
3. Configure AWS Profile with credentials
```
serverless config credentials --provider aws --key AKIAIOSFODNN7EXAMPLE --secret wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
```
