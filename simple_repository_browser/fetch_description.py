# Copyright (C) 2023, CERN
# This software is distributed under the terms of the MIT
# licence, copied verbatim in the file "LICENSE".
# In applying this license, CERN does not waive the privileges and immunities
# granted to it by virtue of its status as Intergovernmental Organization
# or submit itself to any jurisdiction.

import asyncio
import contextlib
import dataclasses
import datetime
import email.parser
import email.policy
import logging
import os.path
import tarfile
import tempfile
import typing
import zipfile

import aiohttp
import bleach
import importlib_metadata
import pkginfo
import readme_renderer.markdown
import readme_renderer.rst
from simple_repository.simple import model


@dataclasses.dataclass
class FileInfo:
    #: Size, in bytes, of the compressed file.
    size: int


@dataclasses.dataclass
class PackageInfo:
    summary: str
    description: str
    url: str
    author: typing.Optional[str] = None
    maintainer: typing.Optional[str] = None
    classifiers: typing.Sequence[str] = ()
    release_date: typing.Optional[datetime.datetime] = None
    project_urls: typing.Dict[str, str] = dataclasses.field(default_factory=dict)
    files_info: typing.Dict[str, FileInfo] = dataclasses.field(default_factory=dict)
    requires_python: typing.Optional[str] = None
    requires_dist: typing.Sequence[str] = ()


class SDist(pkginfo.SDist):
    def read(self):
        fqn = os.path.abspath(
            os.path.normpath(self.filename),
        )

        archive, names, read_file = self._get_archive(fqn)

        try:
            tuples = [x.split('/') for x in names if 'PKG-INFO' in x]
            schwarz = sorted([(-len(x), x) for x in tuples])

            for path in [x[1] for x in schwarz]:
                candidate = '/'.join(path)
                data = read_file(candidate)
                if b'Metadata-Version' in data:
                    reqs = '/'.join(path[:-1] + ['requires.txt'])
                    if reqs in names:
                        contents = read_file(reqs).decode()
                        # Private method to read the pkg-info metadata from the sdist.
                        r = importlib_metadata.Distribution._convert_egg_info_reqs_to_simple_reqs(
                            importlib_metadata.Sectioned.read(contents),
                        )
                        data = data.decode().split('\n')
                        inject = [f'Requires-Dist: {req}' for req in r]
                        data[2:2] = inject
                        data = '\n'.join(data).encode('utf-8')
                    return data
        finally:
            archive.close()


async def fetch_file(url, dest):
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as session:
        async with session.get(url) as r:
            try:
                r.raise_for_status()
            except aiohttp.client.ClientResponseError as err:
                raise IOError(f'Unable to fetch file (reason: { str(err) })')
            chunk_size = 1024 * 100
            with open(dest, 'wb') as fd:
                while True:
                    chunk = await r.content.read(chunk_size)
                    if not chunk:
                        break
                    fd.write(chunk)


class _ZipfileTimeTracker(zipfile.ZipFile):
    def read(self, name):
        info = self.getinfo(name)
        t = datetime.datetime(*info.date_time)
        _ZipfileTimeTracker.captured_time = t
        return super().read(name)


class _TarfileTimeTracker(tarfile.TarFile):
    def extractfile(self, name):
        t = self.getmember(name).mtime
        _TarfileTimeTracker.captured_time = datetime.datetime.fromtimestamp(t)
        return super().extractfile(name)


class ArchiveTimestampCapture:
    def __init__(self):
        self.timestamp = None

    @contextlib.contextmanager
    def patch_archive_classes(self):
        """
        Patch zipfile and tarfile to capture the timestamp of any opened files.

        """
        tarfile.TarFile, orig_tarfile = _TarfileTimeTracker, tarfile.TarFile
        zipfile.ZipFile, orig_zipfile = _ZipfileTimeTracker, zipfile.ZipFile
        _ZipfileTimeTracker.captured_time = _TarfileTimeTracker.captured_time = None
        try:
            yield
            self.timestamp = _ZipfileTimeTracker.captured_time or _TarfileTimeTracker.captured_time
        finally:
            zipfile.ZipFile, tarfile.TarFile = orig_zipfile, orig_tarfile


EMPTY_PKG_INFO = PackageInfo('', '', '')


async def package_info(
    release_files: tuple[model.File, ...],
) -> typing.Optional[PackageInfo]:
    if not release_files:
        return None

    files = sorted(
        release_files,
        key=lambda file: (
            file.filename.endswith('.whl'),
            file.filename.endswith('.tar.gz'),
            file.filename.endswith('.zip'),
        ),
    )

    files_info = {}
    limited_concurrency = asyncio.Semaphore(10)
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as session:
        async def semaphored_head(filename, url):
            async with limited_concurrency:
                return (
                    filename,
                    await session.head(url, allow_redirects=True, ssl=False, headers={}),
                )
        coros = [
            semaphored_head(file.filename, file.url)
            for file in files
        ]
        for coro in asyncio.as_completed(coros):
            filename, response = await coro
            files_info[filename] = FileInfo(
                size=int(response.headers['Content-Length']),
            )

    file = files[0]
    logging.info(f'Downloading {file.filename} from {file.url}')

    is_wheel = file.filename.endswith('.whl')
    # Limiting ourselves to wheels and sdists is the 80-20 rule.
    archive_type = pkginfo.Wheel if is_wheel else SDist

    with tempfile.NamedTemporaryFile(
            suffix=os.path.splitext(file.filename)[1],
    ) as tmp:
        try:
            await fetch_file(file.url, tmp.name)
        except IOError as err:
            logging.warning(f"Unable to fetch {file.url}: {str(err)}")
            return None
        tmp.flush()
        tmp.seek(0)
        try:
            # Capture the timestamp of the file that pkginfo opens so that we
            # can estimate the release date.
            ts_capture = ArchiveTimestampCapture()
            with ts_capture.patch_archive_classes():
                info = archive_type(tmp.name)
        except ValueError as err:
            logging.warning(f'Unable to open {file.url}: { str(err) }')
            return None

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

        # TODO: More metadata could be extracted here.
        pkg = PackageInfo(
            summary=info.summary or '',
            description=description,
            url=info.home_page,
            author=info.author,
            maintainer=info.maintainer,
            classifiers=info.classifiers,
            release_date=ts_capture.timestamp,
            project_urls={
                url.split(',')[0].strip(): url.split(',')[1].strip()
                for url in info.project_urls or []
            },
            files_info=files_info,
            requires_python=info.requires_python,
            requires_dist=info.requires_dist,
        )

        # Ensure that a Homepage exists in the project urls
        if pkg.url and 'Homepage' not in pkg.project_urls:
            pkg.project_urls['Homepage'] = pkg.url

        return pkg


def generate_safe_description_html(package_info: pkginfo.Distribution):
    # Handle the valid description content types.
    # https://packaging.python.org/specifications/core-metadata
    description_type = package_info.description_content_type or 'text/x-rst'
    raw_description = package_info.description or ''

    if description_type == 'text/x-rst' or description_type.startswith('text/x-rst;'):
        return readme_renderer.rst.render(raw_description)

    elif (
        description_type == 'text/markdown' or
        description_type.startswith('text/markdown;')  # Seen longer form with orjson
    ):
        return readme_renderer.markdown.render(raw_description)
    else:
        # Plain, or otherwise.
        description = raw_description

    ALLOWED_TAGS = [
        "h1", "h2", "h3", "h4", "h5", "h6", "hr",
        "div", "object",
        "ul", "ol", "li", "p", "br",
        "pre", "code", "blockquote",
        "strong", "em", "a", "img", "b", "i",
        "table", "thead", "tbody", "tr", "th", "td", "tt",
    ]
    ALLOWED_ATTRIBUTES = {
        "h1": ["id"], "h2": ["id"], "h3": ["id"], "h4": ["id"],
        "a": ["href", "title"],
        "img": ["src", "title", "alt"],
    }

    description = bleach.clean(
        description,
        tags=set(bleach.sanitizer.ALLOWED_TAGS) | set(ALLOWED_TAGS),
        attributes=ALLOWED_ATTRIBUTES,
    )
    description = bleach.linkify(description, parse_email=True)
    return description
