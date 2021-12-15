import sys
from awsglue.utils import getResolvedOptions
import awswrangler

args = getResolvedOptions(sys.argv,
                          ['JOB_NAME',
                           'file_key',
                           'bucket_name'])