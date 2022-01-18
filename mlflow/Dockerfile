FROM continuumio/miniconda3:4.10.3

RUN conda install -y -c conda-forge postgresql

RUN pip install mlflow>=1.23.0 \
    && pip install numpy==1.21.2 \
    && pip install scipy \
    && pip install pandas==1.3.3 \
    && pip install scikit-learn==0.24.2 \
    && pip install psycopg2-binary \
    && pip install boto3 

ENTRYPOINT mlflow server \ 
            --backend-store-uri postgresql://${DB_USERNAME}:${DB_PASSWORD}@${HOST}:${PORT}/${DATABASE} \
            --default-artifact-root s3://${BUCKET} \
            --host 0.0.0.0
