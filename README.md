# codepipeline-helper

Small Python library that simplifies writing AWS Lambda functions which are a part of AWS CodePipeline pipelines.

Simply: CodePipeline Lambda functions for Humans.

## tl;dr

So your Lambda function can look like:

```python
from typing import Dict, Optional

from codepipeline_helper import action, Artifact, ContinueLater


@action
def handler(
    params: Dict[str, str],
    input_artifacts: Dict[str, Artifact],
    output_artifacts: Dict[str, Artifact],
    token: Optional[Dict],
):
    times = int(params['times'])
    if token:
        result = token['result']
    else:
        initial = int(params['initial'])
        result = initial

    if result > times:
        output_artifacts['MyArtifact']['result'] = result
    else:
        raise ContinueLater(result=result + 1)
```

## Rationale

As a part of AWS CodePipeline CI/CD solution user can [invoke an arbitrary Python code using AWS Lambda functions](https://docs.aws.amazon.com/codepipeline/latest/userguide/actions-invoke-lambda-function.html). In addition to performing an actual job, function is responsible for following tasks:

- parsing given input (multi-level Python dictionary which can be different depending on context),
- informing AWS CodePipeline via API of function's processing result,
- finding artifact paths by name,
- downloading/uploading pipeline's artifacts stored in dedicated AWS S3 bucket with given credentials and proper encryption settings,
- ....

It results in bulky Lambda code copy-pasted from one function to another where the most of it has auxiliary nature. This library tries to solve the problem by providing all of these features in one simple, tested module and requires the user to do one thing only: write actual code that matters. 