#!/usr/bin/env python3
import os
import aws_cdk as cdk
from aws_black_belt_infrastructure.storage_layer_stack import StorageLayer
from aws_black_belt_infrastructure.model_development_stack import ModelDevelopment
from aws_black_belt_infrastructure.model_inference_stack import InferenceStack


# Initialize the CDK app
app = cdk.App()

# Define the Account parameters for Stacks
parameters = {"Owner": "*******",
              "Project": "*******",
              "AccountId": "*******",
              "Region": "*******",
              "VPCEndpointId": "*******",
              "VPCSecurityGroupId": "*******",
              "VPCName": "*******",
              "CodeCommitRepoARN": "*******",
              "Subnet1_Id": "*******", 
              "Subnet2_Id": "*******",
              "RouteTableId1": "*******",
              "RouteTableId2": "*******",
              "Az1": "*******",
              "Az2": "*******"} 


# Define the CDK Environment parameters
environment = cdk.Environment(account=parameters["AccountId"], region=parameters["Region"])

# Initialize the Stacks
ModelDevelopment(app, "ModelDevelopmentStack", env=environment, parameters=parameters)
StorageLayer(app, "StorageLayerStack", env=environment, parameters=parameters)
InferenceStack(app, "InferenceStack", env=environment, parameters=parameters)

# Synth the CDK app
app.synth()
