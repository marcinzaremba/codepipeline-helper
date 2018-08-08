import unittest

from . import IntegrationTestCase

from codepipeline_helper import action


class TestIntegration(IntegrationTestCase):
    def test_basic(self):
        @action
        def handler(input_artifacts, output_artifacts, params):
            pass

        self.start_pipeline_execution(handler, {})

        self.assertPipelineExecutionSucceeded()
