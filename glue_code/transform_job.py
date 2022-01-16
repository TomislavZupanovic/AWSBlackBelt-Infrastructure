import sys
import io
import os
from datetime import datetime, timedelta

import pandas as pd
from awsglue.utils import getResolvedOptions
import awswrangler

import lakefs_client
from lakefs_client import models
from lakefs_client.client import LakeFSClient


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

def create_target(raw_data: pd.DataFrame) -> pd.DataFrame:
    """ Creates the RUL target variable based on max cycles from the dataset 
        :argument: raw_data - Pandas DataFrame containing training data
        :return: dataset - Pandas DataFrame containing training data and target variable
    """
    data = raw_data.copy()
    # Group the data by unit column and calculate the max cycle
    grouped = data.groupby('unit')
    max_cycle = grouped['cycle'].max()
    # Merge the max cycle back to the data
    data = data.merge(max_cycle.to_frame(name='max_cycle'), left_on='unit', right_index=True)
    # Calculate difference between max cycle and current cycle, create RUL
    data['rul'] = data['max_cycle'] - data['cycle']
    # Drop the max cycle column
    data.drop('max_cycle', axis=1, inplace=True)
    return data


if __name__ == '__main__':
    # lakeFS credentials and endpoint
    configuration = lakefs_client.Configuration()
    configuration.username = ''
    configuration.password = ''
    configuration.host = 'http://localhost:8000' # TODO

    lfs_client = LakeFSClient(configuration)

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
    raw_data = awswrangler.s3.read_parquet(path=[f"s3://{args['bucket']}/{file_key}"])

    if ingest_type == 'partitioned':
        curated_data = add_timestamp(raw_data)
    else:
        curated_data = create_target(raw_data)

    # Save transformed data to parquet format
    path = f"s3://{args['bucket']}/curated/parquet"
    table = f"mlops-curated-data-{ingest_type}"
    awswrangler.s3.to_parquet(curated_data, path=path, dataset=True, mode='append', 
                            database=args['database_name'], table=table, partition_cols=['unit'])

    # Save Dataframes locally
    raw_data.to_csv('raw_data.csv')
    curated_data.to_csv('curated.csv')

    # Save transformed data to the LakeFS
    with open('raw_data.csv', 'rb') as data:
        lfs_client.objects.upload_object(repository='PredictiveMaintenance', branch='main', 
                                    path=f"{ingest_type}/raw/{filename.split('.')[0]}.csv", content=data)
    with open('curated.csv', 'rb') as data:
        lfs_client.objects.upload_object(repository='PredictiveMaintenance', branch='main', 
                                    path=f"{ingest_type}/curated/{filename.split('.')[0]}.csv", content=data)
    os.remove('curated.csv')
    os.remove('raw_data.csv')

    # Commit the data upload
    lfs_client.commits.commit(repository='PredictiveMaintenance', branch='main',
                    commit_creation=models.CommitCreation(message='Data added to the LakeFS', metadata={'ingest_type': ingest_type}))

