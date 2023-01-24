import typing
from itertools import groupby

import packaging.version
import pypi_simple.client
from pypi_simple import PyPISimple


class PackageName(str):
    @property
    def normalized(self) -> "PackageName":
        # As per PEP 503 (without the regex)
        return PackageName(str(self).lower().replace('.', '-').replace('_', '-'))


class PackageNotFound(Exception):
    pass


class ProjectFile:
    """
    Represents a single file with a version.

    There can be many files in a release.

    """
    def __init__(self, url='', version='', filename=''):
        self.url = url
        self.version = version
        self.filename = filename

    def __repr__(self):
        return f'{self.__class__.__name__}(url={self.url}, version={self.version}, filename={self.filename})'

    def __eq__(self, other):
        if not isinstance(other, ProjectFile):
            return NotImplemented
        return (self.url, self.version, self.filename) == (other.url, other.version, other.filename)


class ProjectRelease:
    """
    Represents a specific version of a project.

    A release can have multiple files.

    """
    def __init__(self, version: str = '', files: typing.Tuple[ProjectFile, ...] = ()):
        self.version = version
        self._files = files

    def files(self) -> typing.Tuple[ProjectFile, ...]:
        return self._files

    @classmethod
    def build_from_files(cls, files: typing.Tuple[ProjectFile, ...]) -> typing.Tuple["ProjectRelease", ...]:
        versions: typing.Dict[str, typing.List[ProjectFile]] = {}
        for k, g in groupby(files, lambda file: file.version):
            versions.setdefault(k, []).extend(list(g))
        releases = []
        for version, version_files in versions.items():
            releases.append(cls(version, tuple(version_files)))
        return tuple(releases)

    def __repr__(self):
        return f'{self.__class__.__name__}(version={repr(self.version)}, files={repr(self.files())}'

    def __eq__(self, other):
        if not isinstance(other, ProjectRelease):
            return NotImplemented
        return (self.version, self.files()) == (other.version, other.files())


def safe_version(version_str) -> packaging.version.Version:
    try:
        # Seen with pyserial and "pyserial-py3k-2.5.win32.exe"
        return packaging.version.parse(version_str)
    except packaging.version.InvalidVersion:
        return packaging.version.parse('0.0rc0')


class Project:
    """
    Represents a Python "project" such as numpy or matplotlib.

    A project contains multiple releases.

    """
    def __init__(self, name: PackageName, releases: typing.Tuple[ProjectRelease, ...]):
        self.name = name

        if not releases:
            raise ValueError(f"Project {name} has no releases")

        self._releases = tuple(
            sorted(
                releases,
                key=lambda release: safe_version(release.version),
            ),
        )

    def releases(self) -> typing.Tuple[ProjectRelease, ...]:
        return self._releases

    def latest_release(self):
        # Use the pip logic to determine the latest release. First, pick the greatest non-dev version,
        # and if nothing, fall back to the greatest dev version.
        for release in self._releases[::-1]:
            vn = safe_version(release.version)
            if not (vn.is_devrelease or vn.is_prerelease):
                return release
        else:
            return self._releases[-1]

    def release(self, version: str) -> ProjectRelease:
        # Suboptimal default search.
        results = [release for release in self.releases() if release.version == version]
        if not results:
            # TODO: Better exception type.
            raise ValueError('No release found')
        assert len(results) == 1
        return results[0]

    def __repr__(self):
        return f'{self.__class__.__name__}(name={repr(self.name)}, releases={repr(self.releases())})'

    def __eq__(self, other):
        if not isinstance(other, Project):
            return NotImplemented
        return (self.name, self.releases()) == (other.name, other.releases())


class SimplePackageIndex:
    """A project index with data coming from a simple (PEP 503) source"""
    def __init__(self, source_url: str = 'https://pypi.org/simple'):
        self._source_url = source_url

    def project_names(self) -> typing.Tuple[PackageName, ...]:
        # TODO: Use code from grouping-service to allow (async) streaming of projects.
        simple = PyPISimple(self._source_url)
        result = []
        for name in simple.stream_project_names():
            result.append(PackageName(name))
        return tuple(result)

    def project(self, name: typing.Union[PackageName, str]) -> Project:
        if not isinstance(name, PackageName):
            name = PackageName(name)
        simple = PyPISimple(self._source_url)
        try:
            page = simple.get_project_page(name)
        except pypi_simple.client.NoSuchProjectError:
            # faulthandler (a test dependency of greenlet)
            page = None

        if page is None:
            raise PackageNotFound(name)

        return Project(
            name=name.normalized,  # We don't have the preferred name here.
            releases=ProjectRelease.build_from_files(
                tuple(
                    ProjectFile(
                        pkg.url,
                        pkg.version or '0.0dev0',  # Seen with pyreadline and vme-boards
                        pkg.filename,
                    ) for pkg in page.packages

                ),
            ),
        )
