import functools
import json
import traceback
import tempfile
import zipfile

import boto3
import botocore


def log(event, **kwargs):
    kwargs['event'] = event
    print(json.dumps(kwargs))


def build_s3_client(credentials_dict):
    session = boto3.Session(
        aws_access_key_id=credentials_dict['accessKeyId'],
        aws_secret_access_key=credentials_dict['secretAccessKey'],
        aws_session_token=credentials_dict['sessionToken'],
    )
    client = session.client('s3', config=botocore.client.Config(signature_version='s3v4'))

    return client


def parse_artifacts(artifacts_list, s3_client, artifact_cls):
    for artifact_dict in artifacts_list:
        location = artifact_dict['location']['s3Location']
        yield artifact_dict['name'], artifact_cls(location['objectKey'], location['bucketName'], s3_client)


def publish_artifacts(artifacts):
    for artifact in artifacts.values():
        artifact.publish()
    log('output_artifacts_published', artifacts={name: artifact.to_dict() for name, artifact in artifacts.items()})


def parse_params(configuration):
    params_json = configuration.get('UserParameters')
    if params_json:
        return json.loads(params_json)
    else:
        return {}


def parse_token(data):
    token_json = data.get('continuationToken')
    if token_json:
        return json.loads(token_json)
    else:
        return None


class ContinueLater(Exception):
    def __init__(self, *args, **kwargs):
        self.token = kwargs
        super().__init__(*args)


class Job:
    def __init__(self, id, codepipeline=None):
        self.id = id
        self.codepipeline = codepipeline or boto3.client('codepipeline')

    def fail(self, message):
        log('job_failed', message=message)

        return self.codepipeline.put_job_failure_result(jobId=self.id,
                                                        failureDetails={'message': message, 'type': 'JobFailed'})

    def complete(self, summary=None):
        log('job_completed')

        return self.codepipeline.put_job_success_result(jobId=self.id)

    def continue_later(self, token):
        token_json = json.dumps(token)
        log('job_will_continue', token=token)

        return self.codepipeline.put_job_success_result(jobId=self.id, continuationToken=token_json)


class Artifact:
    def __init__(self, object_key, bucket_name, s3_client):
        self.s3 = s3_client
        self.object_key = object_key
        self.bucket_name = bucket_name
        self.file_obj = tempfile.NamedTemporaryFile()

    def __getitem__(self, key):
        return self.archive.read(key)

    def __eq__(self, other):
        return all([
            type(self) == type(other),
            self.bucket_name == other.bucket_name,
            self.object_key == other.object_key,
            self.s3 == other.s3,
        ])

    def __hash__(self):
        return hash((self.bucket_name, self.object_key, self.s3))

    @property
    def archive(self):
        raise NotImplementedError

    def to_dict(self):
        return dict(bucket_name=self.bucket_name, object_key=self.object_key)


class InputArtifact(Artifact):
    @property
    @functools.lru_cache()
    def archive(self):
        self.s3.download_fileobj(self.bucket_name, self.object_key, self.file_obj)

        return zipfile.ZipFile(self.file_obj.name)


class OutputArtifact(Artifact):
    @property
    @functools.lru_cache()
    def archive(self):
        return zipfile.ZipFile(self.file_obj.name, 'w')

    def __setitem__(self, key, value):
        return self.archive.writestr(key, value)

    def publish(self):
        self.archive.close()
        self.s3.upload_fileobj(self.file_obj, self.bucket_name, self.object_key)


def action(handler=None, **kwargs):
    if handler:
        config = {}
        config.update(kwargs)
    else:
        return functools.partial(action, **kwargs)

    def on_continue(on_continue_handler):
        wrapper.on_continue_handler = on_continue_handler

        return on_continue_handler

    def wrapper(event, context):
        job = event['CodePipeline.job']
        data = job['data']
        job = Job(job['id'])
        output_artifacts = []

        try:
            s3_client = build_s3_client(data['artifactCredentials'])
            token = parse_token(data)
            output_artifacts = dict(parse_artifacts(data['outputArtifacts'], s3_client, OutputArtifact))
            kwargs = dict(
                input_artifacts=dict(parse_artifacts(data['inputArtifacts'], s3_client, InputArtifact)),
                output_artifacts=output_artifacts,
                params=parse_params(data['actionConfiguration']['configuration']),
            )
            if token:
                kwargs['token'] = token
                actual_handler = wrapper.on_continue_handler
            else:
                actual_handler = handler

            actual_handler(**kwargs)
        except ContinueLater as e:
            publish_artifacts(output_artifacts)
            job.continue_later(e.token)
        except Exception as e:
            log('exception_raised', name=str(e), traceback=traceback.format_exc())
            job.fail('Action failed due to exception: {}'.format(type(e).__name__))
        else:
            publish_artifacts(output_artifacts)
            job.complete()

    wrapper.on_continue_handler = None
    wrapper.on_continue = on_continue
    functools.update_wrapper(wrapper, handler)

    return wrapper
