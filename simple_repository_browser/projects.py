import typing

from acc_py_index import utils
from acc_py_index.simple import model
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version


def get_releases(
    project_page: model.ProjectDetail,
) -> dict[Version, tuple[model.File, ...]]:
    result: dict[Version, list[model.File]] = {}
    canonical_name = canonicalize_name(project_page.name)
    for file in project_page.files:
        try:
            release = Version(
                version=utils.extract_package_version(
                    filename=file.filename,
                    project_name=canonical_name,
                ),
            )
        except (ValueError, InvalidVersion):
            release = Version('0.0rc0')
        result.setdefault(release, []).append(file)
    return {
        version: tuple(files) for version, files in result.items()
    }


def get_latest_version(
    versions: typing.Iterable[Version],
) -> typing.Optional[Version]:
    # Use the pip logic to determine the latest release. First, pick the greatest non-dev version,
    # and if nothing, fall back to the greatest dev version. If no release is available return None.
    sorted_versions = sorted(versions)
    if not sorted_versions:
        return None
    for version in sorted_versions[::-1]:
        if not (version.is_devrelease or version.is_prerelease):
            return version
    return sorted_versions[-1]
