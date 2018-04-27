import functools
import unittest
from unittest import mock

from codepipeline_helper import action, ContinueLater
from tests import UnitTestCase


class TestAction(UnitTestCase):
    def test_set_on_continue_handler(self):
        decorated_handler = action(mock.MagicMock())
        on_continue_handler = mock.MagicMock()

        result = decorated_handler.on_continue(on_continue_handler)

        self.assertEqual(result, on_continue_handler)
        self.assertEqual(decorated_handler.on_continue_handler, on_continue_handler)

    def test_run_handler(self):
        handler = mock.MagicMock()
        decorated_handler = action(handler)
        job_id, event = self.get_event()

        decorated_handler(event, None)

        self.assertActionSuccessful(job_id)
        self.assertEqual(handler.call_count, 1)

    def test_call_continue_later(self):
        token = {'sample': 'token'}
        handler = mock.MagicMock(side_effect=ContinueLater(**token))
        decorated_handler = action(handler)
        job_id, event = self.get_event()

        decorated_handler(event, None)

        self.assertActionSuccessful(job_id)
        self.assertContinuationTokenEqual(token)

    def test_run_continuation_handler(self):
        handler = mock.MagicMock()
        decorated_handler = action(handler)
        continuation_handler = mock.MagicMock()
        decorated_handler.on_continue(continuation_handler)
        token = {'sample': 'token'}
        job_id, event = self.get_event(token=token)

        decorated_handler(event, None)

        self.assertActionSuccessful(job_id)
        self.assertEqual(continuation_handler.call_count, 1)
        self.assertEqual(handler.call_count, 0)

    def test_call_fail(self):
        handler = mock.MagicMock(side_effect=Exception)
        decorated_handler = action(handler)
        job_id, event = self.get_event()

        decorated_handler(event, None)

        self.assertActionFailed(job_id)
        self.assertFailureMessageRegex('Action failed due to exception')
