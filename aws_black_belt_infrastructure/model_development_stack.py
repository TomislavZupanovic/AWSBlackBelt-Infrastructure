from aws_cdk import (
    core as cdk,
    aws_s3,
    aws_iam,
    aws_ec2
)

class ModelDevelopment(cdk.Stack):

    def __init__(self, scope: cdk.Construct, construct_id: str, parameters: dict, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Get Account environment parameters
        account_id = parameters["AccountId"]
        region = parameters["Region"]

        # Define Tags for all resources (where they apply)
        cdk.Tags.of(self).add("Project", "BlackBelt")
        cdk.Tags.of(self).add("Owner", "Tomislav Zupanovic")
        
        #===========================================================================================================================
        #=========================================================VPC===============================================================
        #===========================================================================================================================

        # Import VPC and subnets
        vpc = aws_ec2.Vpc.from_lookup(self, "MainVPC", vpc_name="aast-innovation-vpc")
        subnets = vpc.private_subnets
        subnets_ids = [subnet.subnet_id for subnet in subnets]
        
        # Define Security Group with allowed outbound traffic
        outbound_security_group = aws_ec2.SecurityGroup(self, "OutboundSecurityGroup",
                                                        vpc=vpc, description="Allow all outbound access only",
                                                        allow_all_outbound=True)