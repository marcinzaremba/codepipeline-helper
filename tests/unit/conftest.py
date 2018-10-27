import functools
import json
import uuid
from typing import Dict, Optional
from unittest import mock

from codepipeline_helper import Artifact

import pytest


def action_state(event: Dict, func):
    _, kwargs = func.call_args

    assert func.call_count == 1
    assert 'jobId' in kwargs
    assert kwargs['jobId'] == event['CodePipeline.job']['id']

    return True


@pytest.fixture
def action_successful(codepipeline):
    return functools.partial(action_state, func=codepipeline.put_job_success_result)


@pytest.fixture
def action_failed(codepipeline):
    return functools.partial(action_state, func=codepipeline.put_job_failure_result)


@pytest.fixture
def action_continuation_token(codepipeline):
    def _continuation_token():
        _, kwargs = codepipeline.put_job_success_result.call_args

        assert 'continuationToken' in kwargs

        return json.loads(kwargs['continuationToken'])

    return _continuation_token


@pytest.fixture
def action_failure_message(codepipeline):
    def _action_failure_message():
        _, kwargs = codepipeline.put_job_failure_result.call_args

        assert 'failureDetails' in kwargs
        assert 'message' in kwargs['failureDetails']

        return kwargs['failureDetails']['message']

    return _action_failure_message


@pytest.fixture
def s3():
    client = mock.MagicMock()
    client.download_fileobj.side_effect = None

    return client


@pytest.fixture
def codepipeline():
    client = mock.MagicMock()
    client.put_job_success_result.return_value = {}
    client.put_job_failure_result.return_value = {}

    return client


@pytest.fixture
def boto3(monkeypatch, s3, codepipeline):
    def _client_mock(name, *args, **kwargs):
        if name == 's3':
            return s3
        elif name == 'codepipeline':
            return codepipeline

    monkeypatch.setattr('codepipeline_helper.boto3.Session.client', mock.Mock(side_effect=_client_mock))


@pytest.fixture
def get_event():
    def _get_event_artifacts(artifacts: Optional[Dict[str, Artifact]] = None):
        for name, item in artifacts.items():
            yield {
                'name': name,
                'location': {'s3Location': {
                    'bucketName': item.bucket_name,
                    'objectKey': item.object_key,
                }}
            }

    def _get_event(token: Optional[str] = None, params=None, input_artifacts=None, output_artifacts=None):
        data = {
            'artifactCredentials': {
                'accessKeyId': '',
                'secretAccessKey': '',
                'sessionToken': '',
            },
            'outputArtifacts': [],
            'inputArtifacts': [],
            'actionConfiguration': {'configuration': {}}
        }
        job_id = str(uuid.uuid4())
        event = {
            'CodePipeline.job': {
                'id': job_id,
                'data': data,
            }
        }
        if token:
            data['continuationToken'] = json.dumps(token)
        if params:
            data['actionConfiguration']['configuration']['UserParameters'] = json.dumps(params)
        if input_artifacts:
            data['inputArtifacts'].extend(_get_event_artifacts(input_artifacts))
        if output_artifacts:
            data['outputArtifacts'].extend(_get_event_artifacts(output_artifacts))

        return event

    return _get_event
