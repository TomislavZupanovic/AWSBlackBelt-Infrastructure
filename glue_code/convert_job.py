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
# Get the raw csv data
s3 = boto3.client('s3')
obj = s3.get_object(Bucket=args['bucket'], Key=args['file_key'])
raw_data = pd.read_csv(io.BytesIO(obj['Body'].read()))

# Convert the csv data to the parquet format
path = f"s3://{args['bucket']}/raw/parquet/"
awswrangler.s3.to_parquet() # TODO
