# Copyright (C) 2023, CERN
# This software is distributed under the terms of the MIT
# licence, copied verbatim in the file "LICENSE".
# In applying this license, CERN does not waive the privileges and immunities
# granted to it by virtue of its status as Intergovernmental Organization
# or submit itself to any jurisdiction.

from pathlib import Path

from setuptools import find_packages, setup

HERE = Path(__file__).parent.absolute()
with (HERE / 'README.md').open('rt') as fh:
    LONG_DESCRIPTION = fh.read().strip()


setup(
    name='simple-repository-browser',

    author='BE-CSS-SET, CERN',
    description='A frontend for a simple python package index',
    long_description=LONG_DESCRIPTION,
    long_description_content_type='text/markdown',
    url='',
    packages=find_packages(),
    python_requires='~=3.9',
    classifiers=[
        "Programming Language :: Python :: 3",
        "Operating System :: OS Independent",
    ],
    # include_package_data=True,
    package_data={
        '': [
            'static/*/*',
            'static/*',
            'templates/*',
            'templates/base/*',
        ],
    },
    install_requires=[
        'simple-repository',
        'aiohttp',
        'bleach',
        'diskcache',
        'docutils',
        'fastapi',
        'fastapi-utils',
        'importlib_metadata>=6.0',
        'jinja2',
        'markdown',
        'packaging',
        'parsley',
        'pkginfo',
        'pypi_simple>=1.0',
        'readme-renderer[md]',
        'uvicorn',
    ],
    extras_require={
        'dev': [
            'build',
            'pre-commit',
        ],
    },
    entry_points={
        'console_scripts': [
            'simple-repository-browser = simple_repository_browser.__main__:main',
        ],
    },
)
