# Copyright (C) 2023, CERN
# This software is distributed under the terms of the MIT
# licence, copied verbatim in the file "LICENSE".
# In applying this license, CERN does not waive the privileges and immunities
# granted to it by virtue of its status as Intergovernmental Organization
# or submit itself to any jurisdiction.

import typing

from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version
from simple_repository import model
from simple_repository.packaging import extract_package_version


def get_releases(
    project_page: model.ProjectDetail,
) -> dict[Version, tuple[model.File, ...]]:
    result: dict[Version, list[model.File]] = {}
    canonical_name = canonicalize_name(project_page.name)
    for file in project_page.files:
        try:
            release = Version(
                version=extract_package_version(
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
