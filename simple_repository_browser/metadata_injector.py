from dataclasses import replace
import pathlib
import tarfile
import zipfile

from simple_repository import model
from simple_repository.components.metadata_injector import MetadataInjectorRepository


def get_metadata_from_sdist(package_path: pathlib.Path) -> str:
    archive = tarfile.TarFile.open(package_path)
    names = archive.getnames()

    pkg_info_files = [x.split('/') for x in names if 'PKG-INFO' in x]
    ordered_pkg_info = sorted(pkg_info_files, key=lambda pth: -len(pth))

    for path in ordered_pkg_info:
        candidate = '/'.join(path)
        f = archive.extractfile(candidate)
        if f is None:
            continue
        data = f.read().decode()
        if 'Metadata-Version' in data:
            return data
    raise ValueError(f"No metadata found in {package_path.name}")


def get_metadata_from_zip(package_path: pathlib.Path) -> str:
    # Used by pyreadline. (a zipfile)
    with zipfile.ZipFile(package_path) as archive:
        names = archive.namelist()

        pkg_info_files = [x.split('/') for x in names if 'PKG-INFO' in x]
        ordered_pkg_info = sorted(pkg_info_files, key=lambda pth: -len(pth))

        for path in ordered_pkg_info:
            candidate = '/'.join(path)
            f = archive.open(candidate, mode='r')
            if f is None:
                continue
            data = f.read().decode()
            if 'Metadata-Version' in data:
                return data
        raise ValueError(f"No metadata found in {package_path.name}")


class MetadataInjector(MetadataInjectorRepository):
    def _get_metadata_from_package(self, package_path: pathlib.Path) -> str:
        if package_path.name.endswith('.whl'):
            return self._get_metadata_from_wheel(package_path)
        elif package_path.name.endswith('.tar.gz'):
            return get_metadata_from_sdist(package_path)
        elif package_path.name.endswith('.zip'):
            return get_metadata_from_zip(package_path)
        raise ValueError("Package provided is not a wheel")

    def _add_metadata_attribute(
        self,
        project_page: model.ProjectDetail,
    ) -> model.ProjectDetail:
        """Add the data-core-metadata to all the packages distributed as wheels"""
        files = []
        for file in project_page.files:
            if file.url and not file.dist_info_metadata:
                file = replace(file, dist_info_metadata=True)
            files.append(file)
        project_page = replace(project_page, files=tuple(files))
        return project_page
