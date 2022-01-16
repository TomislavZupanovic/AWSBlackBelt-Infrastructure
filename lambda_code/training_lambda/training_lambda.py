import json
from typing import Optional
import boto3
from datetime import datetime
import os

def get_latest_image() -> str:
    """ Filter images and return the latest pushed one in ECR Repository
        :argument: None
        :return: temp_tag - Tag of the latest Image in ECR Repository
    """
    ecr = boto3.client('ecr', region_name='us-east-1')
    response = ecr.list_images(repositoryName=os.environ['ECRRepositoryName'],
                                  maxResults=1000)
    latest = None
    temp_tag = None
    for image in response['imageIds']:
        tag = image['imageTag']
        img = ecr.describe_images(repositoryName=os.environ['ECRRepositoryName'],
                                     imageIds=[{'imageTag': tag}])
        pushed_at = img['imageDetails'][0]['imagePushedAt']
        if latest is None:
            latest = pushed_at
        else:
            if latest < pushed_at:
                latest = pushed_at
                temp_tag = tag
    return temp_tag

def parameters_file(action: str = "PUT", parameters: dict = None) -> Optional[dict]:
    """ Creates/updates or deletes the parameters JSON file saved for starting Training schedule 
        :argument: parameters - Dictionary containing key-value pairs to save 
        :argument: action - Defines creation, get or delete of parameters file
        :return: parameters_json - Dictionary with saved parameters if action GET, otherwise None
    """
    s3 = boto3.resource('s3')
    file_key = "config/training_schedule.json"
    # Get S3 object from given bucket and file key
    s3_object = s3.Object(os.environ['ArtifactsBucket'], file_key)
    # Create/update parameters file
    if action == "PUT":
        for key in ['cron', 'action']:
            del parameters[key]
        s3_object.put(Body=(bytes(json.dumps(parameters).encode('UTF-8'))))
    # Load parameters file
    elif action == "GET":
        file_content = s3_object.get()['Body'].read().decode('utf-8')
        parameters_json = json.loads(file_content)
        return parameters_json
    # Delete parameters file
    elif action == "DELETE":
        s3_object.delete()
            
    
def schedule_rule(cron: str, action: str = 'create') -> str:
    """ Creates/Updates or Deletes the schedule Cron event Rule 
        :argument: cron - Cron expression for time schedule
        :argument: action - Defines creation or deletion of time schedule
        :return: message - Message info for successful creation/deletion
    """
    events = boto3.client('events', region_name='us-east-1')
    # Reformat the cron expression
    cron_expression = f"cron({cron})"
    # Define Rule name
    rule_name = "TrainingSchedule"
    # Define Lambda target Id
    target_id = "TrainingScheduleTarget"
    if action == 'create':
        # Create/Update the Rule
        response = events.put_rule(Name=rule_name, ScheduleExpression=cron_expression,
                                   State='ENABLED', RoleArn=os.environ['EventRole'],
                                   Description='Cron schedule for training',
                                   Tags=[{'Key': 'Project', 'Value': os.environ['Project']},
                                         {'Key': 'Owner', 'Value': os.environ['Owner']}])
        # Define/Update the Rule target (this Lamdba)
        target_response = events.put_targets(Rule=rule_name, Targets=[
            {
                "Id": target_id,
                "Arn": f"arn:aws:lambda:{os.environ['Region']}:{os.environ['AccountId']}:function:{os.environ['SelfLambdaName']}" 
            }
        ])
        return f'Successfully created/updated Rule: {rule_name}'
    elif action == 'delete':
        # Remove the target from Rule then delete the Rule
        remove_target_response = events.remove_targets(Rule=rule_name, Ids=[target_id])
        delete_response = events.delete_rule(Name=rule_name)
        return f'Successfully delete Rule: {rule_name}'


def start_training(image_tag: str, parameters: dict) -> dict:
    """ Starts the Sagemaker Processing Job as training compute service with specific image tag 
        :argument: image_tag - Tag of the Image in the ECR Repository
        :return: response - Information about the started Processing Job
    """
    sagemaker = boto3.client("sagemaker", region_name='us-east-1')
    current_time = datetime.now().strftime("%y-%m-%d-%H-%M-%S")
    name = f"model-training-{current_time}"
    image = os.environ['ImageUri'] + ':' + image_tag
    environment = {}
    for name, value in parameters.items():
        environment[name] = value
    # Define the Sagemaker Processing Job parameters
    response = sagemaker.create_processing_job(ProcessingJobName=name,
                                               ProcessingResources={
                                                   'ClusterConfig': {
                                                       'InstanceCount': 1,
                                                       'InstanceType': 'ml.t3.medium',
                                                       'VolumeSizeInGB': 30
                                                   }
                                               },
                                               AppSpecification={
                                                   'ImageUri': image,
                                                   'ContainerEntrypoint': [
                                                       "python3", "training/train.py"
                                                   ]
                                               },
                                               NetworkConfig={
                                                   'VpcConfig': {
                                                       'SecurityGroupIds': [os.environ['SecurityGroupId']],
                                                       'Subnets': [os.environ['Subnet0'], os.environ['Subnet1']]
                                                   }
                                               },
                                               RoleArn=os.environ['SagemakerRoleArn'],
                                               Tags=[
                                                   {
                                                       'Key': 'Project',
                                                       'Value': os.environ["Project"]
                                                   },
                                                   {
                                                       'Key': 'Owner',
                                                       'Value': os.environ["Owner"]
                                                   }
                                               ],
                                               Environment=environment)
    return response

def construct_response(body: dict, status_code: int) -> dict:
    """ Constructs API Response 
        :argument: body - Content of the response body
        :argument: status_code - Response status code
        :return: responseObject - Constructed API Response
    """
    responseObject = {}
    responseObject['statusCode'] = status_code
    responseObject['headers'] = {}
    responseObject['headers']['Content-Type'] = 'application/json'
    responseObject['headers']['Access-Control-Allow-Origin'] = "*"
    responseObject['body'] = json.dumps(body)
    return responseObject
    
def lambda_handler(event, context):
    """ Function invoked by the AWS Lambda """
    api_resource = event.get('resource', None)
    if api_resource == '/start_training':
        body = json.loads(event['body'])
        image_tag = body.get('ImageTag', None)
        if image_tag is None:
            image_tag = get_latest_image()
        job_info = start_training(image_tag=image_tag, parameters=body)
        response = {'Message': 'Training successfully started!'}
        response['ImageTag'] = image_tag
        return construct_response(response, 200)
    elif api_resource == '/training_schedule':
        # Get parameters dictionary
        body = json.loads(event['body'])
        cron = body['Cron']
        action = body['Action']
        # If action is delete
        if action == 'delete':
            param_action = "DELETE"
        # If action is create
        else:
            param_action = "PUT"
        parameters_file(action=param_action, parameters=body)
        message = schedule_rule(cron, action)
        response = {'Message': message}
        return construct_response(response, 200)
    else:
        # If triggered by a Cron schedule
        resource = event['resources'][0]
        rule_name = resource.split('/')[1]
        # Get the parameters file as dictionary to start training on schedule
        parameters = parameters_file(action="GET")
        image_tag = get_latest_image()
        job_info = start_training(image_tag=image_tag, parameters=parameters)
        return {'status_code': 200, 'body': 'Successfully started training on schedule with latest image'}