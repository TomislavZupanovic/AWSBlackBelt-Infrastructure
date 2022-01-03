import sys
import io

import boto3
import pandas as pd
from awsglue.utils import getResolvedOptions
import awswrangler

# Get the Arguments
args = getResolvedOptions(sys.argv,
                          ['JOB_NAME',
                           'database_name',
                           'file_key',
                           'bucket'])

# Define the path to the raw parquet file
file_key = args['file_key'].replace('/csv', '/parquet')

# Get the raw parquet data
dataframe = awswrangler.s3.read_parquet(path=[f"s3://{args['bucket']}/{file_key}"])

# Do data transformations TODO


# Save transformed data to parquet format
path = f"s3://{args['bucket']}/curated/parquet"
table = "mlops-curated-data"
awswrangler.s3.to_parquet(transformed_df, path=path, dataset=True, mode='append', 
                          database=args['database_name'], table=table, partition_cols=['unit'])
