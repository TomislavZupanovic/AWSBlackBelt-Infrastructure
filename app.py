#!/usr/bin/env python3
import os
import aws_cdk as cdk
from aws_black_belt_infrastructure.storage_layer_stack import StorageLayer
from aws_black_belt_infrastructure.model_development_stack import ModelDevelopment
from aws_black_belt_infrastructure.model_inference_stack import InferenceStack


# Initialize the CDK app
app = cdk.App()

# Define the Account parameters for Stacks
parameters = {"Owner": "Tomislav Zupanovic",
              "Project": "BlackBelt",
              "AccountId": "167321155121",
              "Region": "us-east-1",
              "VPCEndpointId": "vpce-0a7e4031f9928bdbc",
              "VPCSecurityGroupId": "sg-00068c8858ad5df0b",
              "VPCName": "aast-innovation-vpc",
              "CodeCommitRepoARN": "arn:aws:codecommit:us-east-1:167321155121:AWSBlackBelt-PredictiveMaintenance",
              "Subnet1_Id": "subnet-0d964588c17bea68c",  # If specific Subnet selection is needed
              "Subnet2_Id": "subnet-0a3e3e2004c57c418"}  # If specific Subnet selection is needed

# Define the CDK Environment parameters
environment = cdk.Environment(account=parameters["AccountId"], region=parameters["Region"])

# Initialize the Stacks
ModelDevelopment(app, "ModelDevelopmentStack", env=environment, parameters=parameters)
StorageLayer(app, "StorageLayerStack", env=environment, parameters=parameters)
InferenceStack(app, "InferenceStack", env=environment, parameters=parameters)

# Synth the CDK app
app.synth()
