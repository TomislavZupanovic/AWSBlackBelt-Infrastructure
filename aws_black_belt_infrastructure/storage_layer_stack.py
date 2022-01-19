from aws_cdk import (
    aws_ecs,
    aws_kms,
    aws_s3,
    aws_logs,
    aws_glue_alpha as aws_glue,
    aws_iam, aws_secretsmanager,
    aws_ec2, aws_rds, aws_route53,
    aws_lambda, aws_s3_notifications,
    aws_stepfunctions_tasks, aws_stepfunctions,
    aws_ecs_patterns,
    RemovalPolicy,
    Tags, Stack, Duration, CfnOutput, Fn
)
from constructs import Construct

class StorageLayer(Stack):

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
        #=========================================================S3================================================================
        #===========================================================================================================================

        # Define the Storage Bucket
        storage_bucket = aws_s3.Bucket(self, "StorageBucket", bucket_name="mlops-storage-bucket",
                                       block_public_access=aws_s3.BlockPublicAccess.BLOCK_ALL,
                                       public_read_access=False, removal_policy=RemovalPolicy.DESTROY,
                                       versioned=False, encryption=aws_s3.BucketEncryption.S3_MANAGED)
        
        #===========================================================================================================================
        #=========================================================GLUE==============================================================
        #===========================================================================================================================
        
        # Define Glue Database
        glue_database = aws_glue.Database(self, "GlueDatabase", database_name="mlops-glue-database")
        
        # Define the Policy for Glue Jobs
        glue_job_policy = aws_iam.ManagedPolicy(self, "GlueJobPolicy",
                                                description="Policy used for Glue Jobs",
                                                managed_policy_name="mlops-glue-job-policy",
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
                                                            f"arn:aws:logs:{self.acc_region}:{self.account_id}:log-group:/aws-glue/mlops-jobs/*"
                                                        ]
                                                    ),
                                                    aws_iam.PolicyStatement(
                                                        sid="S3BucketAccess",
                                                        effect=aws_iam.Effect.ALLOW,
                                                        actions=[
                                                            "s3:*"
                                                        ],
                                                        resources=[
                                                            storage_bucket.bucket_arn,
                                                            storage_bucket.bucket_arn + "/*"
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
                                                            glue_database.catalog_arn,
                                                            glue_database.database_arn # TODO: Add tables arn
                                                            
                                                        ]
                                                    ),
                                                ])
        
        # Define the Role for Glue Jobs
        glue_job_role = aws_iam.Role(self, "GlueJobRole", role_name="mlops-glue-job-role",
                                     assumed_by=aws_iam.ServicePrincipal("glue.amazonaws.com"),
                                     managed_policies=[
                                         aws_iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSGlueServiceRole"),
                                         glue_job_policy
                                         ])
        
        # Define the Glue Job for converting .csv to .parquet
        convert_job = aws_glue.Job(self, "ConvertGlueJob", 
                                   executable=aws_glue.JobExecutable.python_etl(
                                       glue_version=aws_glue.GlueVersion.V3_0,
                                       python_version=aws_glue.PythonVersion.THREE,
                                       script=aws_glue.Code.from_asset(path="glue_code/convert_job.py")
                                   ),
                                   default_arguments={"--additional-python-modules": "awswrangler"},
                                   description="Job used to convert data format from CSV to the Parquet",
                                   continuous_logging=aws_glue.ContinuousLoggingProps(enabled=True,
                                                                                      log_group=aws_logs.LogGroup(self, 
                                                                                        'ConvertJobLogGroup', 
                                                                                        log_group_name="/aws-glue/mlops-jobs/convert-job/")),
                                   job_name="mlops-convert-job",
                                   worker_type=aws_glue.WorkerType.STANDARD,
                                   worker_count=1,
                                   role=glue_job_role,
                                   tags={
                                       "Project": self.project,
                                       "Owner": self.owner
                                   })
        
        # Define the Glue Job for transforming data
        transform_job = aws_glue.Job(self, "TransformGlueJob", 
                                   executable=aws_glue.JobExecutable.python_etl(
                                       glue_version=aws_glue.GlueVersion.V3_0,
                                       python_version=aws_glue.PythonVersion.THREE,
                                       script=aws_glue.Code.from_asset(path="glue_code/transform_job.py")
                                   ),
                                   default_arguments={"--additional-python-modules": "awswrangler"},
                                   description="Job used to transform raw data into curated data",
                                   continuous_logging=aws_glue.ContinuousLoggingProps(enabled=True,
                                                                                      log_group=aws_logs.LogGroup(self, 
                                                                                        'TransformJobLogGroup', 
                                                                                        log_group_name="/aws-glue/mlops-jobs/transform-job/")),
                                   job_name="mlops-transform-job",
                                   worker_type=aws_glue.WorkerType.STANDARD,
                                   worker_count=1,
                                   role=glue_job_role,
                                   tags={
                                       "Project": self.project,
                                       "Owner": self.owner 
                                   })
        
        #===========================================================================================================================
        #=======================================================STEP FUNCTIONS======================================================
        #===========================================================================================================================
        
        # Define Step Functions Policy
        states_policy = aws_iam.ManagedPolicy(self, "StatesPolicy", description="Used for StepFunctions permissions",
                                               managed_policy_name="mlops-step-function-policy",
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
                                                            storage_bucket.bucket_arn,
                                                            storage_bucket.bucket_arn + "/*"
                                                        ]
                                                    ),
                                                    aws_iam.PolicyStatement(
                                                        sid="GlueAccess",
                                                        effect=aws_iam.Effect.ALLOW,
                                                        actions=[
                                                            "glue:*"
                                                        ],
                                                        resources=[
                                                            "*"
                                                        ],
                                                        conditions={
                                                            "StringEquals": {
                                                                "glue:resourceTag/Name": self.owner
                                                            }
                                                        }
                                                    ),
                                               ]
                                            )
        
        # Define Step Functions Role
        states_role = aws_iam.Role(self, "StatesRole", role_name="mlops-step-function-role",
                                    assumed_by=aws_iam.ServicePrincipal("states.amazonaws.com"),
                                    managed_policies=[aws_iam.ManagedPolicy.from_aws_managed_policy_name("CloudWatchEventsFullAccess"),
                                                      states_policy])
        
        # Define Step Functions Tasks
        convert_job_step = aws_stepfunctions_tasks.GlueStartJobRun(self, "ConvertGlueJobStep", glue_job_name=convert_job.job_name,
                                                                   arguments=aws_stepfunctions.TaskInput.from_object(
                                                                       {
                                                                            "--database_name": aws_stepfunctions.JsonPath.string_at("$.database_name"),
                                                                            "--file_key": aws_stepfunctions.JsonPath.string_at("$.file_key"),
                                                                            "--bucket": aws_stepfunctions.JsonPath.string_at("$.bucket"),
                                                                            "--file_name": aws_stepfunctions.JsonPath.string_at("$.file_name"),
                                                                            "--ingest_type": aws_stepfunctions.JsonPath.string_at("$.ingest_type"),
                                                                            "--additional-python-modules": aws_stepfunctions.JsonPath.string_at("$.--additional-python-modules")
                                                                       }
                                                                   ),
                                                                   result_path=aws_stepfunctions.JsonPath.DISCARD)
        
        transform_job_step = aws_stepfunctions_tasks.GlueStartJobRun(self, "TransformGlueJobStep", glue_job_name=transform_job.job_name,
                                                                   arguments=aws_stepfunctions.TaskInput.from_object(
                                                                       {
                                                                           "--database_name": aws_stepfunctions.JsonPath.string_at("$.database_name"),
                                                                           "--file_key": aws_stepfunctions.JsonPath.string_at("$.file_key"),
                                                                           "--bucket": aws_stepfunctions.JsonPath.string_at("$.bucket"),
                                                                           "--file_name": aws_stepfunctions.JsonPath.string_at("$.file_name"),
                                                                           "--ingest_type": aws_stepfunctions.JsonPath.string_at("$.ingest_type"),
                                                                           "--additional-python-modules": aws_stepfunctions.JsonPath.string_at("$.--additional-python-modules")
                                                                       }
                                                                   ))
        
        # Define StateMachine Definition of Steps
        state_definition = aws_stepfunctions.Chain.start(convert_job_step).next(transform_job_step).next(aws_stepfunctions.Succeed(
                        self, "ETLProcessSuccess", comment="ETL Process finished Successfully"))
        
        # Define StateMachine
        state_machine = aws_stepfunctions.StateMachine(self, "ETLStateMachine", state_machine_name="mlops-etl-process",
                                                       definition=state_definition, role=states_role)
        
        #===========================================================================================================================
        #=======================================================LAMBDA==============================================================
        #===========================================================================================================================
        
        # Define the Lambda Policy
        lambda_policy = aws_iam.ManagedPolicy(self, "LambdaPolicy", description="Used for ETL Lambda permissions",
                                               managed_policy_name="mlops-etl-lambda-policy",
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
                                                        sid="StepFunctionsAccess",
                                                        effect=aws_iam.Effect.ALLOW,
                                                        actions=[
                                                            "states:StartExecution"
                                                        ],
                                                        resources=[
                                                            state_machine.state_machine_arn
                                                        ]
                                                    ),
                                               ]
                                            )
        
        # Define Lambda Role
        lambda_role = aws_iam.Role(self, "LambdaRole", role_name="mlops-etl-lambda-role",
                                    assumed_by=aws_iam.ServicePrincipal("lambda.amazonaws.com"),
                                    managed_policies=[lambda_policy])
        
        # Define Lambda function
        etl_lambda = aws_lambda.Function(self, "ETLLambda", role=lambda_role,
                                              runtime=aws_lambda.Runtime.PYTHON_3_8,
                                              handler="etl_lambda.lambda_handler",
                                              vpc=self.vpc, vpc_subnets=aws_ec2.SubnetType.PRIVATE_WITH_NAT,
                                              security_groups=[self.outbound_security_group],
                                              code=aws_lambda.Code.from_asset("lambda_code/etl_lambda"),
                                              environment={
                                                        "SecurityGroupId": self.outbound_security_group.security_group_id,
                                                        "StateMachineArn": state_machine.state_machine_arn,
                                                        "GlueDatabaseName": glue_database.database_name
                                                  },
                                              timeout=Duration.minutes(5), 
                                              function_name="mlops-etl-lambda",
                                              description="Used for starting the Step Functions for ETL process",
                                              memory_size=256)
        
        # Define the S3 Notifications to trigger Lambda
        storage_bucket.add_event_notification(aws_s3.EventType.OBJECT_CREATED, 
                                              aws_s3_notifications.LambdaDestination(etl_lambda),
                                              aws_s3.NotificationKeyFilter(prefix="raw/partitioned/csv/"))
        
        storage_bucket.add_event_notification(aws_s3.EventType.OBJECT_CREATED, 
                                              aws_s3_notifications.LambdaDestination(etl_lambda),
                                              aws_s3.NotificationKeyFilter(prefix="raw/total/csv/"))
        