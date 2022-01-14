import contextlib
import dataclasses
import datetime
import logging
import os.path
import tarfile
import tempfile
import typing
import zipfile

import aiohttp
import bleach
import pkginfo
import readme_renderer.markdown
import readme_renderer.rst

from . import _pypil


@dataclasses.dataclass
class PackageInfo:
    summary: str
    description: str
    author: typing.Optional[str] = None
    maintainer: typing.Optional[str] = None
    release_date: typing.Optional[datetime.datetime] = None


async def fetch_file(url, dest):
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as session:
        async with session.get(url,) as r:
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


EMPTY_PKG_INFO = PackageInfo(
        '', '',
    )

async def package_info(
        release: _pypil.ProjectRelease,
) -> typing.Optional[PackageInfo]:

    files = sorted(
        release.files(),
        key=lambda file: (
            file.filename.endswith('.whl'),
            file.filename.endswith('.tar.gz'),
            file.filename.endswith('.zip'),
        )
    )

    if not files:
        logging.debug(f"no files found for {release.version}")
        return None
    file = files[0]
    logging.info(f'Downloading {file.filename} from {file.url}')

    is_wheel = file.filename.endswith('.whl')
    # Limiting ourselves to wheels and sdists is the 80-20 rule.
    archive_type = pkginfo.Wheel if is_wheel else pkginfo.SDist

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

        # TODO: More metadata could be extracted here.
        return PackageInfo(
            summary=info.summary or '',
            description=description,
            author=info.author,
            maintainer=info.maintainer,
            release_date=ts_capture.timestamp,
        )


def generate_safe_description_html(package_info: pkginfo.Distribution):
    # Handle the valid description content types.
    # https://packaging.python.org/specifications/core-metadata
    description_type = package_info.description_content_type or 'text/x-rst'
    raw_description = package_info.description or ''

    if description_type == 'text/x-rst':
        return readme_renderer.rst.render(raw_description)

    elif description_type == 'text/markdown':
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
        tags=bleach.sanitizer.ALLOWED_TAGS + ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
    )
    description = bleach.linkify(description, parse_email=True)
    return description


async def _devel_to_be_turned_into_test():
    index = _pypil.SimplePackageIndex(source_url='http://acc-py-repo.cern.ch:8000/simple')

    prj = index.project('pylogbook')
    releases = prj.releases()
    print(releases[-1])
    summaries = {}
    for release in releases[::-1]:
        print(release.version, release.files())
        info = await package_info(release)
        if info:
            summaries[release.version] = info.summary
            print(info.maintainer, info.author)
            break
    print(summaries)


if __name__ == '__main__':
    import asyncio
    asyncio.run(_devel_to_be_turned_into_test())
