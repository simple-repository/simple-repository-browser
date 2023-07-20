"""
setup.py for pypi-frontend.

For reference see
https://packaging.python.org/guides/distributing-packages-using-setuptools/

"""
from pathlib import Path

from setuptools import find_packages, setup

HERE = Path(__file__).parent.absolute()
with (HERE / 'README.md').open('rt') as fh:
    LONG_DESCRIPTION = fh.read().strip()


REQUIREMENTS: dict = {
    'core': [
        'acc-py-index~=3.0',
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
    'test': [
        'pytest',
    ],
    'dev': [
        'build',
        'pre-commit',
    ],
    'doc': [
        'sphinx',
        'acc-py-sphinx',
    ],
}


setup(
    name='simple-repository-browser',

    author='Phil Elson',
    author_email='philip.elson@cern.ch',
    description='A web application for a browsing a Python PEP-503 simple repository',
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

    install_requires=REQUIREMENTS['core'],
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
        # The 'all' extra is the union of all requirements.
        'all': [req for reqs in REQUIREMENTS.values() for req in reqs],
    },
)
