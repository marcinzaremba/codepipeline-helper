import inspect
import io
import json
import os
import shutil
import tempfile
import textwrap
import unittest
import uuid
import zipfile
from pathlib import Path

import boto3
import botocore
import pip


class IntegrationTestCase(unittest.TestCase):
    S3_BUCKET_NAME = 'codepipeline-helper'
    HANDLER_HEADER_SRC = "from codepipeline_helper import *\n\n"
    HANDLER_FILE_NAME = 'index.py'
    SOURCE_ARTIFACT_NAME = 'pipeline/Source'

    def setUp(self):
        os.environ['AWS_DATA_PATH'] = './tests/data/boto3'
        self.s3 = boto3.resource('s3')
        self.codepipeline = boto3.client('codepipeline')
        self.cloudformation = boto3.client('cloudformation')
        self.logs = boto3.client('logs')

        self.pipeline_name = None
        self.stack_name = None
        self.function_name = None

    def tearDown(self):
        if self.stack_name:
            self.cloudformation.delete_stack(StackName=self.stack_name)

    def assertPipelineExecutionSucceeded(self, timeout=300):
        if not self.pipeline_name:
            raise self.failureException('Pipeline not started.')

        executions = (
            self.codepipeline.list_pipeline_executions(pipelineName=self.pipeline_name)
                .get('pipelineExecutionSummaries', [])
        )
        if executions:
            execution_id = executions[0]['pipelineExecutionId']
        else:
            raise self.failureException('There is no pipeline execution.')

        waiter = self.codepipeline.get_waiter('pipeline_execution_succeeded')
        waiter_delay = 10
        waiter_config = {
            'Delay': waiter_delay,
            'MaxAttempts': int(timeout / waiter_delay),
        }
        try:
            waiter.wait(pipelineName=self.pipeline_name, pipelineExecutionId=execution_id, WaiterConfig=waiter_config)
        except botocore.exceptions.WaiterError:
            logs = '\n'.join(list(map(str, self.get_logs())))
            raise self.failureException(
                'Pipeline execution did not succeeded in {} seconds.\nFunction logs:\n{}'.format(timeout, logs)
            )

    def assertOutputArtifactEqual(self, name, value):
        if not self.function_name:
            raise self.failureException('Pipeline not started.')

        logs = list(self.get_logs('output_artifacts_published'))
        if logs:
            log = logs[0]
        else:
            raise self.failureException('No logs were found.')

        artifact = log['artifacts'].get(name)
        if not artifact:
            raise self.failureException('Output artifact {} does not exist.'.format(name))

        try:
            archive = self.load_artifact(**artifact)
        except zipfile.BadZipFile:
            raise self.failureException('Output artifact s3://{}/{} is empty.'.format(artifact['bucket_name'],
                                                                                      artifact['object_key']))

        archive_dict = {name: archive.read(name).decode() for name in archive.namelist()}
        self.assertEqual(archive_dict, value)

    def assertInLogs(self, item):
        self.assertIn(item, list(self.get_logs()))

    def get_stack_template(self, output_artifact_names=None):
        output_artifact_names = output_artifact_names or []

        return json.dumps({
            'AWSTemplateFormatVersion': '2010-09-09',
            'Parameters': {
                'S3Bucket': {
                    'Type': 'String',
                },
                'LambdaCodeS3Key': {
                    'Type': 'String',
                },
                'SourceArtifactS3Key': {
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
                                        'Action': [
                                            'codepipeline:PutJobSuccessResult',
                                            'codepipeline:PutJobFailureResult',
                                        ],
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
                                            'Resource': {'Fn::Sub': 'arn:aws:s3:::${S3Bucket}/*'}
                                        },
                                        {
                                            'Effect': 'Allow',
                                            'Action': 's3:GetBucketVersioning',
                                            'Resource': {'Fn::Sub': 'arn:aws:s3:::${S3Bucket}'}
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
                        'RestartExecutionOnUpdate': False,
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
                                            'S3ObjectKey': {'Ref': 'SourceArtifactS3Key'},
                                            'PollForSourceChanges': False,
                                        },
                                        'OutputArtifacts': [
                                            {'Name': 'Source'}
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
                                            {'Name': 'Source'}
                                        ],
                                        'OutputArtifacts': [{'Name': name} for name in output_artifact_names],
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
                },
                'FunctionName': {
                    'Value': {'Ref': 'LambdaFunction'}
                }
            }
        })

    def build_lambda(self, func):
        curr_dir = os.getcwd()
        work_dir = tempfile.mkdtemp()
        try:
            # Prepare and change to working directory
            func_src = inspect.getsource(func)
            os.chdir(work_dir)
            # Create lambda content
            package_path = Path('package')
            package_path.mkdir()
            handler_src = self.HANDLER_HEADER_SRC + textwrap.dedent(func_src)
            handler_path =  package_path / self.HANDLER_FILE_NAME
            handler_path.write_text(handler_src)
            pip.main(['install', curr_dir, '-qq', '-t', package_path])
            # Make archive and upload to S3
            archive_file = shutil.make_archive('package', 'zip', package_path)
            s3_key = 'lambda/{}'.format(uuid.uuid4().hex)
            self.s3.meta.client.upload_file(archive_file, self.S3_BUCKET_NAME, s3_key)
        except: # noqa
            raise
        else:
            return s3_key
        finally:
            os.chdir(curr_dir)
            shutil.rmtree(work_dir)

    def deploy_pipeline(self, lambda_s3_key, output_artifact_names=None):
        stack_name = 'codepipeline-helper-{}'.format(uuid.uuid4().hex)
        parameters = {
            'S3Bucket': self.S3_BUCKET_NAME,
            'LambdaCodeS3Key': lambda_s3_key,
            'SourceArtifactS3Key': self.SOURCE_ARTIFACT_NAME,
        }
        self.cloudformation.create_stack(
            StackName=stack_name,
            TemplateBody=self.get_stack_template(output_artifact_names),
            Capabilities=['CAPABILITY_IAM'],
            Parameters=[{'ParameterKey': k, 'ParameterValue': v} for k, v in parameters.items()]
        )
        waiter = self.cloudformation.get_waiter('stack_create_complete')
        waiter.wait(StackName=stack_name, WaiterConfig={'delay': 15})
        response = self.cloudformation.describe_stacks(StackName=stack_name)
        outputs = {output['OutputKey']: output['OutputValue'] for output in response['Stacks'][0]['Outputs']}

        return stack_name, outputs['PipelineName'], outputs['FunctionName']

    def create_artifact(self, items):
        temp_file = tempfile.NamedTemporaryFile()
        with zipfile.ZipFile(temp_file.name, 'w') as zip_file:
            for key, value in items.items():
                zip_file.writestr(key, value)

        self.s3.meta.client.upload_file(temp_file.name, self.S3_BUCKET_NAME, self.SOURCE_ARTIFACT_NAME)

    def load_artifact(self, bucket_name, object_key):
        stream = io.BytesIO()
        self.s3.meta.client.download_fileobj(bucket_name, object_key, stream)
        stream.seek(0)

        return zipfile.ZipFile(stream)

    def get_logs(self, event=None):
        group_name = '/aws/lambda/{}'.format(self.function_name)
        kwargs = dict(logGroupName=group_name)
        if event:
            kwargs['filterPattern'] = '{{$.event={}}}'.format(event)

        events = self.logs.filter_log_events(**kwargs).get('events', [])

        for event in events:
            try:
                yield json.loads(event['message'])
            except ValueError:
                yield event['message'].rstrip()

    def start_pipeline_execution(self, func, source_artifact, output_artifact_names=None):
        self.create_artifact(source_artifact)
        s3_key = self.build_lambda(func)
        self.stack_name, self.pipeline_name, self.function_name = self.deploy_pipeline(s3_key, output_artifact_names)