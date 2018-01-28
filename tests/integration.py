import boto3


def create_pipeline():
    cfn = boto3.client('cloudformation')
    
