import json
import boto3
from datetime import datetime
import os

def get_latest_image():
    """ Filter images and return the latest pushed one """
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
                                                       'Subnets': [os.environ['Subnet0'], os.environ['Subnet1'],
                                                                   os.environ['Subnet2'], os.environ['Subnet3']]
                                                   }
                                               },
                                               RoleArn=os.environ['SagemakerRoleArn'],
                                               Tags=[
                                                   {
                                                       'Key': 'Project',
                                                       'Value': 'BlackBelt'
                                                   },
                                                   {
                                                       'Key': 'Owner',
                                                       'Value': 'Tomislav Zupanovic'
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
        image_tag = body['ImageTag']
        job_info = start_training(image_tag=image_tag, parameters=body)
        response = {'Message': 'Training successfully started!'}
        response['ImageTag'] = image_tag
        return construct_response(response, 200)
    
    return {'status_code': 200}