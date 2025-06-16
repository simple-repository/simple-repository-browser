import asyncio
import dataclasses
import datetime
import email.parser
import email.policy
import logging
import os.path
import pathlib
import tempfile
import typing

import httpx
from packaging.requirements import InvalidRequirement
from packaging.requirements import Requirement as _PkgRequirement
import pkginfo
import readme_renderer.markdown
import readme_renderer.rst
import readme_renderer.txt
from simple_repository import SimpleRepository, model


@dataclasses.dataclass
class FileInfo:
    #: Size, in bytes, of the compressed file.
    size: int


class Requirement(_PkgRequirement):
    is_valid: bool = True


@dataclasses.dataclass(frozen=True)
class InvalidRequirementSpecification:
    spec: str
    is_valid: bool = dataclasses.field(init=False, default=False)


class RequirementsSequence(tuple[Requirement | InvalidRequirementSpecification]):
    def extras(self) -> set[str]:
        # Get all extras found in any of the contained requirements.
        _extras = set()
        for req in iter(self):
            if isinstance(req, Requirement):
                _extras.update(self.extras_for_requirement(req))
        return _extras

    @classmethod
    def extra_for_requirement(cls, requirement: Requirement) -> list[str] | None:
        extras = list(cls.extras_for_requirement(requirement))
        if extras:
            return extras
        else:
            return None

    @classmethod
    def discover_extra_markers(cls, ast) -> typing.Generator[str, None, None]:
        # Find all extra parts of the markers.
        if isinstance(ast, list) and len(ast) == 1:
            # https://github.com/pypa/packaging/blob/09f131b326453f18a217fe34f4f7a77603b545db/src/packaging/markers.py#L75
            yield from cls.discover_extra_markers(ast[0])
            return
        if isinstance(ast, list):
            if isinstance(ast[0], (list, tuple)):
                yield from cls.discover_extra_markers(ast[0])
            if isinstance(ast[2], (list, tuple)):
                yield from cls.discover_extra_markers(ast[2])
        elif isinstance(ast, tuple):
            lhs_v = getattr(ast[0], 'value', None)
            if lhs_v == 'extra':
                yield ast[2].value
            # Note: Technically, it is possible to build a '"foo" == extra' style
            #       marker. We don't bother with it though, since it isn't something
            #       that comes out of setuptools.
        else:
            raise ValueError(f"Unexpected ast component {ast}")

    @classmethod
    def extras_for_requirement(cls, requirement: Requirement) -> set[str]:
        req_marker = requirement.marker
        if req_marker:
            # Access the AST. Not yet a public API, see https://github.com/pypa/packaging/issues/448.
            markers_ast = req_marker._markers
            return set(list(cls.discover_extra_markers(markers_ast)))
        return set()


@dataclasses.dataclass
class PackageInfo:
    """Represents a simplified pkg-info/dist-info metadata, suitable for easy (and safe) use in html templates"""
    summary: str
    description: str  # This is HTML safe (rendered with readme_renderer).
    author: typing.Optional[str] = None
    maintainer: typing.Optional[str] = None
    classifiers: typing.Sequence[str] = ()
    project_urls: typing.Dict[str, str] = dataclasses.field(default_factory=dict)
    requires_python: typing.Optional[str] = None
    requires_dist: RequirementsSequence = RequirementsSequence()
    yanked: bool | str = False

    # A mapping of filename to FileInfo. This must only be used for sharing size information,
    # and will be removed once this code moves to a component based repository definition.
    files_info: dict[str, FileInfo] = dataclasses.field(default_factory=dict)


async def fetch_file(url, dest):
    async with httpx.AsyncClient(verify=False) as http_client:
        async with http_client.stream("GET", url) as r:
            try:
                r.raise_for_status()
            except httpx.HTTPError as err:
                raise IOError(f'Unable to fetch file (reason: { str(err) })')
            chunk_size = 1024 * 100
            with open(dest, 'wb') as fd:
                async for chunk in r.aiter_bytes(chunk_size):
                    fd.write(chunk)


class PkgInfoFromFile(pkginfo.Distribution):
    def __init__(self, filename: str):
        self._filename = filename
        self.extractMetadata()

    def read(self):
        content = pathlib.Path(self._filename).read_text()
        return content.encode()


async def package_info(
    release_files: tuple[model.File, ...],
    repository: SimpleRepository,
    project_name: str,
) -> tuple[model.File, PackageInfo]:
    files = sorted(
        release_files,
        key=lambda file: (
            not file.dist_info_metadata,  # Put those with dist info metadata first.
            not file.filename.endswith('.whl'),
            not file.filename.endswith('.tar.gz'),
            not file.filename.endswith('.zip'),
            file.upload_time,  # Distinguish conflicts by picking the earliest one.
        ),
    )

    files_info: typing.Dict[str, FileInfo] = {}

    # Get the size from the repository, if possible.
    for file in files:
        if file.size:
            files_info[file.filename] = FileInfo(
                size=file.size,
            )

    limited_concurrency = asyncio.Semaphore(10)
    # Compute the size of each file.
    # TODO: This should be done as part of the repository component interface.
    async with httpx.AsyncClient(verify=False) as http_client:
        async def semaphored_head(filename: str, url: str):
            async with limited_concurrency:
                headers: dict[str, str] = {}
                return (
                    filename,
                    await http_client.head(url, follow_redirects=True, headers=headers),
                )
        coros = [
            semaphored_head(file.filename, file.url)
            for file in files
            if file.filename not in files_info
        ]
        for coro in asyncio.as_completed(coros):
            filename, response = await coro
            files_info[filename] = FileInfo(
                size=int(response.headers['Content-Length']),
            )

    file = files[0]

    if file.dist_info_metadata:
        resource_name = file.filename + '.metadata'
    else:
        raise ValueError(f"Metadata not available for {file}")

    logging.debug(f'Downloading metadata for {file.filename} from {resource_name}')

    with tempfile.NamedTemporaryFile(
            suffix=os.path.splitext(file.filename)[1],
    ) as tmp:
        resource = await repository.get_resource(project_name, resource_name)

        if isinstance(resource, model.TextResource):
            tmp.write(resource.text.encode())
            if not file.upload_time:
                # If the repository doesn't provide information about the upload time, estimate
                # it from the headers of the resource, if they exist.
                if ct := resource.context.get('creation-date'):
                    if isinstance(ct, str):
                        file = dataclasses.replace(file, upload_time=datetime.datetime.fromisoformat(ct))
        elif isinstance(resource, model.HttpResource):
            await fetch_file(resource.url, tmp.name)
        else:
            raise ValueError(f"Unhandled resource type ({type(resource)})")

        tmp.flush()
        tmp.seek(0)
        info = PkgInfoFromFile(tmp.name)
        description = generate_safe_description_html(info)

        # If there is email information, but not a name in the "author" or "maintainer"
        # attribute, extract this information from the first person's email address.
        # Will take something like ``"Ivan" foo@example.com`` and extract the "Ivan" part.
        def extract_usernames(emails):
            names = []
            parsed = email.parser.Parser(policy=email.policy.default).parsestr(
                f'To: {info.author_email}',
            )
            for address in parsed['to'].addresses:
                names.append(address.display_name)
            return ', '.join(names)

        if not info.author and info.author_email:
            info.author = extract_usernames(info.author_email)

        if not info.maintainer and info.maintainer_email:
            info.maintainer = extract_usernames(info.maintainer_email)

        project_urls = {
            url.split(',')[0].strip().title(): url.split(',')[1].strip()
            for url in info.project_urls or []
        }
        # Ensure that a Homepage exists in the project urls
        if info.home_page and 'Homepage' not in project_urls:
            project_urls['Homepage'] = info.home_page

        sorted_urls = {
            name: url for name, url in sorted(
                project_urls.items(),
                key=lambda item: (item[0] != 'Homepage', item[0]),
            )
        }

        reqs: list[Requirement | InvalidRequirementSpecification] = []
        for req in info.requires_dist:
            try:
                reqs.append(Requirement(req))
            except InvalidRequirement:
                reqs.append(InvalidRequirementSpecification(req))

        pkg = PackageInfo(
            summary=info.summary or '',
            description=description,
            author=info.author,
            maintainer=info.maintainer,
            classifiers=info.classifiers,
            project_urls=sorted_urls,
            requires_python=info.requires_python,
            requires_dist=RequirementsSequence(reqs),
            # We include files info as it is the only way to influence the file.size of
            # all files (for the files list page). In the future, this can be a standalone
            # component.
            files_info=files_info,
        )

        if not file.size:
            # If the repository doesn't provide information about the size take it from
            # the file info that we gathered.
            file = dataclasses.replace(file, size=files_info[file.filename].size)

        return file, pkg


def generate_safe_description_html(package_info: pkginfo.Distribution) -> str:
    # Handle the valid description content types.
    # https://packaging.python.org/specifications/core-metadata
    description_type = package_info.description_content_type or 'text/x-rst'
    raw_description = package_info.description or ''

    # Seen in the wild (internal only: sps-deep-hysteresis-compensation).
    description_type = description_type.replace('\"', '')

    if description_type == 'text/x-rst' or description_type.startswith('text/x-rst;'):
        return readme_renderer.rst.render(raw_description) or ""
    elif description_type == 'text/markdown' or description_type.startswith('text/markdown;'):  # Seen longer form with orjson
        return readme_renderer.markdown.render(raw_description) or ""
    elif description_type == 'text/plain' or description_type.startswith('text/plain;'):  # seen with nbformat
        return readme_renderer.txt.render(raw_description) or ""
    else:
        raise ValueError(f"Unknown readme format {description_type}")
