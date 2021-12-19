FROM public.ecr.aws/lambda/python:3.8

# Copy Function code
COPY etl_lambda.py ${LAMBDA_TASK_ROOT}

# Install the function's dependencies using requirements.txt file
COPY requirements.txt .
RUN pip3 install -r requirements.txt --target "${LAMBDA_TASK_ROOT}"

# Set the CMD to a lambda_handler
CMD ["etl_lambda.lambda_handler"]