from setuptools import setup

setup(
    name='codepipeline-helper',
    author='Marcin Zaremba',
    py_modules=['codepipeline_helper'],
    install_requires=['boto3'],
    extras_require={
        'dev': [
            'flake8',
        ]
    },
    test_suite='tests',
)
