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
                        'ingest_type',
                        'bucket'])
# Get the raw csv data
s3 = boto3.client('s3')
obj = s3.get_object(Bucket=args['bucket'], Key=args['file_key'])
raw_data = pd.read_csv(io.BytesIO(obj['Body'].read()))

# Get ingest type
ingest_type = args['ingest_type']

# Add column names
# Define number of sensor columns
sensors_number = len(raw_data.columns) - 5
# Rename the columns to corrensponding value
column_names = ['unit', 'cycle', 'altitude', 'mach', 'tra'] + [f'sensor_{i}' for i in range(1, sensors_number + 1)]
raw_data.columns = column_names

# Convert the csv data to the parquet format
path = f"s3://{args['bucket']}/raw/parquet"
table = f"mlops-raw-data-{ingest_type}"
awswrangler.s3.to_parquet(raw_data, path=path, dataset=True, mode='append', 
                        database=args['database_name'], table=table, partition_cols=['unit'])
