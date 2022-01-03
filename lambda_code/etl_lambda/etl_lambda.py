import json
from typing import Optional
import boto3
from datetime import datetime
import os

def start_etl(bucket: str, file_key: str) -> dict:
    """ Starts the Step Functions tasks for ETL process 
        :argument: bucket - Name of the S3 bucket where data lands
        :argument: file_key - S3 path to the file that lands in bucket
        :return: execution_response - dictionary containing info about started SF execution
    """
    step_functions = boto3.client('stepfunctions')
    current_time = datetime.now().strftime("%y-%m-%d-%H-%M-%S")
    # Define parameters for Step Function
    input_parameters = {"bucket": bucket, "file_key": file_key}
    # Start the Step Function
    execution_response = step_functions.start_execution(stateMachineArn=os.environ['StateMachineArn'],
                                                        name=f"ETL-{current_time}",
                                                        input=json.dumps(input_parameters))
    return execution_response

def lambda_handler(event, context):
    """ Function invoked by the AWS Lambda """
    s3_info = event['Records'][0]['s3']
    # Get Bucket name and file path
    bucket = s3_info['bucket']['name']
    file_key = s3_info['object']['key']
    # Start ETL Step Function process
    response = start_etl(bucket=bucket, file_key=file_key)
    return {'status_code': 200, 'body': 'Successfully started ETL process'}