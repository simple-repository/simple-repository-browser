import dataclasses
from datetime import datetime, timezone
import functools
import types
import typing

from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion as InvalidVersionError
from packaging.version import Version
from simple_repository import model
from simple_repository.packaging import extract_package_version


@functools.total_ordering
class InvalidVersion:
    """Represents a version string that doesn't conform to PEP 440."""

    def __init__(self, version_string: str = "unknown"):
        self._version_string = version_string

    def __str__(self):
        return self._version_string

    def __repr__(self):
        return f"InvalidVersion({self._version_string!r})"

    def __hash__(self):
        return hash(("invalid-version", self._version_string))

    def __eq__(self, other):
        return (
            isinstance(other, InvalidVersion)
            and self._version_string == other._version_string
        )

    def __lt__(self, other):
        # Sort invalid versions to the beginning (before all real versions)
        # so they won't be selected as the latest version
        if isinstance(other, InvalidVersion):
            return self._version_string < other._version_string
        return True

    @property
    def is_prerelease(self):
        return False

    @property
    def is_devrelease(self):
        return False


@dataclasses.dataclass(frozen=True)
class ShortReleaseInfo:
    # A short representation of a release. Intended to be lightweight to compute,
    # such that many ShortReleaseInfo instances can be provided to a view.
    version: Version | InvalidVersion
    files: tuple[model.File, ...]
    release_date: datetime | None
    labels: typing.Mapping[
        str, typing.Annotated[str, "reason"]
    ]  # A mapping between labels (yank, partial-yank, quarantined, latest-release, etc.) to a reason for that label.


class ReleaseInfoModel:
    @classmethod
    def release_infos(
        cls, project_detail: model.ProjectDetail
    ) -> tuple[
        dict[Version | InvalidVersion, ShortReleaseInfo], Version | InvalidVersion
    ]:
        files_grouped_by_version: dict[Version | InvalidVersion, list[model.File]] = {}

        if not project_detail.files:
            raise ValueError("No files for the release")

        canonical_name = canonicalize_name(project_detail.name)
        release: Version | InvalidVersion
        for file in project_detail.files:
            version_str = None
            try:
                version_str = extract_package_version(
                    filename=file.filename,
                    project_name=canonical_name,
                )
                release = Version(version=version_str)
            except (ValueError, InvalidVersionError):
                # Use the extracted version_str if available, otherwise the filename
                release = InvalidVersion(version_str or file.filename)
            files_grouped_by_version.setdefault(release, []).append(file)

        # Ensure there is a release for each version, even if there is no files for it.
        version: Version | InvalidVersion
        for version_str in project_detail.versions or []:
            try:
                version = Version(version_str)
            except (ValueError, InvalidVersionError):
                version = InvalidVersion(version_str)
            files_grouped_by_version.setdefault(version, [])

        result: dict[Version | InvalidVersion, ShortReleaseInfo] = {}

        latest_version = cls.compute_latest_version(files_grouped_by_version)

        if typing.TYPE_CHECKING:
            RawQuarantinefile = typing.TypedDict(
                "RawQuarantinefile",
                {
                    "filename": str,
                    "quarantine_release_time": str,
                    "upload_time": str,
                },
            )
            Quarantinefile = typing.TypedDict(
                "Quarantinefile",
                {
                    "filename": str,
                    "quarantine_release_time": datetime,
                    "upload_time": datetime,
                },
            )

        quarantined_files: list[RawQuarantinefile] = (
            typing.cast(
                typing.Any, project_detail.private_metadata.get("_quarantined_files")
            )
            or []
        )

        quarantined_files_by_release: dict[
            Version | InvalidVersion, list[Quarantinefile]
        ] = {}

        date_format = "%Y-%m-%dT%H:%M:%SZ"
        for file_info in quarantined_files:
            quarantined_file: Quarantinefile = {
                "filename": file_info["filename"],
                "quarantine_release_time": datetime.strptime(
                    file_info["quarantine_release_time"],
                    date_format,
                ).replace(tzinfo=timezone.utc),
                "upload_time": datetime.strptime(
                    file_info["upload_time"], date_format
                ).replace(tzinfo=timezone.utc),
            }
            version_str = None
            try:
                version_str = extract_package_version(
                    filename=quarantined_file["filename"],
                    project_name=canonical_name,
                )
                release = Version(version_str)
            except (ValueError, InvalidVersionError):
                # Use the extracted version_str if available, otherwise the filename
                release = InvalidVersion(version_str or quarantined_file["filename"])
            quarantined_files_by_release.setdefault(release, []).append(
                quarantined_file
            )
            # Make sure there is a record for this release, even if there are no files.
            files_grouped_by_version.setdefault(release, [])

        for version, files in sorted(files_grouped_by_version.items()):
            quarantined_files_for_release = quarantined_files_by_release.get(
                version, []
            )

            upload_times: list[datetime] = [
                file.upload_time for file in files if file.upload_time is not None
            ]

            labels = {}

            yanked_files = 0
            not_yanked_files = 0
            yank_reasons = set()
            for file in files:
                if file.yanked:
                    yanked_files += 1
                    if isinstance(file.yanked, str):
                        yank_reasons.add(file.yanked)
                else:
                    not_yanked_files += 1
            if yanked_files > 0 and not_yanked_files > 0:
                labels["partial-yank"] = "Partially yanked"
            elif yanked_files > 0 and not_yanked_files == 0:
                yank_reasons_len = len(yank_reasons)
                if yank_reasons_len == 1:
                    labels["yanked"] = next(iter(yank_reasons))
                elif yank_reasons_len > 1:
                    labels["yanked"] = (
                        "Yanked for multiple reasons, see individual files for details"
                    )
                else:
                    labels["yanked"] = "No yank reasons given"

            if quarantined_files_for_release:
                quarantine_release_times = [
                    file["quarantine_release_time"]
                    for file in quarantined_files_for_release
                ]
                quarantine_release_time = min(quarantine_release_times)
                # When computing the release time, take into account quarantined files.
                if not upload_times:
                    upload_times = [
                        file["upload_time"] for file in quarantined_files_for_release
                    ]
                labels["quarantined"] = (
                    f"Release quarantined. Available from {quarantine_release_time}"
                )

            if version == latest_version:
                labels["latest-release"] = ""

            if upload_times:
                earliest_release_date = min(upload_times)
            else:
                earliest_release_date = None

            result[version] = ShortReleaseInfo(
                version=version,
                files=tuple(files),
                release_date=earliest_release_date,
                labels=types.MappingProxyType(labels),
            )

        return result, latest_version

    @classmethod
    def compute_latest_version(
        cls, versions: dict[Version | InvalidVersion, list[typing.Any]]
    ) -> Version | InvalidVersion:
        # Use the pip logic to determine the latest release. First, pick the greatest non-dev version,
        # and if nothing, fall back to the greatest dev version. If no release is available return None.
        sorted_versions = sorted(
            versions,
            key=lambda version: (
                # Prioritise the releases with files (e.g. not quarantined).
                len(versions[version]) > 0,
                # Then, put the non dev-releases first.
                not version.is_devrelease and not version.is_prerelease,
                # Finally, order by the version.
                version,
            ),
        )
        return sorted_versions[-1]
