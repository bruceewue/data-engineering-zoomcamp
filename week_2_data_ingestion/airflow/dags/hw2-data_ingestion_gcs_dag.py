import os
from datetime import datetime
import logging
import gzip
from airflow import DAG
from airflow.utils.dates import days_ago
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator

from google.cloud import storage
# from airflow.providers.google.cloud.operators.bigquery import BigQueryCreateExternalTableOperator
import pyarrow.csv as pv
import pyarrow.parquet as pq

AIRFLOW_HOME = os.environ.get("AIRFLOW_HOME", "/opt/airflow/")

PROJECT_ID = os.environ.get("GCP_PROJECT_ID")
BUCKET = os.environ.get("GCP_GCS_BUCKET")



# dataset_file = "yellow_tripdata_2021-01.csv"
# dataset_url = f"https://s3.amazonaws.com/nyc-tlc/trip+data/{dataset_file}"
# path_to_local_home = os.environ.get("AIRFLOW_HOME", "/opt/airflow/")
#parquet_file = dataset_file.replace('.csv', '.parquet')
# BIGQUERY_DATASET = os.environ.get("BIGQUERY_DATASET", 'trips_data_all')


# TABLE_NAME_TEMPLATE = 'yellow_taxi_{{ execution_date.strftime(\'%Y_%m\') }}'


def format_to_parquet(src_file,dest_file):
    # if not src_file.endswith('.csv'):
    #     logging.error("Can only accept source files in CSV format, for the moment")
    #     return
    if src_file.endswith('.gz'):
        with gzip.open(src_file) as f:
            table = pv.read_csv(f)
            pq.write_table(table, dest_file)
    elif src_file.endswith('.csv'):
        table = pv.read_csv(src_file)
        pq.write_table(table, dest_file)
    else:
        logging.error("Can only accept source files in CSV format, for the moment")
        return


# NOTE: takes 20 mins, at an upload speed of 800kbps. Faster if your internet has a better upload speed
def upload_to_gcs(bucket, object_name, local_file):
    """
    Ref: https://cloud.google.com/storage/docs/uploading-objects#storage-upload-object-python
    :param bucket: GCS bucket name
    :param object_name: target path & file-name
    :param local_file: source path & file-name
    :return:
    """
    # WORKAROUND to prevent timeout for files > 6 MB on 800 kbps upload speed.
    # (Ref: https://github.com/googleapis/python-storage/issues/74)
    storage.blob._MAX_MULTIPART_SIZE = 5 * 1024 * 1024  # 5 MB
    storage.blob._DEFAULT_CHUNKSIZE = 5 * 1024 * 1024  # 5 MB
    # End of Workaround

    client = storage.Client()
    bucket = client.bucket(bucket)

    blob = bucket.blob(object_name)
    blob.upload_from_filename(local_file)




default_args = {
    "owner": "airflow",
    # "start_date": datetime(2019, 1, 1), #days_ago(1),
    # "end_date":datetime(2021, 1, 1),
    "depends_on_past": False,
    "retries": 1,
}


def donwload_parquetize_upload_dag(
    dag,
    url_template,
    local_file_path_template,
    local_parquet_path_template,
    gcs_path_template
):
    with dag:

        download_dataset_task = BashOperator(
            task_id="download_dataset_task",
            bash_command=f"curl -sSLf {url_template} > {local_file_path_template}"
        )

        # gunzip_dataset_task = BashOperator(
        # task_id="gunzip_dataset_task",
        # # bash_command=f"curl -sSL {dataset_url} > {path_to_local_home}/{dataset_file}"
        # bash_command=f"gunzip -f {local_file_path_template}" )

        format_to_parquet_task = PythonOperator(
            task_id="format_to_parquet_task",
            python_callable=format_to_parquet,
            op_kwargs={
                "src_file": local_file_path_template,
                "dest_file": local_parquet_path_template
            },
        )

        local_to_gcs_task = PythonOperator(
            task_id="local_to_gcs_task",
            python_callable=upload_to_gcs,
            op_kwargs={
                "bucket": BUCKET,
                "object_name": gcs_path_template,
                "local_file": local_parquet_path_template,
            },
        )

        rm_task = BashOperator(
            task_id="rm_task",
            bash_command=f"rm -f {local_file_path_template} {local_parquet_path_template}"
        )

        download_dataset_task >> format_to_parquet_task >> local_to_gcs_task >> rm_task



URL_PREFIX = 'https://github.com/DataTalksClub/nyc-tlc-data/releases/download/' 


YELLOW_TAXI_URL_TEMPLATE = URL_PREFIX + 'yellow/yellow_tripdata_{{ execution_date.strftime(\'%Y-%m\') }}.csv.gz'
YELLOW_TAXI_CSV_FILE_TEMPLATE = AIRFLOW_HOME + '/yellow_tripdata_{{ execution_date.strftime(\'%Y-%m\') }}.csv'
YELLOW_TAXI_GZ_FILE_TEMPLATE = AIRFLOW_HOME + '/yellow_tripdata_{{ execution_date.strftime(\'%Y-%m\') }}.csv.gz'
YELLOW_TAXI_PARQUET_FILE_TEMPLATE = AIRFLOW_HOME + '/yellow_tripdata_{{ execution_date.strftime(\'%Y-%m\') }}.parquet'
YELLOW_TAXI_GCS_PATH_TEMPLATE = 'raw/yellow_tripdata/{{ execution_date.strftime(\'%Y\') }}/yellow_tripdata_{{ execution_date.strftime(\'%Y-%m\') }}.parquet'

yellow_taxi_data_dag = DAG(
    dag_id="yellow_taxi_data_v2",
    schedule_interval="0 6 2 * *",
    start_date=datetime(2019, 1, 1),
    default_args=default_args,
    catchup=True,
    max_active_runs=3,
    tags=['dtc-de'],
)


donwload_parquetize_upload_dag(
    dag=yellow_taxi_data_dag,
    url_template=YELLOW_TAXI_URL_TEMPLATE,
    local_file_path_template=YELLOW_TAXI_GZ_FILE_TEMPLATE,
    local_parquet_path_template=YELLOW_TAXI_PARQUET_FILE_TEMPLATE,
    gcs_path_template=YELLOW_TAXI_GCS_PATH_TEMPLATE
)


GREEN_TAXI_URL_TEMPLATE = URL_PREFIX + 'green/green_tripdata_{{ execution_date.strftime(\'%Y-%m\') }}.csv.gz'
GREEN_TAXI_GZ_FILE_TEMPLATE = AIRFLOW_HOME + '/green_tripdata_{{ execution_date.strftime(\'%Y-%m\') }}.csv.gz'
GREEN_TAXI_PARQUET_FILE_TEMPLATE = AIRFLOW_HOME + '/green_tripdata_{{ execution_date.strftime(\'%Y-%m\') }}.parquet'
GREEN_TAXI_GCS_PATH_TEMPLATE = "raw/green_tripdata/{{ execution_date.strftime(\'%Y\') }}/green_tripdata_{{ execution_date.strftime(\'%Y-%m\') }}.parquet"

green_taxi_data_dag = DAG(
    dag_id="green_taxi_data_v1",
    schedule_interval="0 7 2 * *",
    start_date=datetime(2019, 1, 1),
    end_date=datetime(2021, 1, 1),
    default_args=default_args,
    catchup=True,
    max_active_runs=3,
    tags=['dtc-de'],
)

donwload_parquetize_upload_dag(
    dag=green_taxi_data_dag,
    url_template=GREEN_TAXI_URL_TEMPLATE,
    local_file_path_template=GREEN_TAXI_GZ_FILE_TEMPLATE,
    local_parquet_path_template=GREEN_TAXI_PARQUET_FILE_TEMPLATE,
    gcs_path_template=GREEN_TAXI_GCS_PATH_TEMPLATE
)

FHV_TAXI_URL_TEMPLATE = URL_PREFIX + 'fhv/fhv_tripdata_{{ execution_date.strftime(\'%Y-%m\') }}.csv.gz'
FHV_TAXI_GZ_FILE_TEMPLATE = AIRFLOW_HOME + '/fhv_tripdata_{{ execution_date.strftime(\'%Y-%m\') }}.csv.gz'
FHV_TAXI_PARQUET_FILE_TEMPLATE = AIRFLOW_HOME + '/fhv_tripdata_{{ execution_date.strftime(\'%Y-%m\') }}.parquet'
FHV_TAXI_GCS_PATH_TEMPLATE = "raw/fhv_tripdata/{{ execution_date.strftime(\'%Y\') }}/fhv_tripdata_{{ execution_date.strftime(\'%Y-%m\') }}.parquet"

fhv_taxi_data_dag = DAG(
    dag_id="hfv_taxi_data_v1",
    schedule_interval="0 8 2 * *",
    start_date=datetime(2019, 1, 1),
    end_date=datetime(2020, 1, 1),
    default_args=default_args,
    catchup=True,
    max_active_runs=3,
    tags=['dtc-de'],
)

donwload_parquetize_upload_dag(
    dag=fhv_taxi_data_dag,
    url_template=FHV_TAXI_URL_TEMPLATE,
    local_file_path_template=FHV_TAXI_GZ_FILE_TEMPLATE,
    local_parquet_path_template=FHV_TAXI_PARQUET_FILE_TEMPLATE,
    gcs_path_template=FHV_TAXI_GCS_PATH_TEMPLATE
)



ZONES_URL_TEMPLATE = 'https://github.com/DataTalksClub/nyc-tlc-data/releases/download/misc/taxi_zone_lookup.csv'
ZONES_CSV_FILE_TEMPLATE = AIRFLOW_HOME + '/taxi_zone_lookup.csv'
ZONES_PARQUET_FILE_TEMPLATE = AIRFLOW_HOME + '/taxi_zone_lookup.parquet'
ZONES_GCS_PATH_TEMPLATE = "raw/taxi_zone/taxi_zone_lookup.parquet"

zones_data_dag = DAG(
    dag_id="zones_data_v1",
    schedule_interval="@once",
    start_date=days_ago(1),
    default_args=default_args,
    catchup=True,
    max_active_runs=3,
    tags=['dtc-de'],
)

donwload_parquetize_upload_dag(
    dag=zones_data_dag,
    url_template=ZONES_URL_TEMPLATE,
    local_file_path_template=ZONES_CSV_FILE_TEMPLATE,
    local_parquet_path_template=ZONES_PARQUET_FILE_TEMPLATE,
    gcs_path_template=ZONES_GCS_PATH_TEMPLATE
)



# # NOTE: DAG declaration - using a Context Manager (an implicit way)
# with DAG(
#     dag_id="hw2_data_ingestion_gcs_dag_v4",
#     schedule_interval="0 6 2 * *",
#     default_args=default_args,
#     catchup=True,
#     max_active_runs=3,
#     tags=['dtc-de'],
# ) as yellow_taxi_data_v1:

#     download_dataset_task = BashOperator(
#         task_id="download_dataset_task",
#         # bash_command=f"curl -sSL {dataset_url} > {path_to_local_home}/{dataset_file}"
#         bash_command=f"curl -sSLf {YELLOW_TAXI_URL_TEMPLATE} > {YELLOW_TAXI_GZ_FILE_TEMPLATE} " 

#     )

#     gunzip_dataset_task = BashOperator(
#         task_id="gunzip_dataset_task",
#         # bash_command=f"curl -sSL {dataset_url} > {path_to_local_home}/{dataset_file}"
#         bash_command=f"gunzip -f {YELLOW_TAXI_GZ_FILE_TEMPLATE}" 

#     )

#     format_to_parquet_task = PythonOperator(
#         task_id="format_to_parquet_task",
#         python_callable=format_to_parquet,
#         op_kwargs={
#             # "src_file": f"{path_to_local_home}/{dataset_file}",
#             "src_file": YELLOW_TAXI_CSV_FILE_TEMPLATE,
#             "dest_file": YELLOW_TAXI_PARQUET_FILE_TEMPLATE,
#         },
#     )

#     # TODO: Homework - research and try XCOM to communicate output values between 2 tasks/operators
#     local_to_gcs_task = PythonOperator(
#         task_id="local_to_gcs_task",
#         python_callable=upload_to_gcs,
#         op_kwargs={
#             "bucket": BUCKET,
#             "object_name": YELLOW_TAXI_GCS_PATH_TEMPLATE,
#             # "local_file": f"{path_to_local_home}/{parquet_file}",
#             "local_file": YELLOW_TAXI_PARQUET_FILE_TEMPLATE,
#         },
#     )

#     # bigquery_external_table_task = BigQueryCreateExternalTableOperator(
#     #     task_id="bigquery_external_table_task",
#     #     table_resource={
#     #         "tableReference": {
#     #             "projectId": PROJECT_ID,
#     #             "datasetId": BIGQUERY_DATASET,
#     #             "tableId": "external_table",
#     #         },
#     #         "externalDataConfiguration": {
#     #             "sourceFormat": "PARQUET",
#     #             "sourceUris": [f"gs://{BUCKET}/raw/{parquet_file}"],
#     #         },
#     #     },
#     # )

#     rm_task = BashOperator(
#         task_id="rm_task",
#         # bash_command=f"curl -sSL {dataset_url} > {path_to_local_home}/{dataset_file}"
#         bash_command=f"rm {YELLOW_TAXI_CSV_FILE_TEMPLATE}  {YELLOW_TAXI_PARQUET_FILE_TEMPLATE}"
#     )

#     download_dataset_task >> gunzip_dataset_task >>format_to_parquet_task >> local_to_gcs_task >>rm_task




