import sys
import io
import os

import pandas as pd
from awsglue.utils import getResolvedOptions
import awswrangler

import lakefs_client
from lakefs_client import models
from lakefs_client.client import LakeFSClient

# lakeFS credentials and endpoint
configuration = lakefs_client.Configuration()
configuration.username = ''
configuration.password = ''
configuration.host = 'http://localhost:8000'

client = LakeFSClient(configuration)

# Get the Arguments
args = getResolvedOptions(sys.argv,
                          ['JOB_NAME',
                           'database_name',
                           'file_key',
                           'ingest_type',
                           'file_name',
                           'bucket'])

# Define the path to the raw parquet file
file_key = args['file_key'].replace('/csv', '/parquet')
ingest_type = args['ingest_type']
filename = args['file_name']

# Get the raw parquet data
dataframe = awswrangler.s3.read_parquet(path=[f"s3://{args['bucket']}/{file_key}"])

# Do data transformations TODO
transformed_df = ''

# Save transformed data to parquet format
path = f"s3://{args['bucket']}/curated/parquet"
table = f"mlops-curated-data-{ingest_type}"
awswrangler.s3.to_parquet(transformed_df, path=path, dataset=True, mode='append', 
                          database=args['database_name'], table=table, partition_cols=['unit'])

# Save transformed data to the LakeFS
transformed_df.to_csv('data.csv')
with open('data.csv', 'rb') as data:
    client.objects.upload_object(repository='PredictiveMaintenance', branch='main', 
                                 path=f"{ingest_type}/{filename.split('.')[0]}.csv", content=data)
os.remove('data.csv')
# Commit the data upload
client.commits.commit(repository='PredictiveMaintenance', branch='main',
                commit_creation=models.CommitCreation(message='Data added to the LakeFS', metadata={'ingest_type': ingest_type}))

