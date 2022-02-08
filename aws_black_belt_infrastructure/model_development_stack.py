from aws_cdk import (
    aws_s3,
    aws_iam, aws_logs,
    aws_ec2,
    aws_secretsmanager,
    aws_kms,
    aws_rds,
    aws_ecs,
    aws_ecs_patterns,
    aws_lambda,
    aws_ecr,
    aws_codecommit, aws_events_targets,
    aws_codebuild, aws_apigateway,
    RemovalPolicy, Duration,
    Tags, Stack, CfnOutput
)
from constructs import Construct

class ModelDevelopment(Stack):
    def __init__(self, scope: Construct, construct_id: str, parameters: dict, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Get Account environment parameters
        self.account_id = parameters["AccountId"]
        self.acc_region = parameters["Region"]
        self.vpc = None
        self.outbound_security_group = None
        self.vpc_endpoint_id = parameters["VPCEndpointId"]
        self.vpc_security_group_id = parameters["VPCSecurityGroupId"]
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
        
        # Define Security Group with allowed outbound traffic
        self.outbound_security_group = aws_ec2.SecurityGroup(self, "OutboundSecurityGroup",
                                                        vpc=self.vpc, description="Allow all outbound access only",
                                                        allow_all_outbound=True, security_group_name="mlops-security-group")
        
        # Import VPC Endpoint Security Group
        # vpc_endpoint_security_group = aws_ec2.SecurityGroup.from_security_group_id(
        #     self, "VPCEndpointSecurityGroupImport", security_group_id=self.vpc_security_group_id
        # )

        # Define Subnet Selection
        selected_subnets = [aws_ec2.Subnet.from_subnet_attributes(self, "ImportedSubnet1", subnet_id=parameters["Subnet1_Id"],
                                                                  availability_zone='us-east-1a', route_table_id='rtb-0e9876e2b4570bf40'),
                            aws_ec2.Subnet.from_subnet_attributes(self, "ImportedSubnet2", subnet_id=parameters["Subnet2_Id"],
                                                                  availability_zone='us-east-1b', route_table_id='rtb-092c66b81271f6fde')]
        subnet_selection = aws_ec2.SubnetSelection(subnets=selected_subnets)
        
        # VPC Endpoint for API Gateway
        vpc_endpoint = aws_ec2.InterfaceVpcEndpoint(self, "VPCEndpointInterface", 
                                                    vpc=self.vpc, service=aws_ec2.InterfaceVpcEndpointService(
                                                        name="com.amazonaws.us-east-1.execute-api", port=443
                                                    ), subnets=subnet_selection)
        
        #===========================================================================================================================
        #=========================================================S3================================================================
        #===========================================================================================================================

        # Define the Artifacts Bucket for MLflow
        artifacts_bucket = aws_s3.Bucket(self, "ArtifactsBucket", bucket_name="mlops-artifacts-bucket",
                                       block_public_access=aws_s3.BlockPublicAccess.BLOCK_ALL,
                                       public_read_access=False, removal_policy=RemovalPolicy.DESTROY,
                                       versioned=False, encryption=aws_s3.BucketEncryption.S3_MANAGED)
        
        #===========================================================================================================================
        #=========================================================KMS & SECRET======================================================
        #===========================================================================================================================
        
        # Define the KMS key for Secret Encryption/Decryption
        # kms_key = aws_kms.Key(self, "MLflowDBSecretKey", description="Key used for MLflow DB Secret",
        #                          enabled=True, enable_key_rotation=False,
        #                          policy=aws_iam.PolicyDocument(
        #                                     statements=[aws_iam.PolicyStatement(
        #                                         actions=["kms:Create*", 
        #                                                  "kms:Describe*", 
        #                                                  "kms:Enable*", 
        #                                                  "kms:List*", 
        #                                                  "kms:Put*"
        #                                         ],
        #                                         principals=[aws_iam.AccountRootPrincipal()],
        #                                         resources=["*"]
        #                                     )])) # removal_policy=RemovalPolicy.DESTROY)
        
        # Define the Secret for MLflow Aurora DB
        mlflow_db_secret = aws_secretsmanager.Secret(self, "MLflowDBSecret",
                                                     description="Secret used for connecting to the MLflow PostgreSQL database",
                                                     secret_name="mlops-mlflow-db-secret",
                                                     removal_policy=RemovalPolicy.DESTROY,
                                                     generate_secret_string=aws_secretsmanager.SecretStringGenerator(
                                                         exclude_characters='/@"\' ',
                                                         exclude_punctuation=True,
                                                         generate_string_key="password",
                                                         secret_string_template="{\"username\":\"mlflow_user\"}"
                                                     ))
        
        #===========================================================================================================================
        #=========================================================AURORA============================================================
        #===========================================================================================================================
        
        # Define Security group for serverless Aurora
        aurora_security_group = aws_ec2.SecurityGroup(self, "AuroraSecurityGroup",
                                                      vpc=self.vpc, description="Security group used for connecting to MLflow Database backend",
                                                      allow_all_outbound=True, security_group_name="mlops-aurora-security-group")
        
        aurora_security_group.add_ingress_rule(aws_ec2.Peer.ipv4("0.0.0.0/0"), 
                                               aws_ec2.Port.tcp(5432), "Allow access to the PostgreSQL")
        aurora_security_group.add_ingress_rule(aws_ec2.Peer.ipv4("0.0.0.0/0"),  
                                               aws_ec2.Port.tcp(3306), "Allow access to the MySQL")
        
        # Define Serverless Aurora for MLflow backend
        mlflow_database_name = "MLflowBackend"
        mlflow_backend_db = aws_rds.ServerlessCluster(self, "MLflowBackendDB",
                                                      engine=aws_rds.DatabaseClusterEngine.aurora_postgres(version=
                                                                                                           aws_rds.AuroraPostgresEngineVersion.VER_10_14),
                                                      credentials=aws_rds.Credentials.from_secret(mlflow_db_secret),
                                                      vpc=self.vpc,
                                                      vpc_subnets=subnet_selection,
                                                      security_groups=[aurora_security_group],
                                                      default_database_name=mlflow_database_name,
                                                      cluster_identifier="mlops-mlflow")
        # Define the MLflow DB endpoint
        mlflow_db_endpoint = mlflow_backend_db.cluster_endpoint
        
        #===========================================================================================================================
        #=========================================================FARGATE===========================================================
        #===========================================================================================================================
        
        # Define the Fargate Cluster
        fargate_cluster = aws_ecs.Cluster(self, "FargateCluster", cluster_name="mlops-fargate-cluster",
                                          enable_fargate_capacity_providers=True, vpc=self.vpc, container_insights=True)
        
        # Define Fargate Policy
        fargate_policy = aws_iam.ManagedPolicy(self, "FargatePolicy", description="Used for Fargate Cluster",
                                               managed_policy_name="mlops-fargate-policy",
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
                                                            "*"
                                                        ]
                                                    ),
                                                    aws_iam.PolicyStatement(
                                                        sid="SecretsManagerAccess",
                                                        effect=aws_iam.Effect.ALLOW,
                                                        actions=[
                                                            "secretsmanager:*"
                                                        ],
                                                        resources=[
                                                            "*"
                                                        ]
                                                    ),
                                                    aws_iam.PolicyStatement(
                                                        sid="ECSAccess",
                                                        effect=aws_iam.Effect.ALLOW,
                                                        actions=[
                                                            "ecs:*"
                                                        ],
                                                        resources=[
                                                            "*"
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
                                                        sid="S3ArtifactsAccess",
                                                        effect=aws_iam.Effect.ALLOW,
                                                        actions=[
                                                            "s3:*"
                                                        ],
                                                        resources=[
                                                            artifacts_bucket.bucket_arn,
                                                            artifacts_bucket.bucket_arn + "/*"
                                                        ]
                                                    ),
                                                    aws_iam.PolicyStatement(
                                                        sid="CloudWatchAccessForGrafana",
                                                        effect=aws_iam.Effect.ALLOW,
                                                        actions=[
                                                            "cloudwatch:DescribeAlarmsForMetric",
                                                            "cloudwatch:DescribeAlarmHistory",
                                                            "cloudwatch:DescribeAlarms",
                                                            "cloudwatch:ListMetrics",
                                                            "cloudwatch:GetMetricStatistics",
                                                            "cloudwatch:GetMetricData",
                                                            "cloudwatch:GetInsightRuleReport",
                                                            "logs:DescribeLogGroups",
                                                            "logs:GetLogGroupFields",
                                                            "logs:StartQuery",
                                                            "logs:StopQuery",
                                                            "logs:GetQueryResults",
                                                            "logs:GetLogEvents",
                                                            "ec2:DescribeTags",
                                                            "ec2:DescribeInstances",
                                                            "ec2:DescribeRegions",
                                                            "tag:GetResources"
                                                        ],
                                                        resources=[
                                                            "*"
                                                        ]
                                                    ),
                                                    aws_iam.PolicyStatement(
                                                        sid="AthenaQueryAccess",
                                                        effect=aws_iam.Effect.ALLOW,
                                                        actions=[
                                                            "athena:ListDatabases",
                                                            "athena:ListDataCatalogs",
                                                            "athena:ListWorkGroups",
                                                            "athena:GetDatabase",
                                                            "athena:GetDataCatalog",
                                                            "athena:GetQueryExecution",
                                                            "athena:GetQueryResults",
                                                            "athena:GetTableMetadata",
                                                            "athena:GetWorkGroup",
                                                            "athena:ListTableMetadata",
                                                            "athena:StartQueryExecution",
                                                            "athena:StopQueryExecution"
                                                        ],
                                                        resources=[
                                                            "*"
                                                        ]
                                                    ),
                                                    aws_iam.PolicyStatement(
                                                        sid="GlueReadAccess",
                                                        effect=aws_iam.Effect.ALLOW,
                                                        actions=[
                                                            "glue:GetDatabase",
                                                            "glue:GetDatabases",
                                                            "glue:GetTable",
                                                            "glue:GetTables",
                                                            "glue:GetPartition",
                                                            "glue:GetPartitions",
                                                            "glue:BatchGetPartition"
                                                        ],
                                                        resources=[
                                                            "*"
                                                        ]
                                                    ),
                                                    aws_iam.PolicyStatement(
                                                        sid="AthenaS3Access",
                                                        effect=aws_iam.Effect.ALLOW,
                                                        actions=[
                                                            "s3:GetBucketLocation",
                                                            "s3:GetObject",
                                                            "s3:ListBucket",
                                                            "s3:ListBucketMultipartUploads",
                                                            "s3:ListMultipartUploadParts",
                                                            "s3:AbortMultipartUpload",
                                                            "s3:PutObject"
                                                        ],
                                                        resources=[
                                                            "arn:aws:s3:::mlops-storage-bucket",
                                                            "arn:aws:s3:::mlops-storage-bucket/*"
                                                        ]
                                                    ),
                                               ]
                                            )
        
        # Define Fargate Role
        fargate_role = aws_iam.Role(self, "FargateRole", role_name="mlops-fargate-role",
                                    assumed_by=aws_iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
                                    managed_policies=[fargate_policy])
        
        # Define Security Group for Fargate Cluster
        fargate_security_group = aws_ec2.SecurityGroup(self, "FargateSecurityGroup", vpc=self.vpc,
                                                       description="Security Group used for connecting to MLflow and Grafana servers",
                                                       allow_all_outbound=True, security_group_name="mlops-fargate-security-group")
        fargate_security_group.add_ingress_rule(aws_ec2.Peer.ipv4("0.0.0.0/0"), aws_ec2.Port.tcp(5000),
                                                "Allow access from VPC for the MLflow")
        fargate_security_group.add_ingress_rule(aws_ec2.Peer.ipv4("0.0.0.0/0"), aws_ec2.Port.tcp(3000),
                                                "Allow access from VPC for the Grafana")
        fargate_security_group.add_ingress_rule(aws_ec2.Peer.ipv4("0.0.0.0/0"), aws_ec2.Port.tcp(80),
                                                "Allow access to the Load Balancer")
        
        #===========================================================================================================================
        #=========================================================MLFLOW============================================================
        #===========================================================================================================================
        
        # Define Mlflow Task Definition
        mlflow_task_definition = aws_ecs.FargateTaskDefinition(self, "MLflowTaskDefinition", cpu=1024, ephemeral_storage_gib=30,
                                                               memory_limit_mib=4096, execution_role=fargate_role,
                                                               family="mlops-mlflow-task", task_role=fargate_role)
        
        # Define the MLflow Task Container 
        mlflow_task_definition.add_container("MLflowImageContainer",
                                             image=aws_ecs.ContainerImage.from_asset(directory="mlflow"),
                                             container_name="mlflow-task-container", privileged=False,
                                             port_mappings=[aws_ecs.PortMapping(container_port=5000, protocol=aws_ecs.Protocol.TCP)],
                                             logging=aws_ecs.LogDriver.aws_logs(stream_prefix="mlflow-task"),
                                             secrets={
                                                 "DB_USERNAME": aws_ecs.Secret.from_secrets_manager(mlflow_db_secret, "username"),
                                                 "DB_PASSWORD": aws_ecs.Secret.from_secrets_manager(mlflow_db_secret, "password")
                                             },
                                             environment={
                                                 "HOST": mlflow_db_endpoint.hostname,
                                                 "PORT": "5432",
                                                 "DATABASE": mlflow_database_name,
                                                 "BUCKET": artifacts_bucket.bucket_name
                                             })
        
        # Define the Load Balanced Service for MLflow
        mlflow_load_balanced_service = aws_ecs_patterns.ApplicationLoadBalancedFargateService(
            self, "MLflowLoadBalancedService", assign_public_ip=False, cpu=1024, 
            memory_limit_mib=4096, security_groups=[fargate_security_group],
            task_definition=mlflow_task_definition, cluster=fargate_cluster,
            task_subnets=subnet_selection,
            desired_count=1, listener_port=80, 
            load_balancer_name="mlops-mlflow-load-balancer",
            open_listener=False, public_load_balancer=True, 
            service_name="mlops-mlflow-service",
            health_check_grace_period=Duration.minutes(3)
        )
        # Attach Fargate Security Group to the MLflow Load Balancer
        mlflow_load_balanced_service.load_balancer.add_security_group(fargate_security_group)
        
        #===========================================================================================================================
        #=========================================================CI/CD============================================================
        #===========================================================================================================================
        
        # Define the ECR Repository to contain all project images
        ecr_repository = aws_ecr.Repository(self, "ECRRepository",
                                            repository_name="mlops_image_repository",
                                            removal_policy=RemovalPolicy.DESTROY)
        
        # Import the CodeCommit repo
        code_repository = aws_codecommit.Repository.from_repository_arn(self, "CodeRepository", 
                                                                        repository_arn=parameters['CodeCommitRepoARN'])
        
        # Define CodeBuild policy
        codebuild_policy = aws_iam.ManagedPolicy(self, "CodeBuildPolicy", description="Used for Codebuild to create and push images to ECR",
                                               managed_policy_name="mlops-codebuild-policy",
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
                                                            f"arn:aws:logs:{self.acc_region}:{self.account_id}:log-group:/aws/codebuild/*"
                                                        ]
                                                    ),
                                                    aws_iam.PolicyStatement(
                                                        sid="ECRReadAccess",
                                                        effect=aws_iam.Effect.ALLOW,
                                                        actions=[
                                                            "ecr:BatchCheckLayerAvailability",
                                                            "ecr:CompleteLayerUpload",
                                                            "ecr:GetAuthorizationToken",
                                                            "ecr:InitiateLayerUpload",
                                                            "ecr:PutImage",
                                                            "ecr:UploadLayerPart",
                                                        ],
                                                        resources=[
                                                            "*"
                                                        ]
                                                    ),
                                               ]
                                            )
        
        # Define CodeBuild Role
        codebuild_role = aws_iam.Role(self, "CodeBuildRole", role_name="mlops-codebuild-role",
                                    assumed_by=aws_iam.ServicePrincipal("codebuild.amazonaws.com"),
                                    managed_policies=[codebuild_policy])
        
        # Define the CodeBuild Project for GitHub Repository
        codebuild_project = aws_codebuild.Project(self, "CodeBuildProject",
                                role=codebuild_role, vpc=self.vpc, security_groups=[self.outbound_security_group],
                                subnet_selection=subnet_selection, project_name=f"mlops_codebuild_project",
                                environment=aws_codebuild.BuildEnvironment(
                                    privileged=True,
                                    build_image=aws_codebuild.LinuxBuildImage.from_code_build_image_id("aws/codebuild/amazonlinux2-x86_64-standard:3.0")
                                ),
                                environment_variables={
                                    "AWS_DEFAULT_REGION": aws_codebuild.BuildEnvironmentVariable(value=self.acc_region),
                                    "AWS_ACCOUNT_ID": aws_codebuild.BuildEnvironmentVariable(value=self.account_id),
                                    "IMAGE_REPO_NAME": aws_codebuild.BuildEnvironmentVariable(value=ecr_repository.repository_name),
                                },
                                logging=aws_codebuild.LoggingOptions(cloud_watch=aws_codebuild.CloudWatchLoggingOptions(
                                    log_group=aws_logs.LogGroup(self, "CodeBuildLogGroup",
                                                                log_group_name=f"/aws/codebuild/mlops",
                                                                removal_policy=RemovalPolicy.DESTROY,
                                                                retention=aws_logs.RetentionDays.ONE_WEEK)
                                )), description=f"CodeBuild used to create and push ML images",
                                source=aws_codebuild.Source.code_commit(repository=code_repository, 
                                                                        identifier="mlops_source"))
        
        code_repository.on_commit("CommitToMaster", branches=['master'], 
                                  target=aws_events_targets.CodeBuildProject(codebuild_project))
        
        #===========================================================================================================================
        #=========================================================SAGEMAKER=========================================================
        #===========================================================================================================================
        
        # Define Sagemaker policy
        sagemaker_policy = aws_iam.ManagedPolicy(self, "SagemakerPolicy", description="Used for Sagemaker Processing Job",
                                               managed_policy_name="mlops-sagemaker-policy",
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
                                                            "*"
                                                        ]
                                                    ),
                                                    aws_iam.PolicyStatement(
                                                        sid="FullS3BucketAccess",
                                                        effect=aws_iam.Effect.ALLOW,
                                                        actions=[
                                                            "s3:*"
                                                        ],
                                                        resources=[
                                                            "*"
                                                        ]
                                                    ),
                                                    aws_iam.PolicyStatement(
                                                        sid="GlueTablesAccess",
                                                        effect=aws_iam.Effect.ALLOW,
                                                        actions=[
                                                            "glue:GetSchemaByDefinition",
                                                            "glue:CreateSchema",
                                                            "glue:RegisterSchemaVersion",
                                                            "glue:PutSchemaVersionMetadata",
                                                            "glue:GetSchemaVersion",
                                                            "glue:GetDatabase",
                                                            "glue:GetDatabases",
                                                            "glue:*Table*",
                                                            "glue:*Partition*",
                                                        ],
                                                        resources=[
                                                            "*" 
                                                        ]
                                                    ),
                                               ]
                                            )
        
        # Define the Sagemaker Role
        sagemaker_role = aws_iam.Role(self, "SagemakerRole", role_name="mlops-sagemaker-role",
                                    assumed_by=aws_iam.ServicePrincipal("sagemaker.amazonaws.com"),
                                    managed_policies=[aws_iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSageMakerFullAccess"),
                                                      sagemaker_policy])
        
        #===========================================================================================================================
        #=========================================================LAMBDA============================================================
        #===========================================================================================================================
        
        # Define the EventBridge Role
        events_role = aws_iam.Role(self, "EventsRole", role_name="mlops-events-role",
                                   assumed_by=aws_iam.ServicePrincipal('events.amazonaws.com'),
                                   managed_policies=[aws_iam.ManagedPolicy.from_aws_managed_policy_name("AmazonEventBridgeFullAccess")])
        
        # Define the Lambda Policy
        lambda_policy = aws_iam.ManagedPolicy(self, "LambdaPolicy", description="Used for Training Lambda permissions",
                                               managed_policy_name="mlops-training-lambda-policy",
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
                                                            "ecr:*",
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
                                                        sid="S3Access",
                                                        effect=aws_iam.Effect.ALLOW,
                                                        actions=[
                                                            "s3:*"
                                                        ],
                                                        resources=[
                                                            artifacts_bucket.bucket_arn,
                                                            artifacts_bucket.bucket_arn + '/*'
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
        lambda_role = aws_iam.Role(self, "LambdaRole", role_name="mlops-training-lambda-role",
                                    assumed_by=aws_iam.ServicePrincipal("lambda.amazonaws.com"),
                                    managed_policies=[lambda_policy])
        
        # Define Lambda function
        training_lambda_name = "mlops-training-lambda"
        training_lambda = aws_lambda.Function(self, "TrainingLambda", role=lambda_role,
                                              runtime=aws_lambda.Runtime.PYTHON_3_8,
                                              handler="training_lambda.lambda_handler",
                                              vpc=self.vpc, vpc_subnets=aws_ec2.SubnetType.PRIVATE_WITH_NAT,
                                              security_groups=[self.outbound_security_group],
                                              code=aws_lambda.Code.from_asset("lambda_code/training_lambda"),
                                              environment={
                                                        "SagemakerRoleArn": sagemaker_role.role_arn,
                                                        "EventRole": events_role.role_arn,
                                                        "ImageUri": ecr_repository.repository_uri,
                                                        "ECRRepositoryName": ecr_repository.repository_name,
                                                        "SecurityGroupId": self.outbound_security_group.security_group_id,
                                                        "Subnet0": subnets_ids[0],
                                                        "Subnet1": subnets_ids[1],
                                                        "Region": self.acc_region,
                                                        "AccountId": self.account_id,
                                                        "ArtifactsBucket": artifacts_bucket.bucket_name,
                                                        "SelfLambdaName": training_lambda_name,
                                                        "Owner": self.owner,
                                                        "Project": self.project
                                                  },
                                              timeout=Duration.minutes(5), 
                                              function_name=training_lambda_name,
                                              description="Used for starting the model training, invoked through API or Event Rule")
        
        # Add invocation permission for EventBridge
        events_principal = aws_iam.ServicePrincipal("events.amazonaws.com")
        training_lambda.grant_invoke(events_principal)
        
        #===========================================================================================================================
        #=========================================================APIGATEWAY========================================================
        #===========================================================================================================================
        
        # Define API Gateway Policy
        api_policy = aws_iam.PolicyDocument(
                statements=[
                    aws_iam.PolicyStatement(
                            sid="InvokeLambda",
                            effect=aws_iam.Effect.ALLOW,
                            actions=[
                                "lambda:InvokeFunction",
                            ],
                            resources=[
                                training_lambda.function_arn
                            ],
                            principals=[aws_iam.AnyPrincipal()]
                    ),
                    aws_iam.PolicyStatement(
                            sid="AllowFromVPCLocations",
                            effect=aws_iam.Effect.ALLOW,
                            actions=[
                                "execute-api:Invoke",
                            ],
                            resources=[
                                "execute-api:/*"
                            ],
                            principals=[aws_iam.AnyPrincipal()]
                    )
                    # aws_iam.PolicyStatement(
                    #         sid="DenyFromNonVPCLocations",
                    #         effect=aws_iam.Effect.DENY,
                    #         actions=[
                    #             "execute-api:Invoke",
                    #         ],
                    #         resources=[
                    #             "execute-api:/*"
                    #         ],
                    #         principals=[aws_iam.AnyPrincipal()],
                    #         conditions={
                    #             "StringNotEquals": {
                    #                 "aws:sourceVpc": self.vpc.vpc_id
                    #             }
                    #         }
                    # ),
                ])
        
        # Define API Gateway with VPC Endpoint
        # api = aws_apigateway.RestApi(self, "MLOpsAPI", rest_api_name="mlops-api-gateway",
        #                                          description="API used to start training, inference and define training/inference schedule",
        #                                          policy=api_policy, deploy=True,
        #                                          deploy_options=aws_apigateway.StageOptions(stage_name="v1"),
        #                                          endpoint_configuration=aws_apigateway.EndpointConfiguration(
        #                                              types=[aws_apigateway.EndpointType.EDGE],
        #                                              vpc_endpoints=[vpc_endpoint]
        #                                          ))
        
        api = aws_apigateway.RestApi(self, "MLOpsAPIGateway", rest_api_name="mlops-api",
                                                 description="API used to start training, inference and define training/inference schedule",
                                                 policy=api_policy, deploy=True,
                                                 deploy_options=aws_apigateway.StageOptions(stage_name="v1"))
        
        # Define Integration Lambda with API Gateway
        training_integration = aws_apigateway.LambdaIntegration(training_lambda)
        
        # Define the API Resources and methods
        train_resource = api.root.add_resource("start_training")
        train_resource.add_method("POST", training_integration)
        
        schedule_resource = api.root.add_resource("training_schedule")
        schedule_resource.add_method("POST", training_integration)
        
        #===========================================================================================================================
        #=========================================================STACK EXPORTS=====================================================
        #===========================================================================================================================
        
        CfnOutput(self, "SecuritGroupExport", description="ID of the Security Group",
                  value=self.outbound_security_group.security_group_id,
                  export_name="SecurityGroupId")
        
        CfnOutput(self, "AuroraSecurityGroupExport", description="ID of the Aurora Security Group",
                  value=aurora_security_group.security_group_id,
                  export_name="AuroraSecurityGroupId")
        
        # CfnOutput(self, "KMSKeyARN", description="ARN of the KMS Key",
        #           value=kms_key.key_arn,
        #           export_name="KMSKeyARN")
        
        CfnOutput(self, "SecretARNExport", description="ARN of the Secret",
                  value=mlflow_db_secret.secret_full_arn,
                  export_name="SecretARN")
        
        CfnOutput(self, "FargateClusterARN", description="ARN of the Fargate Cluster",
                  value=fargate_cluster.cluster_arn,
                  export_name="FargateClusterARN")
        
        CfnOutput(self, "FargateClusterName", description="Name of the Fargate Cluster",
                  value=fargate_cluster.cluster_name,
                  export_name="FargateClusterName")
        
        CfnOutput(self, "FargateSecurityGroupExport", description="ID of the Fargate Security Group",
                  value=fargate_security_group.security_group_id,
                  export_name="FargateSecurityGroupId")
        
        CfnOutput(self, "FargateRoleARNExport", description="ARN of the Fargate Role",
                  value=fargate_role.role_arn,
                  export_name="FargateRoleARN")
        
        CfnOutput(self, "ECRRepositoryArn", description="Arn of the ECR Repository",
                  value=ecr_repository.repository_arn,
                  export_name="ECRRepositoryArn")
        
        CfnOutput(self, "ECRRepositoryNameExport", description="Name of the ECR Repository",
                  value=ecr_repository.repository_name,
                  export_name="ECRRepositoryName")
        
        CfnOutput(self, "SagemakerRoleArn", description="Arn of the Sagemaker Role",
                  value=sagemaker_role.role_arn,
                  export_name="SagemakerRoleArn")
        
        CfnOutput(self, "APIid", description="ID of the REST API",
                  value=api.rest_api_id,
                  export_name="APIid")
        
        CfnOutput(self, "APIRoot", description="Root Resource of the REST API",
                  value=api.rest_api_root_resource_id,
                  export_name="APIRoot")
        
        CfnOutput(self, "ArtifactsBucketExport", description="Name of the Artifacts Bucket",
                  value=artifacts_bucket.bucket_name,
                  export_name="ArtifactsBucketName")
        
        CfnOutput(self, "EventRoleArn", description="ARN of the Event Role",
                  value=events_role.role_arn,
                  export_name="EventRoleArn")
        