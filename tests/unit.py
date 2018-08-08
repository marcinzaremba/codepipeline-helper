from unittest import mock

from codepipeline_helper import action, ContinueLater, InputArtifact, OutputArtifact
from tests import UnitTestCase


class TestAction(UnitTestCase):
    def test_set_on_continue_handler(self):
        decorated_handler = action(mock.MagicMock())
        on_continue_handler = mock.MagicMock()

        result = decorated_handler.on_continue(on_continue_handler)

        self.assertEqual(result, on_continue_handler)
        self.assertEqual(decorated_handler.on_continue_handler, on_continue_handler)

    def test_call_handler_with_kwargs(self):
        handler = mock.MagicMock()
        decorated_handler = action(handler)
        params = {'param1': 'one', 'param2': 'two'}
        bucket_name = self.randstr()
        input_artifacts = {
            'input1': InputArtifact(bucket_name=bucket_name, object_key=self.randstr(), s3_client=self.s3),
            'input2': InputArtifact(bucket_name=bucket_name, object_key=self.randstr(), s3_client=self.s3),
        }
        output_artifacts = {
            'output1': OutputArtifact(bucket_name=bucket_name, object_key=self.randstr(), s3_client=self.s3),
            'output2': OutputArtifact(bucket_name=bucket_name, object_key=self.randstr(), s3_client=self.s3),
        }
        event = self.get_event(params=params, input_artifacts=input_artifacts, output_artifacts=output_artifacts)

        decorated_handler(event, None)

        handler.assert_called_with(
            params=params,
            input_artifacts=input_artifacts,
            output_artifacts=output_artifacts
        )

    # def test_read_artifacts(self):
    #     @action
    #     def handler(params, input_artifacts, output_artifacts):
    #         pass
    #     event = self.get_event()
    #
    #     handler(event, None)
    #

    def test_run_handler(self):
        handler = mock.MagicMock()
        decorated_handler = action(handler)
        event = self.get_event()

        decorated_handler(event, None)

        self.assertActionSuccessful(event)
        self.assertEqual(handler.call_count, 1)

    def test_call_continue_later(self):
        token = {'sample': 'token'}
        handler = mock.MagicMock(side_effect=ContinueLater(**token))
        decorated_handler = action(handler)
        event = self.get_event()

        decorated_handler(event, None)

        self.assertActionSuccessful(event)
        self.assertContinuationTokenEqual(token)

    def test_run_on_continue_handler(self):
        handler = mock.MagicMock()
        decorated_handler = action(handler)
        on_continue_handler = mock.MagicMock()
        decorated_handler.on_continue(on_continue_handler)
        token = {'sample': 'token'}
        event = self.get_event(token=token)

        decorated_handler(event, None)

        self.assertActionSuccessful(event)
        self.assertEqual(on_continue_handler.call_count, 1)
        self.assertEqual(handler.call_count, 0)

    def test_call_fail(self):
        handler = mock.MagicMock(side_effect=Exception)
        decorated_handler = action(handler)
        event = self.get_event()

        decorated_handler(event, None)

        self.assertActionFailed(event)
        self.assertFailureMessageRegex('Action failed due to exception')
