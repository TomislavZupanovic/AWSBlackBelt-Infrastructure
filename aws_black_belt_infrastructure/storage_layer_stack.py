from aws_cdk import (
    core as cdk,
    aws_s3,
    aws_glue
)

class StorageLayerStack(cdk.Stack):

    def __init__(self, scope: cdk.Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # TODO: Add global tags
        
        #======================================================================================
        #=========================================VPC==========================================
        #======================================================================================

        # TODO: Import VPC and subnets
        
    
        #======================================================================================
        #=========================================S3===========================================
        #======================================================================================

        # Define the Storage Bucket
        storage_bucket = aws_s3.Bucket(self, "StorageBucket", bucket_name="mlops-storage-bucket",
                                       block_public_access=aws_s3.BlockPublicAccess.BLOCK_ALL,
                                       public_read_access=False, removal_policy=cdk.RemovalPolicy.DESTROY,
                                       versioned=False)
        
        #======================================================================================
        #=========================================GLUE=========================================
        #======================================================================================
        # TODO: Add Glue Role
        
        # Define the Glue Job for converting .csv to .parquet
        convert_job = aws_glue.Job(self, "ConvertGlueJob", 
                                   executable=aws_glue.JobExecutable.python_shell(
                                       glue_version=aws_glue.GlueVersion.V3_0,
                                       python_version=aws_glue.PythonVersion.THREE,
                                       script=aws_glue.Code.from_asset(path="glue_code/convert_job.py")
                                   ),
                                   default_arguments={"--additional-python-modules": "awswrangler"},
                                   description="Job used to convert data format from CSV to the Parquet",
                                   job_name="mlops-convert-job",
                                   worker_type=aws_glue.WorkerType.STANDARD,
                                   worker_count=1,
                                   role=glue_job_role,
                                   tags={  # TODO
                                       "":"",
                                       "": "" 
                                   })