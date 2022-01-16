import sys
import io
from datetime import datetime, timedelta

import boto3
import pandas as pd
from awsglue.utils import getResolvedOptions
import awswrangler

def add_timestamp(splitted_data: pd.DataFrame) -> pd.DataFrame:
    """ Adds simulated timestamp the the ingested data to replicate 
        real life scenario
        :argument: splitted_data - Pandas Dataframe with data of 24 cycle split with all units
        :return: timestamp_data - Pandas Dataframe with timestamps for 24 cycle for all units
    """
    current_time = datetime.now()
    time_list = []
    # Get number of rows for one unit
    unit_length = len(splitted_data[splitted_data['unit']==1])
    # Iterate over the length of one unit
    for i in range(unit_length):
        # Calculate new time based on difference of current row
        new_time = current_time - timedelta(hours=i)
        # Append the new time as string in list
        time_list.append(new_time.strftime('%Y-%m-%d %H-%M-%S'))
    # Reverse the time list so that current time is last in unit
    time_list.reverse()
    timestamp_data_list = []
    # Iterate over all units
    for unit in splitted_data['unit'].unique():
        # Get rows only for the specified unit
        unit_splitted = splitted_data[splitted_data['unit']==unit]
        # Add the reversed timestamps as additional column
        unit_splitted.loc[:, 'timestamp'] = time_list
        # Append new dataframe for specified unit
        timestamp_data_list.append(unit_splitted)
    # Concatenate all dataframes of specified units into one dataframe
    timestamp_data = pd.concat(timestamp_data_list)
    return timestamp_data

if __name__ == '__main__':
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
