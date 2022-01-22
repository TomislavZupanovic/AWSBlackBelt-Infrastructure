from aws_cdk import (
    aws_apigateway,
    aws_ecr,
    aws_ecs,
    aws_kms,
    aws_s3,
    aws_iam, aws_secretsmanager,
    aws_ec2, aws_rds, aws_route53,
    aws_lambda, aws_s3_notifications,
    aws_stepfunctions_tasks, aws_stepfunctions,
    aws_ecs_patterns,
    RemovalPolicy,
    Tags, Stack, Duration, CfnOutput, Fn
)
from constructs import Construct



class InferenceStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, parameters: dict, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        
        # Get Account environment parameters
        self.account_id = parameters["AccountId"]
        self.acc_region = parameters["Region"]
        self.owner = parameters["Owner"]
        self.project = parameters["Project"]
        
        # Define Tags for all resources (where they apply)
        Tags.of(self).add("Project", self.project)
        Tags.of(self).add("Owner", self.owner)
        
        #===========================================================================================================================
        #=========================================================VPC===============================================================
        #===========================================================================================================================

        # Import VPC and subnets
        self.vpc = aws_ec2.Vpc.from_lookup(self, "MainVPC", vpc_name=parameters['VPCName'])
        subnets = self.vpc.private_subnets
        all_private_subnets = [subnet.subnet_id for subnet in subnets]
        subnets_ids = [parameters["Subnet1_Id"], parameters["Subnet2_Id"]]
        
        # Import Security Group with allowed outbound traffic from ModelDevelopmnet Stack
        self.outbound_security_group = aws_ec2.SecurityGroup.from_security_group_id(self, "ImportedSecurityGroup",
                                                                                    security_group_id=Fn.import_value("SecurityGroupId"))
        
        # Define Subnet Selection
        selected_subnets = [aws_ec2.Subnet.from_subnet_attributes(self, "ImportedSubnet1", subnet_id=parameters["Subnet1_Id"],
                                                                  availability_zone='us-east-1a', route_table_id='rtb-0e9876e2b4570bf40'),
                            aws_ec2.Subnet.from_subnet_attributes(self, "ImportedSubnet2", subnet_id=parameters["Subnet2_Id"],
                                                                  availability_zone='us-east-1b', route_table_id='rtb-092c66b81271f6fde')]
        subnet_selection = aws_ec2.SubnetSelection(subnets=selected_subnets)
        
        #===========================================================================================================================
        #=========================================================ECR===============================================================
        #===========================================================================================================================
        
        # Import the ECR repository from the Model Development Stack
        ecr_repository = aws_ecr.Repository.from_repository_attributes(self, "ImportedECRRepository",
                                                                repository_arn=Fn.import_value("ECRRepositoryArn"),
                                                                repository_name=Fn.import_value("ECRRepositoryName"))
        
        #===========================================================================================================================
        #=======================================================LAMBDA==============================================================
        #===========================================================================================================================
        
        # Define the Lambda Policy
        lambda_policy = aws_iam.ManagedPolicy(self, "LambdaPolicy", description="Used for Inference Lambda permissions",
                                               managed_policy_name="mlops-inference-lambda-policy",
                                               statements=[
                                                   aws_iam.PolicyStatement(
                                                        sid="CloudWatchLogsAccess",
                                                        effect=aws_iam.Effect.ALLOW,
                                                        actions=[
                                                            "logs:CreateLogGroup",
                                                            "logs:PutLogEvents",
                                                            "logs:CreateLogStream"
                                                        ],
                                                        resources=[
                                                            f"arn:aws:logs:{self.acc_region}:{self.account_id}:log-group:/aws/lambda/*"
                                                        ]
                                                    ),
                                                    aws_iam.PolicyStatement(
                                                        sid="VPCAccessPolicy",
                                                        effect=aws_iam.Effect.ALLOW,
                                                        actions=[
                                                            "ec2:CreateNetworkInterface",
                                                            "ec2:DescribeDhcpOptions",
                                                            "ec2:DescribeNetworkInterfaces",
                                                            "ec2:DeleteNetworkInterface",
                                                            "ec2:DescribeSubnets",
                                                            "ec2:DescribeSecurityGroups",
                                                            "ec2:DescribeVpcs"
                                                        ],
                                                        resources=[
                                                            "*"
                                                        ]
                                                    ),
                                                    aws_iam.PolicyStatement(
                                                        sid="ECRReadAccess",
                                                        effect=aws_iam.Effect.ALLOW,
                                                        actions=[
                                                            "ecr:DescribeImages",
                                                            "ecr:DescribeRepositories",
                                                            "ecr:BatchGetImage",
                                                            "ecr:GetDownloadUrlForLayer",
                                                        ],
                                                        resources=[
                                                            ecr_repository.repository_arn
                                                        ]
                                                    ),
                                                    aws_iam.PolicyStatement(
                                                        sid="SagemakerAccess",
                                                        effect=aws_iam.Effect.ALLOW,
                                                        actions=[
                                                            "sagemaker:*TransformJob",
                                                            "sagemaker:*TransformJobs",
                                                            "sagemaker:*ProcessingJob",
                                                            "sagemaker:*ProcessingJobs",
                                                            "iam:PassRole",
                                                        ],
                                                        resources=[
                                                            "*"
                                                        ]
                                                    ),
                                                    aws_iam.PolicyStatement(
                                                        sid="EventsAccess",
                                                        effect=aws_iam.Effect.ALLOW,
                                                        actions=[
                                                            "events:*"
                                                        ],
                                                        resources=[
                                                            "*"
                                                        ]
                                                    ),
                                               ]
                                            )
        
        # Define Lambda Role
        lambda_role = aws_iam.Role(self, "LambdaRole", role_name="mlops-inference-lambda-role",
                                    assumed_by=aws_iam.ServicePrincipal("lambda.amazonaws.com"),
                                    managed_policies=[lambda_policy])
        
        # Define Lambda function
        inference_lambda_name = "mlops-inference-lambda"
        inference_lambda = aws_lambda.Function(self, "InferenceLambda", role=lambda_role,
                                              runtime=aws_lambda.Runtime.PYTHON_3_8,
                                              handler="inference_lambda.lambda_handler",
                                              vpc=self.vpc, vpc_subnets=aws_ec2.SubnetType.PRIVATE_WITH_NAT,
                                              security_groups=[self.outbound_security_group],
                                              code=aws_lambda.Code.from_asset("lambda_code/inference_lambda"),
                                              environment={
                                                        "SagemakerRoleArn": Fn.import_value("SagemakerRoleArn"),
                                                        "ImageUri": ecr_repository.repository_uri,
                                                        "SecurityGroupId": self.outbound_security_group.security_group_id,
                                                        "Subnet0": subnets_ids[0],
                                                        "Subnet1": subnets_ids[1],
                                                        "Region": self.acc_region,
                                                        "AccountId": self.account_id,
                                                        "ArtifactsBucket": Fn.import_value("ArtifactsBucketName"),
                                                        "SelfLambdaName": inference_lambda_name,
                                                        "EventRole": Fn.import_value("EventRoleArn"),
                                                        "Owner": self.owner,
                                                        "Project": self.project
                                                  },
                                              timeout=Duration.minutes(5), 
                                              function_name=inference_lambda_name,
                                              description="Used for starting the Sagemaker Processing Job for Batch Inference")
        
        # Add invocation permission for EventBridge
        events_principal = aws_iam.ServicePrincipal("events.amazonaws.com")
        inference_lambda.grant_invoke(events_principal)
        #===========================================================================================================================
        #=======================================================KMS & SECRET==============================================================
        #===========================================================================================================================
        
        # Import KMS key
        # kms_key = aws_kms.Key.from_key_arn(self, "ImportedKMSKey", key_arn=Fn.import_value("KMSKeyARN"))
        
        # Define the Secret for Grafana Aurora DB
        # grafana_db_secret = aws_secretsmanager.Secret(self, "GrafanaDatabaseSecret",
        #                                              description="Secret used for connecting to the Grafana MySQL database",
        #                                              secret_name="mlops-grafana-db",
        #                                              removal_policy=RemovalPolicy.DESTROY,
        #                                              generate_secret_string=aws_secretsmanager.SecretStringGenerator(
        #                                                  exclude_characters='/@"\' ',
        #                                                  exclude_punctuation=True,
        #                                                  generate_string_key="password",
        #                                                  secret_string_template="{\"username\":\"grafana_user\"}"
        #                                              ))
        
        # Import the MLflow secret to reuse for Grafana Aurora DB
        grafana_db_secret = aws_secretsmanager.Secret.from_secret_complete_arn(self, "ImportedDBSecret", 
                                                                               secret_complete_arn=Fn.import_value("SecretARN"))
        
        #===========================================================================================================================
        #=======================================================AURORA==============================================================
        #===========================================================================================================================
        
        # Import Aurora Security Group from Model Developmnet Stack
        aurora_security_group = aws_ec2.SecurityGroup.from_security_group_id(self, "ImportedAuroraSecurityGroup",
                                                     security_group_id=Fn.import_value("AuroraSecurityGroupId"))
        
        # Define Grafana backend Aurora Database
        grafana_database_name = "Grafana"
        grafana_backend_db = aws_rds.ServerlessCluster(self, "GrafanaBackendDB",
                                                      engine=aws_rds.DatabaseClusterEngine.AURORA_MYSQL,
                                                      credentials=aws_rds.Credentials.from_secret(grafana_db_secret),
                                                      vpc=self.vpc,
                                                      vpc_subnets=subnet_selection,
                                                      security_groups=[aurora_security_group],
                                                      default_database_name=grafana_database_name,
                                                      cluster_identifier="mlops-grafana")
        # Define the Grafana DB endpoint
        grafana_db_endpoint = grafana_backend_db.cluster_endpoint
        
        #===========================================================================================================================
        #=======================================================FARGATE=============================================================
        #===========================================================================================================================
        
        # Import the Fargate Cluster from Model Development stack
        fargate_cluster = aws_ecs.Cluster.from_cluster_attributes(self, "ImportedFargateCluster",
                                                                  cluster_arn=Fn.import_value("FargateClusterARN"),
                                                                  cluster_name=Fn.import_value("FargateClusterName"),
                                                                  security_groups=[self.outbound_security_group],
                                                                  vpc=self.vpc)
        
        # Import the Fargate Role from Model Development Stack
        fargate_role = aws_iam.Role.from_role_arn(self, "ImportedFargateRole", 
                                                  role_arn=Fn.import_value("FargateRoleARN"))
        
        # Import the Fargate Security Group from Model Development Stack
        fargate_security_group =  aws_ec2.SecurityGroup.from_security_group_id(self, "ImportedFargateSecurityGroup",
                                                     security_group_id=Fn.import_value("FargateSecurityGroupId"))
        
        #===========================================================================================================================
        #=======================================================GRAFANA=============================================================
        #===========================================================================================================================
        
        # Define Grafana Task Definition
        grafana_task_definition = aws_ecs.FargateTaskDefinition(self, "GrafanaTaskDefinition", cpu=1024, ephemeral_storage_gib=30,
                                                               memory_limit_mib=4096, execution_role=fargate_role,
                                                               family="mlops-grafana-task", task_role=fargate_role)
        
        # Define the Grafana Task Container 
        grafana_task_definition.add_container("GrafanaImageContainer",
                                             image=aws_ecs.ContainerImage.from_asset(directory="grafana"),
                                             container_name="grafana-task-container", privileged=False,
                                             port_mappings=[aws_ecs.PortMapping(container_port=3000, protocol=aws_ecs.Protocol.TCP)],
                                             secrets={
                                                 "DB_USERNAME": aws_ecs.Secret.from_secrets_manager(grafana_db_secret, "username"),
                                                 "DB_PASSWORD": aws_ecs.Secret.from_secrets_manager(grafana_db_secret, "password")
                                             },
                                             environment={
                                                 "HOST": grafana_db_endpoint.hostname,
                                                 "PORT": "3306",
                                                 "DATABASE": grafana_database_name,
                                             })
        
        # Define the Load Balanced Service for Grafana
        grafana_load_balanced_service = aws_ecs_patterns.ApplicationLoadBalancedFargateService(
            self, "GrafanaLoadBalancedService", assign_public_ip=False, cpu=1024, 
            memory_limit_mib=4096, security_groups=[fargate_security_group],
            task_definition=grafana_task_definition, cluster=fargate_cluster,
            task_subnets=subnet_selection,
            desired_count=1, listener_port=80, load_balancer_name="mlops-grafana-load-balancer",
            open_listener=False, public_load_balancer=True, 
            service_name="mlops-grafana-service",
            health_check_grace_period=Duration.minutes(3)
        )
        # Attach Fargate Security Group to the Grafana Load Balancer
        grafana_load_balanced_service.load_balancer.add_security_group(fargate_security_group)
        grafana_load_balanced_service.target_group.configure_health_check(path="/login", interval=Duration.seconds(120),
                                                                         timeout=Duration.seconds(10))
        
        #===========================================================================================================================
        #=========================================================APIGATEWAY========================================================
        #===========================================================================================================================
        
        # Import the existing API Gateway (REST) from Development Stack
        api = aws_apigateway.RestApi.from_rest_api_attributes(self, "ImportedMLOpsAPI", rest_api_id=Fn.import_value("APIid"),
                                                              root_resource_id=Fn.import_value("APIRoot"))
        
         # Define Integration Lambda with API Gateway
        inference_integration = aws_apigateway.LambdaIntegration(inference_lambda)
        
        # Define the API Resources and methods
        inference_resource = api.root.add_resource("start_batch_inference")
        inference_resource.add_method("POST", inference_integration)
        
        schedule_resource = api.root.add_resource("inference_schedule")
        schedule_resource.add_method("POST", inference_integration)