# Copyright (C) 2023, CERN
# This software is distributed under the terms of the MIT
# licence, copied verbatim in the file "LICENSE".
# In applying this license, CERN does not waive the privileges and immunities
# granted to it by virtue of its status as Intergovernmental Organization
# or submit itself to any jurisdiction.

from pathlib import Path

from setuptools import setup

HERE = Path(__file__).parent.absolute()
with (HERE / 'README.md').open('rt') as fh:
    LONG_DESCRIPTION = fh.read().strip()


REQUIREMENTS: dict = {
    'core': [
        'aiohttp',
        'aiosqlite',
        'diskcache',
        'docutils',
        'fastapi',
        'importlib_metadata>=6.0',
        'jinja2',
        'markdown',
        'markupsafe',
        'packaging',
        'parsley',
        'pkginfo',
        'readme-renderer[md]',
        'simple-repository',
        'uvicorn',
    ],
    'test': [
        'pytest',
    ],
    'dev': [
        'build',
        'pre-commit',
    ],
}


setup(
    name='simple-repository-browser',

    author="CERN, BE-CSS-SET",
    description='A web interface to browse and search packages in any simple package repository (PEP-503), inspired by PyPI / warehouse',
    long_description=LONG_DESCRIPTION,
    long_description_content_type='text/markdown',
    url="https://github.com/simple-repository/simple-repository-browser",

    packages=['simple_repository_browser'],
    python_requires='~=3.11',
    classifiers=[
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
    ],
    package_data={
        '': [
            'static/*/*',
            'static/*',
            'templates/*',
            'templates/base/*',
        ],
    },

    install_requires=REQUIREMENTS.pop('core'),
    entry_points={
        'console_scripts': [
            'simple-repository-browser = simple_repository_browser.__main__:main',
        ],
    },
    extras_require={
        **REQUIREMENTS,
        # The 'dev' extra is the union of 'test' and 'doc', with an option
        # to have explicit development dependencies listed.
        'dev': [
            req
            for extra in ['dev', 'test', 'doc']
            for req in REQUIREMENTS.get(extra, [])
        ],
    },
)
