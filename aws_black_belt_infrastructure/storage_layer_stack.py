from aws_cdk import (
    core as cdk
    # aws_sqs as sqs,
)

class StorageLayerStack(cdk.Stack):

    def __init__(self, scope: cdk.Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        
