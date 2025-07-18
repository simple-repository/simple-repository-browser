"""
Extended MetadataInjector that supports sdist (.tar.gz) and zip (.zip) formats.

This extends SimpleRepository's MetadataInjectorRepository to provide metadata extraction
for package formats beyond wheels.

"""

from dataclasses import replace
import pathlib
import tarfile
import typing
import zipfile

from simple_repository import model
from simple_repository.components.metadata_injector import MetadataInjectorRepository


def _extract_pkg_info_from_archive(
    archive_names: typing.List[str],
    extract_func: typing.Callable[[str], typing.Optional[typing.IO[bytes]]],
    package_name: str,
) -> str:
    """
    Extract PKG-INFO metadata from an archive.

    Args:
        archive_names: List of file names in the archive
        extract_func: Function to extract a file from the archive
        package_name: Name of the package for error messages

    Returns:
        Metadata content as string

    Raises:
        ValueError: If no valid metadata is found
    """
    pkg_info_files = [x.split("/") for x in archive_names if "PKG-INFO" in x]
    # Sort by path length (descending) to prefer more specific/nested metadata files
    ordered_pkg_info = sorted(pkg_info_files, key=lambda pth: -len(pth))

    for path in ordered_pkg_info:
        candidate = "/".join(path)
        f = extract_func(candidate)
        if f is None:
            continue
        try:
            data = f.read().decode("utf-8")
            if "Metadata-Version" in data:
                return data
        except (UnicodeDecodeError, OSError):
            # Skip files that can't be decoded or read
            continue

    raise ValueError(f"No valid PKG-INFO metadata found in {package_name}")


def get_metadata_from_sdist(package_path: pathlib.Path) -> str:
    """Extract metadata from a source distribution (.tar.gz file)."""
    with tarfile.TarFile.open(package_path) as archive:
        names = archive.getnames()

        def extract_func(candidate: str) -> typing.Optional[typing.IO[bytes]]:
            return archive.extractfile(candidate)

        return _extract_pkg_info_from_archive(names, extract_func, package_path.name)


def get_metadata_from_zip(package_path: pathlib.Path) -> str:
    """Extract metadata from a zip file (legacy format, used by packages like pyreadline)."""
    with zipfile.ZipFile(package_path) as archive:
        names = archive.namelist()

        def extract_func(candidate: str) -> typing.Optional[typing.IO[bytes]]:
            try:
                return archive.open(candidate, mode="r")
            except (KeyError, zipfile.BadZipFile):
                return None

        return _extract_pkg_info_from_archive(names, extract_func, package_path.name)


class MetadataInjector(MetadataInjectorRepository):
    """
    Extended MetadataInjector that supports multiple package formats.

    This class extends SimpleRepository's MetadataInjectorRepository to provide
    metadata extraction for:
    - Wheel files (.whl) - handled by parent class
    - Source distributions (.tar.gz) - contains PKG-INFO files
    - Zip files (.zip) - legacy format used by some packages
    """

    # Map of supported file extensions to their extraction functions
    _EXTRACTORS: typing.Dict[
        str, typing.Callable[["MetadataInjector", pathlib.Path], str]
    ] = {
        ".whl": lambda self, path: self._get_metadata_from_wheel(path),
        ".tar.gz": lambda self, path: get_metadata_from_sdist(path),
        ".zip": lambda self, path: get_metadata_from_zip(path),
    }

    def _get_metadata_from_package(self, package_path: pathlib.Path) -> str:
        """Extract metadata from a package file based on its extension."""
        package_name = package_path.name

        for extension, extractor in self._EXTRACTORS.items():
            if package_name.endswith(extension):
                return extractor(self, package_path)

        # Provide more descriptive error message
        supported_formats = ", ".join(self._EXTRACTORS.keys())
        raise ValueError(
            f"Unsupported package format: {package_name}. "
            f"Supported formats: {supported_formats}"
        )

    def _add_metadata_attribute(
        self,
        project_page: model.ProjectDetail,
    ) -> model.ProjectDetail:
        """
        Add the data-core-metadata attribute to all supported package files.

        Unlike the parent class which only adds metadata attributes to wheel files,
        this implementation adds them to all files with URLs, enabling metadata
        requests for sdist and zip files as well.
        """
        files = []
        for file in project_page.files:
            matching_extension = file.filename.endswith(tuple(self._EXTRACTORS.keys()))
            if matching_extension and not file.dist_info_metadata:
                file = replace(file, dist_info_metadata=True)
            files.append(file)
        return replace(project_page, files=tuple(files))
