import json
import os
import shutil
import uuid
import zipfile
from pathlib import Path
import tempfile

import boto3
import pip
import inspect

from codepipeline_helper import action

HANDLER_HEADER_SRC = "from codepipeline_helper import *\n\n"
HANDLER_FILE_NAME = 'index.py'
S3_BUCKET_NAME = 'codepipeline-helper'
PIPELINE_STACK_TEMPLATE = json.dumps({
    'AWSTemplateFormatVersion': '2010-09-09',
    'Parameters': {
        'S3Bucket': {
            'Type': 'String',
        },
        'LambdaCodeS3Key': {
            'Type': 'String',
        }
    },
    'Resources': {
        'LambdaRole': {
            'Type': 'AWS::IAM::Role',
            'Properties': {
                'AssumeRolePolicyDocument': {
                    'Version': '2012-10-17',
                    'Statement': {
                        'Effect': 'Allow',
                        'Principal': {'Service': 'lambda.amazonaws.com'},
                        'Action': 'sts:AssumeRole',
                    }
                },
                'ManagedPolicyArns': [
                    'arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole'
                ],
                'Policies': [
                    {
                        'PolicyName': 'LambdaRole',
                        'PolicyDocument': {
                            'Version': '2012-10-17',
                            'Statement': {
                                'Effect': 'Allow',
                                'Action': 'codepipeline:PutJobSuccessResult',
                                'Resource': '*',
                            }
                        }
                    }
                ]
            }
        },
        'LambdaFunction': {
            'Type': 'AWS::Lambda::Function',
            'Properties': {
                'Runtime': 'python3.6',
                'Role': {'Fn::GetAtt': 'LambdaRole.Arn'},
                'MemorySize': 128,
                'Code': {
                    'S3Bucket': {'Ref': 'S3Bucket'},
                    'S3Key': {'Ref': 'LambdaCodeS3Key'}
                },
                'Handler': 'index.handler',
            }
        },
        'PipelineRole': {
            'Type': 'AWS::IAM::Role',
            'Properties': {
                'AssumeRolePolicyDocument': {
                    'Version': '2012-10-17',
                    'Statement': {
                        'Effect': 'Allow',
                        'Principal': {'Service': 'codepipeline.amazonaws.com'},
                        'Action': 'sts:AssumeRole',
                    }
                },
                'Policies': [
                    {
                        'PolicyName': 'PipelineRole',
                        'PolicyDocument': {
                            'Version': '2012-10-17',
                            'Statement': [
                                {
                                    'Effect': 'Allow',
                                    'Action': [
                                        's3:GetObject',
                                        's3:PutObject',
                                        's3:GetObjectVersion',
                                    ],
                                    'Resource': 'arn:aws:s3:::{}/*'.format(S3_BUCKET_NAME)
                                },
                                {
                                    'Effect': 'Allow',
                                    'Action': 's3:GetBucketVersioning',
                                    'Resource': 'arn:aws:s3:::{}'.format(S3_BUCKET_NAME)
                                },
                                {
                                    "Effect": "Allow",
                                    'Action': [
                                        'lambda:ListFunctions',
                                        'lambda:InvokeFunction',
                                        'iam:PassRole',
                                    ],
                                    'Resource': '*'
                                }
                            ]
                        }
                    }
                ]
            }
        },
        'Pipeline': {
            'Type': 'AWS::CodePipeline::Pipeline',
            'Properties': {
                'RoleArn': {'Fn::GetAtt': 'PipelineRole.Arn'},
                'ArtifactStore': {
                    'Type': 'S3',
                    'Location': {'Ref': 'S3Bucket'},
                },
                'Stages': [
                    {
                        'Name': 'Source',
                        'Actions': [
                            {
                                'Name': 'Source',
                                'ActionTypeId': {
                                    'Category': 'Source',
                                    'Owner': 'AWS',
                                    'Version': 1,
                                    'Provider': 'S3'
                                },
                                'Configuration': {
                                    'S3Bucket': {'Ref': 'S3Bucket'},
                                    'S3ObjectKey': 'pipeline/InputArtifact'
                                },
                                'OutputArtifacts': [
                                    {'Name': 'InputArtifact'}
                                ],
                                'RunOrder': 1
                            }
                        ]
                    },
                    {
                        'Name': 'Invoke',
                        'Actions': [
                            {
                                'Name': 'Invoke',
                                'ActionTypeId': {
                                    'Category': 'Invoke',
                                    'Owner': 'AWS',
                                    'Version': 1,
                                    'Provider': 'Lambda',
                                },
                                'InputArtifacts': [
                                    {'Name': 'InputArtifact'}
                                ],
                                'Configuration': {
                                    'FunctionName': {'Ref': 'LambdaFunction'}
                                }
                            }
                        ]
                    }
                ]
            }
        }
    },
    'Outputs': {
        'PipelineName': {
            'Value': {'Ref': 'Pipeline'}
        }
    }
})

s3 = boto3.resource('s3')


def build_lambda(func):
    curr_dir = os.getcwd()
    work_dir = tempfile.mkdtemp()
    try:
        # Prepare and change to working directory
        func_src = inspect.getsource(func)
        os.chdir(work_dir)
        # Create lambda content
        package_path = Path('package')
        package_path.mkdir()
        handler_src = HANDLER_HEADER_SRC + func_src
        handler_path =  package_path / HANDLER_FILE_NAME
        handler_path.write_text(handler_src)
        pip.main(['install', curr_dir, '-qq', '-t', package_path])
        # Make archive and upload to S3
        archive_file = shutil.make_archive('package', 'zip', package_path)
        s3_key = 'lambda/{}'.format(uuid.uuid4().hex)
        s3.meta.client.upload_file(archive_file, S3_BUCKET_NAME, s3_key)
    except: # noqa
        raise
    else:
        return s3_key
    finally:
        os.chdir(curr_dir)
        shutil.rmtree(work_dir)


def deploy_pipeline(s3_key):
    cfn = boto3.client('cloudformation')
    stack_name = 'codepipeline-helper-{}'.format(uuid.uuid4().hex)
    parameters = {
        'S3Bucket': S3_BUCKET_NAME,
        'LambdaCodeS3Key': s3_key,
    }
    cfn.create_stack(
        StackName=stack_name,
        TemplateBody=PIPELINE_STACK_TEMPLATE,
        Capabilities=['CAPABILITY_IAM'],
        Parameters=[{'ParameterKey': k, 'ParameterValue': v} for k, v in parameters.items()]
    )
    waiter = cfn.get_waiter('stack_create_complete')
    waiter.wait(StackName=stack_name, WaiterConfig={'delay': 15})
    response = cfn.describe_stacks(StackName=stack_name)
    outputs = {output['OutputKey']: output['OutputValue'] for output in response['Stacks'][0]['Outputs']}

    return stack_name, outputs


def create_artifact(items):
    temp_file = tempfile.NamedTemporaryFile()
    with zipfile.ZipFile(temp_file.name, 'w') as zip_file:
        for key, value in items.items():
            zip_file.writestr(key, value)

    s3.meta.client.upload_file(temp_file.name, S3_BUCKET_NAME, 'pipeline/InputArtifact')


def execute_pipeline(func, input_artifact):
    create_artifact(input_artifact)
    s3_key = build_lambda(func)
    stack_name, outputs = deploy_pipeline(s3_key)
    print(stack_name, outputs)


@action
def handler(input_artifacts, output_artifacts, params):
    print(params)
    print(input_artifacts.keys())


execute_pipeline(handler, {'hello': 'world'})
