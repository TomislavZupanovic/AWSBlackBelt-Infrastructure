from aws_cdk import (
    core as cdk,
    aws_s3,
    aws_glue_alpha as aws_glue,
    aws_iam,
    aws_ec2
)

class StorageLayerStack(cdk.Stack):

    def __init__(self, scope: cdk.Construct, construct_id: str, parameters: dict, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Get Account environment parameters
        account_id = parameters["AccountId"]
        region = parameters["Region"]

        # Define Tags for all resources (where they apply)
        cdk.Tags.of(self).add("Project", "BlackBelt")
        cdk.Tags.of(self).add("Owner", "Tomislav Zupanovic")
        
        #======================================================================================
        #=========================================VPC==========================================
        #======================================================================================

        # Import VPC and subnets
        vpc = aws_ec2.Vpc.from_lookup(self, "MainVPC", vpc_name="aast-innovation-vpc")
        subnets = vpc.private_subnets
        subnets_ids = [subnet.subnet_id for subnet in subnets]
        
        # Define Security Group with allowed outbound traffic
        outbound_security_group = aws_ec2.SecurityGroup(self, "OutboundSecurityGroup",
                                                        vpc=vpc, description="Allow all outbound access only",
                                                        allow_all_outbound=True)
        
        #======================================================================================
        #=========================================S3===========================================
        #======================================================================================

        # Define the Storage Bucket
        storage_bucket = aws_s3.Bucket(self, "StorageBucket", bucket_name="mlops-storage-bucket",
                                       block_public_access=aws_s3.BlockPublicAccess.BLOCK_ALL,
                                       public_read_access=False, removal_policy=cdk.RemovalPolicy.DESTROY,
                                       versioned=False, encryption=aws_s3.BucketEncryption.S3_MANAGED)
        
        #======================================================================================
        #=========================================GLUE=========================================
        #======================================================================================
        
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
                                                            f"arn:aws:logs:{region}:{account_id}:log-group:/aws-glue/mlops-jobs/*"
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
                                                            glue_database.database_arn
                                                            
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
                                   executable=aws_glue.JobExecutable.python_shell(
                                       glue_version=aws_glue.GlueVersion.V3_0,
                                       python_version=aws_glue.PythonVersion.THREE,
                                       script=aws_glue.Code.from_asset(path="glue_code/convert_job.py")
                                   ),
                                   default_arguments={"--additional-python-modules": "awswrangler"},
                                   description="Job used to convert data format from CSV to the Parquet",
                                   continuous_logging=aws_glue.ContinuousLoggingProps(enabled=True,
                                                                                      log_group="/aws-glue/mlops-jobs/convert-job/")
                                   job_name="mlops-convert-job",
                                   worker_type=aws_glue.WorkerType.STANDARD,
                                   worker_count=1,
                                   role=glue_job_role,
                                   tags={
                                       "Project":"BlackBelt",
                                       "Owner": "Tomislav Zupanovic" 
                                   })
        
        # Define the Glue Job for transforming data
        transform_job = aws_glue.Job(self, "TransformGlueJob", 
                                   executable=aws_glue.JobExecutable.python_shell(
                                       glue_version=aws_glue.GlueVersion.V3_0,
                                       python_version=aws_glue.PythonVersion.THREE,
                                       script=aws_glue.Code.from_asset(path="glue_code/transform_job.py")
                                   ),
                                   default_arguments={"--additional-python-modules": "awswrangler"},
                                   description="Job used to transform raw data into curated data",
                                   continuous_logging=aws_glue.ContinuousLoggingProps(enabled=True,
                                                                                      log_group="/aws-glue/mlops-jobs/transform-job/")
                                   job_name="mlops-transform-job",
                                   worker_type=aws_glue.WorkerType.STANDARD,
                                   worker_count=1,
                                   role=glue_job_role,
                                   tags={
                                       "Project":"BlackBelt",
                                       "Owner": "Tomislav Zupanovic" 
                                   })
        