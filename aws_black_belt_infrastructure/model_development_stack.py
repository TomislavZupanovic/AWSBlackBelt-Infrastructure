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
    aws_route53,
    aws_codebuild, aws_apigateway,
    RemovalPolicy, Duration,
    Tags, Stack
)
from constructs import Construct
import constructs

class ModelDevelopment(Stack):
    def __init__(self, scope: Construct, construct_id: str, parameters: dict, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Get Account environment parameters
        self.account_id = parameters["AccountId"]
        self.region = parameters["Region"]
        self.vpc = None
        self.outbound_security_group = None
        self.vpc_endpoint_id = parameters["VPCEndpointId"]
        self.vpc_security_group_id = parameters["VPCSecurityGroupId"]
        
        # Define Tags for all resources (where they apply)
        Tags.of(self).add("Project", "BlackBelt")
        Tags.of(self).add("Owner", "Tomislav Zupanovic")
        
        #===========================================================================================================================
        #=========================================================VPC===============================================================
        #===========================================================================================================================

        # Import VPC and subnets
        self.vpc = aws_ec2.Vpc.from_lookup(self, "MainVPC", vpc_name="aast-innovation-vpc")
        subnets = self.vpc.private_subnets
        subnets_ids = [subnet.subnet_id for subnet in subnets]
        
        # Define Security Group with allowed outbound traffic
        self.outbound_security_group = aws_ec2.SecurityGroup(self, "OutboundSecurityGroup",
                                                        vpc=self.vpc, description="Allow all outbound access only",
                                                        allow_all_outbound=True)
        
        # Import VPC Endpoint Security Group
        vpc_endpoint_security_group = aws_ec2.SecurityGroup.from_security_group_id(
            self, "VPCEndpointSecurityGroupImport", security_group_id=self.vpc_security_group_id
        )
        
        # Import VPC Endpoint for API Gateway
        vpc_endpoint = aws_ec2.InterfaceVpcEndpoint.from_interface_vpc_endpoint_attributes(
            self, "VPCEndpointImport", port=443, vpc_endpoint_id=self.vpc_endpoint_id,
            security_groups=[vpc_endpoint_security_group]
        )

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
        mlflow_key = aws_kms.Key(self, "MLflowDBSecretKey", description="Key used for MLflow DB Secret",
                                 enabled=True, enable_key_rotation=False,
                                 policy=aws_iam.PolicyDocument(
                                            statements=[aws_iam.PolicyStatement(
                                                actions=["kms:Create*", 
                                                         "kms:Describe*", 
                                                         "kms:Enable*", 
                                                         "kms:List*", 
                                                         "kms:Put*"
                                                ],
                                                principals=[aws_iam.AccountRootPrincipal()],
                                                resources=["*"]
                                            )]), removal_policy=RemovalPolicy.DESTROY)
        
        # Define the Secret for MLflow Aurora DB
        mlflow_db_secret = aws_secretsmanager.Secret(self, "MLflowDBSecret", encryption_key=mlflow_key,
                                                     description="Secret used for connecting to the MLflow PostgreSQL database",
                                                     secret_name="mlops-mlflow-db-secret",
                                                     removal_policy=RemovalPolicy.DESTROY,
                                                     generate_secret_string=aws_secretsmanager.SecretStringGenerator(
                                                         generate_string_key="password",
                                                         secret_string_template="{\"username\":\"mlflow-user\"}"
                                                     ))
        
        #===========================================================================================================================
        #=========================================================AURORA============================================================
        #===========================================================================================================================
        
        # Define Security group for serverless Aurora
        aurora_security_group = aws_ec2.SecurityGroup(self, "AuroraSecurityGroup",
                                                      vpc=self.vpc, description="Security group used for connecting to MLflow Database backend",
                                                      allow_all_outbound=True)
        
        aurora_security_group.add_ingress_rule(aws_ec2.Peer.ipv4("0.0.0.0/0"),  # TODO: Restrict IP range
                                               aws_ec2.Port.tcp(5432), "Allow access from VPC")
        
        # Define Serverless Aurora for MLflow backend
        mlflow_database_name = "MLflowBackend"
        mlflow_backend_db = aws_rds.ServerlessCluster(self, "MLflowBackendDB",
                                                      engine=aws_rds.DatabaseClusterEngine.aurora_postgres(
                                                          version=aws_rds.AuroraPostgresEngineVersion.VER_10_4),
                                                      credentials=aws_rds.Credentials.from_secret(mlflow_db_secret),
                                                      vpc=self.vpc,
                                                      vpc_subnets=aws_ec2.SubnetSelection(
                                                          one_per_az=True,
                                                          subnet_type=aws_ec2.SubnetType.PRIVATE_WITH_NAT  # TODO: Double-check
                                                      ),
                                                      security_groups=[aurora_security_group],
                                                      default_database_name=mlflow_database_name,
                                                      cluster_identifier="mlops-mlflow-backend")
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
                                                            mlflow_db_secret.secret_arn
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
                                               ]
                                            )
        
        # Define Fargate Role
        fargate_role = aws_iam.Role(self, "FargateRole", role_name="mlops-fargate-role",
                                    assumed_by=aws_iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
                                    managed_policies=[fargate_policy])
        
        # Define Security Group for Fargate Cluster
        fargate_security_group = aws_ec2.SecurityGroup(self, "FargateSecurityGroup", vpc=self.vpc,
                                                       description="Security Group used for connecting to MLflow and Grafana servers",
                                                       allow_all_outbound=True)
        fargate_security_group.add_ingress_rule(aws_ec2.Peer.ipv4("0.0.0.0/0"), aws_ec2.Port.tcp(5000),
                                                "Allow access from VPC for the MLflow")
        fargate_security_group.add_ingress_rule(aws_ec2.Peer.ipv4("0.0.0.0/0"), aws_ec2.Port.tcp(3000),
                                                "Allow access from VPC for the Grafana")
        fargate_security_group.add_ingress_rule(aws_ec2.Peer.ipv4("0.0.0.0/0"), aws_ec2.Port.tcp(80),
                                                "Allow access to the Load Balancer")
        
        #===========================================================================================================================
        #=========================================================MLFLOW============================================================
        #===========================================================================================================================
        
        # Define Route53 Hosted Zone
        hosted_zone = aws_route53.HostedZone(self, "Route53HostedZone",
                                             vpcs=[self.vpc], zone_name="aast-innovation.iolap.com")
        
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
            task_subnets=aws_ec2.SubnetSelection(
                one_per_az=True,
                subnet_type=aws_ec2.SubnetType.PRIVATE_WITH_NAT  # TODO: Double-check
            ),
            desired_count=1, listener_port=80, domain_zone=hosted_zone,
            domain_name="mlflow", load_balancer_name="mlops-mlflow-load-balancer",
            open_listener=False, public_load_balancer=False, 
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
                                            repository_name="mlops-image-repository",
                                            removal_policy=RemovalPolicy.DESTROY)
        
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
                                                            f"arn:aws:logs:{self.region}:{self.account_id}:log-group:/aws/codebuild/*"
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
                                                            "ecr:UploadLayerPart"
                                                        ],
                                                        resources=[
                                                            ecr_repository.repository_arn
                                                        ]
                                                    ),
                                               ]
                                            )
        
        # Define CodeBuild Role
        codebuild_role = aws_iam.Role(self, "CodeBuildRole", role_name="mlops-codebuild-role",
                                    assumed_by=aws_iam.ServicePrincipal("codebuild.amazonaws.com"),
                                    managed_policies=[codebuild_policy])
        
        # Define Subnet Selection for CodeBuild
        subnet_selection = aws_ec2.SubnetSelection(one_per_az=True,
                                                   subnet_type=aws_ec2.SubnetType.PRIVATE_WITH_NAT)
        
        # Define the CodeBuild Project for GitHub Repository
        codebuild_project = aws_codebuild.Project(self, "CodeBuildProject", allow_all_outbound=True,
                                role=codebuild_role, vpc=self.vpc, security_groups=[self.outbound_security_group],
                                subnet_selection=subnet_selection, project_name=f"mlops-codebuild-project",
                                environment=aws_codebuild.BuildEnvironment(
                                    privileged=True,
                                    build_image=aws_codebuild.LinuxBuildImage.from_code_build_image_id("aws/codebuild/amazonlinux2-x86_64-standard:3.0")
                                ),
                                environment_variables={
                                    "AWS_DEFAULT_REGION": aws_codebuild.BuildEnvironmentVariable(value=self.region),
                                    "AWS_ACCOUNT_ID": aws_codebuild.BuildEnvironmentVariable(value=self.account_id),
                                    "IMAGE_REPO_NAME": aws_codebuild.BuildEnvironmentVariable(value=ecr_repository.repository_name),
                                },
                                logging=aws_codebuild.LoggingOptions(cloud_watch=aws_codebuild.CloudWatchLoggingOptions(
                                    log_group=aws_logs.LogGroup(self, "CodeBuildLogGroup",
                                                                log_group_name=f"/aws/codebuild/mlops",
                                                                removal_policy=RemovalPolicy.DESTROY,
                                                                retention=aws_logs.RetentionDays.ONE_WEEK)
                                )), description=f"CodeBuild used to create and push ML images",
                                source=aws_codebuild.Source.git_hub(owner="TomislavZupanovic", repo="AWSBlackBelt-Capstone",
                                                                    branch_or_ref="main", webhook=True,
                                                                    identifier=f"codebuild-github-source"))
        
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
                                                        sid="S3BucketAccess",
                                                        effect=aws_iam.Effect.ALLOW,
                                                        actions=[
                                                            "s3:*"
                                                        ],
                                                        resources=[
                                                            artifacts_bucket.bucket_arn,
                                                            artifacts_bucket.bucket_arn + "/*"
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
        
        # Define the Lambda Policy
        lambda_policy = aws_iam.ManagedPolicy(self, "LambdaPolicy", description="Used for Lambdas permissions",
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
                                                            f"arn:aws:logs:{self.region}:{self.account_id}:log-group:/aws/lambda/*"
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
                                               ]
                                            )
        
        # Define Lambda Role
        lambda_role = aws_iam.Role(self, "LambdaRole", role_name="mlops-lambda-role",
                                    assumed_by=aws_iam.ServicePrincipal("lambda.amazonaws.com"),
                                    managed_policies=[lambda_policy])
        
        # Define Lambda function
        training_lambda = aws_lambda.Function(self, "TrainingLambda", role=lambda_role,
                                              runtime=aws_lambda.Runtime.PYTHON_3_8,
                                              handler="training_lambda.lambda_handler",
                                              vpc=self.vpc, vpc_subnets=aws_ec2.SubnetType.PRIVATE_WITH_NAT,
                                              security_groups=[self.outbound_security_group],
                                              code=aws_lambda.Code.from_asset("lambda_code/training_lambda"),
                                              environment={
                                                        "SagemakerRoleArn": sagemaker_role.role_arn,
                                                        "ImageUri": ecr_repository.repository_uri,
                                                        "SecurityGroupId": self.outbound_security_group.security_group_id,
                                                        "Subnet0": subnets_ids[0],
                                                        "Subnet1": subnets_ids[1],
                                                        "Subnet2": subnets_ids[2],
                                                        "Subnet3": subnets_ids[3],
                                                  },
                                              timeout=Duration.minutes(5), 
                                              function_name="mlops-training-lambda",
                                              description="Used for starting the model training, invoked through API or Event Rule")
        
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
                    ),
                    aws_iam.PolicyStatement(
                            sid="DenyFromNonVPCLocations",
                            effect=aws_iam.Effect.DENY,
                            actions=[
                                "execute-api:Invoke",
                            ],
                            resources=[
                                "execute-api:/*"
                            ],
                            principals=[aws_iam.AnyPrincipal()],
                            conditions={
                                "StringNotEquals": {
                                    "aws:sourceVpc": self.vpc.vpc_id
                                }
                            }
                    ),
                ])
        
        # Define API Gateway with VPC Endpoint
        development_api = aws_apigateway.RestApi(self, "DevelopmentAPI", rest_api_name="mlops-development-api",
                                                 description="API used to start training and define training schedule",
                                                 policy=api_policy, deploy=True,
                                                 deploy_options=aws_apigateway.StageOptions(stage_name="prod"),
                                                 endpoint_configuration=aws_apigateway.EndpointConfiguration(
                                                     types=[aws_apigateway.EndpointType.PRIVATE],
                                                     vpc_endpoint=[vpc_endpoint]
                                                 ))
        
        # Define Integration Lambda with API Gateway
        training_integration = aws_apigateway.LambdaIntegration(training_lambda)
        
        # Define the API Resources and methods
        train_resource = development_api.root.add_resource("start_training")
        train_resource.add_method("PUT", training_integration)
        
        schedule_resource = development_api.root.add_resource("training_schedule")
        schedule_resource.add_method("PUT", training_integration)