# Copyright (C) 2023, CERN
# This software is distributed under the terms of the MIT
# licence, copied verbatim in the file "LICENSE".
# In applying this license, CERN does not waive the privileges and immunities
# granted to it by virtue of its status as Intergovernmental Organization
# or submit itself to any jurisdiction.

import base64
import datetime
import pathlib
import pickle
import tarfile
import tempfile
import typing
import zipfile
from dataclasses import replace
from pathlib import Path

import aiohttp
from simple_repository import errors, model, utils
from simple_repository.components.metadata_injector import \
    MetadataInjectorRepository

ResourceHeaders = typing.TypedDict('ResourceHeaders', {'creation-date': datetime.datetime}, total=False)


class MetadataInjector(MetadataInjectorRepository):
    async def get_project_page(
        self,
        project_name: str,
        *,
        request_context: model.RequestContext = model.RequestContext.DEFAULT,
    ) -> model.ProjectDetail:
        project_page = await super().get_project_page(project_name, request_context=request_context)

        files_changed = False
        files = []
        for file in project_page.files:
            if file.url and file.filename.endswith(".tar.gz") and not file.dist_info_metadata:
                file = replace(file, dist_info_metadata=True)
                files_changed = True

            if file.url and file.filename.endswith(".whl") and not file.dist_info_metadata:
                file = replace(file, dist_info_metadata=True)
                files_changed = True
            if file.url and file.filename.endswith(".zip") and not file.dist_info_metadata:
                file = replace(file, dist_info_metadata=True)
                files_changed = True
            files.append(file)
        if files_changed:
            project_page = replace(project_page, files=tuple(files))
        return project_page

    async def get_resource(
        self,
        project_name: str,
        resource_name: str,
        *,
        request_context: model.RequestContext = model.RequestContext.DEFAULT,
    ) -> model.Resource:

        try:
            # Attempt to get the resource from upstream.
            return await super().get_resource(project_name, resource_name, request_context=request_context)
        except errors.ResourceUnavailable:
            if not resource_name.endswith(".metadata"):
                # If we tried to get a resource that wasn't a .metadata one, and it failed,
                # propagate the error.
                raise

        # The resource doesn't exist upstream, and looks like a metadata file has been
        # requested. Let's try to fetch the underlying resource and compute the metadata.

        # Give the cache-key a unique name, to avoid colliding with the cache from other components
        # (such as MetadataInjectorRepository)
        cache_key = f'MetadataInjector__{project_name}/{resource_name}'

        # First, let's attempt to get the metadata out of the cache.
        encoded_metadata = await self._cache.get(cache_key)
        if encoded_metadata:
            decoded_metadata = pickle.loads(base64.b64decode(encoded_metadata.encode('ascii')))
            metadata = decoded_metadata['body']
            headers = decoded_metadata['headers']

        else:
            # Get hold of the actual artefact from which we want to extract
            # the metadata.
            # FIXME: We should be calling the root of the repository here.
            #  We can't do that until we have context though (currently only on master).
            resource = await super().get_resource(
                project_name, resource_name.removesuffix(".metadata"),
            )
            if isinstance(resource, model.HttpResource):
                try:
                    metadata, headers = await self.download_metadata(
                        package_name=resource_name.removesuffix(".metadata"),
                        download_url=resource.url,
                        session=self._session,
                    )
                except ValueError as e:
                    # If we can't get hold of the metadata from the file then raise
                    # a resource unavailable.
                    raise errors.ResourceUnavailable(resource_name) from e
            elif isinstance(resource, model.LocalResource):
                try:
                    metadata, headers = self.metadata_from_package(resource.path)
                except ValueError as e:
                    raise errors.ResourceUnavailable(resource_name) from e
            else:
                raise errors.ResourceUnavailable(
                    resource_name.removesuffix(".metadata"),
                    "Unable to fetch the resource needed to extract the metadata.",
                )

            # Cache the result for a faster response in the future.
            encoded_metadata = pickle.dumps({'headers': headers, 'body': metadata})
            await self._cache.set(cache_key, base64.b64encode(encoded_metadata).decode('ascii'))

        result = model.TextResource(text=metadata)
        result.context.update(headers)
        return result

    async def download_metadata(
            self,
            package_name: str,
            download_url: str,
            session: aiohttp.ClientSession,
    ) -> tuple[str, ResourceHeaders]:
        with tempfile.TemporaryDirectory() as tmpdir:
            pkg_path = pathlib.Path(tmpdir) / package_name
            await utils.download_file(download_url, pkg_path, session)
            return self.metadata_from_package(pkg_path)

    def metadata_from_package(self, path: Path) -> tuple[str, ResourceHeaders]:
        return get_metadata_from_package(path)


def get_metadata_from_package(package_path: pathlib.Path) -> tuple[str, ResourceHeaders]:
    if package_path.name.endswith('.whl'):
        return get_metadata_from_wheel(package_path)
    elif package_path.name.endswith('.tar.gz'):
        return get_metadata_from_sdist(package_path)
    elif package_path.name.endswith('.zip'):
        return get_metadata_from_zip(package_path)
    raise ValueError("Package provided is not a wheel or an sdist")


def get_metadata_from_wheel(package_path: pathlib.Path) -> tuple[str, ResourceHeaders]:
    package_tokens = package_path.name.split('-')
    if len(package_tokens) < 2:
        raise ValueError(
            f"Filename {package_path.name} is not normalized according to PEP-427",
        )
    name_ver = package_tokens[0] + '-' + package_tokens[1]

    with zipfile.ZipFile(package_path, 'r') as ziparchive:
        meta_zip_path = name_ver + ".dist-info/METADATA"
        try:
            info = ziparchive.getinfo(meta_zip_path)
            return (
                ziparchive.read(meta_zip_path).decode(),
                {'creation-date': datetime.datetime(*info.date_time)},
            )
        except KeyError as e:
            raise errors.InvalidPackageError(
                "Provided wheel doesn't contain a metadata file.",
            ) from e


def get_metadata_from_sdist(package_path: pathlib.Path) -> tuple[str, ResourceHeaders]:
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
            info = archive.getmember(candidate)
            metadata: ResourceHeaders = {'creation-date': datetime.datetime.fromtimestamp(info.mtime)}
            return data, metadata
    raise ValueError(f"No metadata found in {package_path.name}")


def get_metadata_from_zip(package_path: pathlib.Path) -> tuple[str, ResourceHeaders]:
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
                info = archive.getinfo(candidate)
                metadata: ResourceHeaders = {'creation-date': datetime.datetime(*info.date_time)}
                return data, metadata
        raise ValueError(f"No metadata found in {package_path.name}")
