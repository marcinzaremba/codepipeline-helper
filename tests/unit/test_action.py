from unittest import mock

from codepipeline_helper import (ContinueLater, InputArtifact, OutputArtifact,
                                 action)

import pytest


def test_run_handler(get_event, boto3, action_successful):
    handler = mock.MagicMock()
    decorated_handler = action(handler)
    event = get_event()

    decorated_handler(event, None)

    assert handler.call_count == 1
    assert action_successful(event)


def test_set_on_continue_handler():
    decorated_handler = action(mock.MagicMock())
    on_continue_handler = mock.MagicMock()

    result = decorated_handler.on_continue(on_continue_handler)

    assert result == on_continue_handler
    assert decorated_handler.on_continue_handler == on_continue_handler


def test_run_on_continue_handler(get_event, boto3, action_successful):
    handler = mock.MagicMock()
    decorated_handler = action(handler)
    on_continue_handler = mock.MagicMock()
    decorated_handler.on_continue(on_continue_handler)
    token = {'sample': 'token'}
    event = get_event(token=token)

    decorated_handler(event, None)

    assert action_successful(event)
    assert on_continue_handler.call_count == 1
    assert handler.call_count == 0


def test_call_continue_later(get_event, boto3, codepipeline, action_successful, action_continuation_token):
    token = {'sample': 'token'}
    handler = mock.MagicMock(side_effect=ContinueLater(**token))
    decorated_handler = action(handler)
    event = get_event()

    decorated_handler(event, None)

    assert action_successful(event)
    assert action_continuation_token() == token


def test_call_fail(get_event, boto3, action_failed, action_failure_message):
    handler = mock.MagicMock(side_effect=Exception)
    decorated_handler = action(handler)
    event = get_event()

    decorated_handler(event, None)

    assert action_failed(event)
    assert 'Action failed due to exception' in action_failure_message()


@pytest.mark.parametrize('handler_kwarg_names,expected_handler_kwargs', [
    pytest.param([], {}, id='with_everything_empty'),
    pytest.param(['params'], {'params': {'param1': 'one', 'param2': 'two'}}, id='with_known_kwarg'),
    pytest.param(['unknown_param'], {'unknown_param': None}, id='with_unkown_kwarg'),
])
def test_call_handler_with_specified_kwargs(get_event, boto3, monkeypatch,
                                            handler_kwarg_names, expected_handler_kwargs):
    monkeypatch.setattr('inspect.signature', mock.MagicMock(
        return_value=mock.MagicMock(parameters=handler_kwarg_names)
    ))
    handler = mock.MagicMock()
    decorated_handler = action(handler)
    event = get_event(params={'param1': 'one', 'param2': 'two'})

    decorated_handler(event, None)

    handler.assert_called_with(**expected_handler_kwargs)


def test_call_handler_with_parsed_artifacts(get_event, boto3, monkeypatch, s3):
    monkeypatch.setattr('inspect.signature', mock.MagicMock(
        return_value=mock.MagicMock(parameters=['input_artifacts', 'output_artifacts'])
    ))
    handler = mock.MagicMock()
    decorated_handler = action(handler)
    input_artifacts = {
        'input1': InputArtifact(bucket_name='bucket_name', object_key='input1', s3_client=s3),
        'input2': InputArtifact(bucket_name='bucket_name', object_key='input2', s3_client=s3),
    }
    output_artifacts = {
        'output1': OutputArtifact(bucket_name='bucket_name', object_key='output1', s3_client=s3),
        'output2': OutputArtifact(bucket_name='bucket_name', object_key='output2', s3_client=s3),
    }
    event = get_event(input_artifacts=input_artifacts, output_artifacts=output_artifacts)

    decorated_handler(event, None)

    handler.assert_called_with(input_artifacts=input_artifacts, output_artifacts=output_artifacts)
