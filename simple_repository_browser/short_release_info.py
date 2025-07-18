import dataclasses
from datetime import datetime
import types
import typing

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
    labels: typing.Mapping[
        str, typing.Annotated[str, "reason"]
    ]  # A mapping between labels (yank, partial-yank, quarantined, latest-release, etc.) to a reason for that label.


class ReleaseInfoModel:
    @classmethod
    def _group_files_by_version(
        cls, project_detail: model.ProjectDetail
    ) -> dict[Version, list[model.File]]:
        """Group files by version, handling version extraction and validation."""
        files_grouped_by_version: dict[Version, list[model.File]] = {}

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
                release = Version("0.0rc0")
            files_grouped_by_version.setdefault(release, []).append(file)

        # Ensure there is a release for each version, even if there is no files for it.
        for version_str in project_detail.versions or []:
            files_grouped_by_version.setdefault(Version(version_str), [])

        return files_grouped_by_version

    @classmethod
    def _process_quarantined_files(
        cls,
        project_detail: model.ProjectDetail,
        files_grouped_by_version: dict[Version, list[model.File]],
    ) -> dict[Version, list[typing.Dict[str, typing.Any]]]:
        """Process quarantined files metadata and group by version."""
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

        quarantined_files_by_release: dict[Version, list[Quarantinefile]] = {}
        canonical_name = canonicalize_name(project_detail.name)
        date_format = "%Y-%m-%dT%H:%M:%SZ"

        for file_info in quarantined_files:
            quarantined_file: Quarantinefile = {
                "filename": file_info["filename"],
                "quarantine_release_time": datetime.strptime(
                    file_info["quarantine_release_time"], date_format
                ),
                "upload_time": datetime.strptime(file_info["upload_time"], date_format),
            }
            release = Version(
                extract_package_version(
                    filename=quarantined_file["filename"],
                    project_name=canonical_name,
                ),
            )
            quarantined_files_by_release.setdefault(release, []).append(
                quarantined_file
            )
            # Make sure there is a record for this release, even if there are no files.
            files_grouped_by_version.setdefault(release, [])

        return quarantined_files_by_release

    @classmethod
    def _compute_yank_labels(cls, files: list[model.File]) -> dict[str, str]:
        """Compute yank-related labels for a release."""
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
            labels["yanked"] = ". ".join(yank_reasons or ["No yank reasons given"])

        return labels

    @classmethod
    def _compute_quarantine_labels(
        cls, quarantined_files_for_release: list[typing.Dict[str, typing.Any]]
    ) -> tuple[dict[str, str], list[datetime]]:
        """Compute quarantine-related labels and upload times."""
        labels = {}
        upload_times = []

        if quarantined_files_for_release:
            quarantine_release_times = [
                file["quarantine_release_time"]
                for file in quarantined_files_for_release
            ]
            quarantine_release_time = min(quarantine_release_times)
            upload_times = [
                file["upload_time"] for file in quarantined_files_for_release
            ]
            labels["quarantined"] = (
                f"Release quarantined. Available from {quarantine_release_time}"
            )

        return labels, upload_times

    @classmethod
    def _compute_upload_times(
        cls, files: list[model.File], quarantine_upload_times: list[datetime]
    ) -> list[datetime]:
        """Compute upload times from files and quarantined files."""
        upload_times: list[datetime] = [
            file.upload_time for file in files if file.upload_time is not None
        ]

        # When computing the release time, take into account quarantined files.
        if not upload_times and quarantine_upload_times:
            upload_times = quarantine_upload_times

        return upload_times

    @classmethod
    def _compute_release_labels(
        cls,
        version: Version,
        files: list[model.File],
        quarantined_files_for_release: list[typing.Dict[str, typing.Any]],
        latest_version: Version,
    ) -> dict[str, str]:
        """Compute all labels for a release version."""
        labels = {}

        # Add yank labels
        labels.update(cls._compute_yank_labels(files))

        # Add quarantine labels
        quarantine_labels, _ = cls._compute_quarantine_labels(
            quarantined_files_for_release
        )
        labels.update(quarantine_labels)

        # Add latest release label
        if version == latest_version:
            labels["latest-release"] = ""

        return labels

    @classmethod
    def release_infos(
        cls, project_detail: model.ProjectDetail
    ) -> tuple[dict[Version, ShortReleaseInfo], Version]:
        """Generate release information for all versions in a project."""
        files_grouped_by_version = cls._group_files_by_version(project_detail)
        quarantined_files_by_release = cls._process_quarantined_files(
            project_detail, files_grouped_by_version
        )
        latest_version = cls.compute_latest_version(files_grouped_by_version)

        result: dict[Version, ShortReleaseInfo] = {}

        for version, files in sorted(files_grouped_by_version.items()):
            quarantined_files_for_release = quarantined_files_by_release.get(
                version, []
            )

            # Compute labels for this release
            labels = cls._compute_release_labels(
                version, files, quarantined_files_for_release, latest_version
            )

            # Compute upload times
            _, quarantine_upload_times = cls._compute_quarantine_labels(
                quarantined_files_for_release
            )
            upload_times = cls._compute_upload_times(files, quarantine_upload_times)

            # Determine release date
            earliest_release_date = min(upload_times) if upload_times else None

            result[version] = ShortReleaseInfo(
                version=version,
                files=tuple(files),
                release_date=earliest_release_date,
                labels=types.MappingProxyType(labels),
            )

        return result, latest_version

    @classmethod
    def compute_latest_version(
        cls, versions: dict[Version, list[typing.Any]]
    ) -> Version:
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
