#!/usr/bin/env python3
import os
from aws_cdk import core as cdk
from aws_black_belt_infrastructure.storage_layer_stack import StorageLayer
from aws_black_belt_infrastructure.model_development_stack import ModelDevelopment


# Initialize the CDK app
app = cdk.App()

# Define the Account parameters for Stacks
parameters = {"AccountId": "167321155121",
              "Region": "us-east-1"}

# Define the CDK Environment parameters
environment = cdk.Environment(account=parameters["AccountId"], region=parameters["Region"])

# Initialize the Stacks
StorageLayer(app, "StorageLayerStack", env=environment, parameters=parameters)
ModelDevelopment(app, "ModelDevelopmentStack", env=environment, parameters=parameters)

# Synth the CDK app
app.synth()
