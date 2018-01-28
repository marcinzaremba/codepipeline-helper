import unittest
from unittest import mock

from codepipeline_helper import action, ContinueLater


class TestAction(unittest.TestCase):
    def setUp(self):
        self.patches = dict(
            build_s3_client=mock.patch('codepipeline_helper.build_s3_client', autospec=True),
            parse_artifacts=mock.patch('codepipeline_helper.parse_artifacts', autospec=True),
            parse_params=mock.patch('codepipeline_helper.parse_params', autospec=True),
            parse_token=mock.patch('codepipeline_helper.parse_token', autospec=True, return_value=None),
            Job=mock.patch('codepipeline_helper.Job', autospec=True),
        )
        self.mocks = dict()
        for name, patch in self.patches.items():
            self.mocks[name] = patch.start()

    def tearDown(self):
        for patch in self.patches.values():
            patch.stop()
        self.mocks = dict()

    def test_on_continue_handler_is_set(self):
        decorated_handler = action(mock.MagicMock())
        on_continue_handler = mock.MagicMock()

        decorated_handler.on_continue(on_continue_handler)

        self.assertEqual(decorated_handler.on_continue_handler, on_continue_handler)

    def test_handler_is_run_when_no_token(self):
        handler = mock.MagicMock()
        decorated_handler = action(handler)

        decorated_handler(mock.MagicMock(), None)

        self.assertEqual(handler.call_count, 1)

    def test_on_continue_handler_is_run_when_token(self):
        self.mocks['parse_token'].return_value = True
        handler = mock.MagicMock()
        on_continue_handler = mock.MagicMock()
        decorated_handler = action(handler)
        decorated_handler.on_continue(on_continue_handler)

        decorated_handler(mock.MagicMock(), None)

        self.assertFalse(handler.called)
        self.assertTrue(on_continue_handler.called)

    def test_job_is_continued_when_continue_later_raised(self):
        handler = mock.MagicMock(side_effect=ContinueLater)
        decorated_handler = action(handler)

        decorated_handler(mock.MagicMock(), None)

        self.assertTrue(self.mocks['Job'].return_value.continue_later.called)

    def test_job_is_completed(self):
        decorated_handler = action(mock.MagicMock())

        decorated_handler(mock.MagicMock(), None)

        self.assertTrue(self.mocks['Job'].return_value.complete.called)

    def test_job_failed_when_exception_raised(self):
        decorated_handler = action(mock.MagicMock(side_effect=Exception))

        decorated_handler(mock.MagicMock(), None)

        self.assertTrue(self.mocks['Job'].return_value.fail.called)
