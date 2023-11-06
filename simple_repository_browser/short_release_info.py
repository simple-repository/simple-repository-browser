# Copyright (C) 2023, CERN
# This software is distributed under the terms of the MIT
# licence, copied verbatim in the file "LICENSE".
# In applying this license, CERN does not waive the privileges and immunities
# granted to it by virtue of its status as Intergovernmental Organization
# or submit itself to any jurisdiction.

import dataclasses
import typing
from datetime import datetime

from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version
from simple_repository import model
from simple_repository.packaging import extract_package_version


@dataclasses.dataclass(frozen=True)
class ShortReleaseInfo:
    # A short representation of a release. Intended to be lightweight to compute,
    # such that many ShortReleaseInfo instances can be provided to a view.
    version: Version
    files: tuple[model.File, ...]
    release_date: datetime | None
    is_latest: bool
    yank_status: bool | typing.Literal['partial']


class ReleaseInfoModel:
    @classmethod
    def release_infos(cls, project_detail: model.ProjectDetail) -> tuple[dict[Version, ShortReleaseInfo], Version]:
        files_groued_by_version: dict[Version, list[model.File]] = {}

        if not project_detail.files:
            raise ValueError("No files for the release")

        canonical_name = canonicalize_name(project_detail.name)
        for file in project_detail.files:
            try:
                release = Version(
                    version=extract_package_version(
                        filename=file.filename,
                        project_name=canonical_name,
                    ),
                )
            except (ValueError, InvalidVersion):
                release = Version('0.0rc0')
            files_groued_by_version.setdefault(release, []).append(file)

        result: dict[Version, ShortReleaseInfo] = {}

        latest_version = cls.compute_latest_version(tuple(files_groued_by_version.keys()))

        for version, files in sorted(files_groued_by_version.items()):
            upload_times = [file.upload_time for file in files if file.upload_time]
            if upload_times:
                earliest_release_date = min(upload_times)
            else:
                earliest_release_date = None

            yankeds = [bool(file.yanked) for file in files]
            yank_status: bool | typing.Literal['partial'] = False
            if all(yankeds):
                yank_status = True
            elif any(yankeds):
                yank_status = 'partial'

            result[version] = ShortReleaseInfo(
                version=version,
                files=tuple(files),
                release_date=earliest_release_date,
                is_latest=(version == latest_version),
                yank_status=yank_status,
            )

        return result, latest_version

    @classmethod
    def compute_latest_version(cls, versions: tuple[Version, ...]) -> Version:
        # Use the pip logic to determine the latest release. First, pick the greatest non-dev version,
        # and if nothing, fall back to the greatest dev version. If no release is available return None.
        sorted_versions = sorted(versions)
        for version in sorted_versions[::-1]:
            if not version.is_devrelease and not version.is_prerelease:
                return version
        return sorted_versions[-1]
