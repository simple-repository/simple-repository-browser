import dataclasses
import logging
import tempfile
import typing

import aiohttp
import bleach
import markdown
import pkginfo

from . import _pypil


@dataclasses.dataclass
class PackageInfo:
    summary: str
    description: str


async def fetch_file(url, dest):
    async with aiohttp.ClientSession() as session:
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
        return None
    file = files[0]
    logging.info(f'Downloading {file.filename} from {file.url}')

    is_wheel = file.filename.endswith('.whl')
    # Limiting ourselves to wheels and sdists is the 80-20 rule.
    archive_type = pkginfo.Wheel if is_wheel else pkginfo.SDist

    with tempfile.NamedTemporaryFile(suffix='.whl') as tmp:
        try:
            await fetch_file(file.url, tmp.name)
        except IOError as err:
            logging.warning(f"Unable to fetch {file.url}: {str(err)}")
            return None
        tmp.flush()
        tmp.seek(0)
        try:
            info = archive_type(tmp.name)
        except ValueError as err:
            logging.warning(f'Unable to open {file.url}: { str(err) }')
            return None

        description = generate_safe_description_html(info)

        # TODO: More metadata could be extracted here.
        return PackageInfo(info.summary or '', description)


def generate_safe_description_html(package_info: pkginfo.Distribution):
    # Handle the valid description content types.
    # https://packaging.python.org/specifications/core-metadata
    description_type = package_info.description_content_type or 'text/x-rst'
    raw_description = package_info.description or ''
    if description_type == 'text/x-rst':
        from docutils.core import publish_parts
        description = publish_parts(raw_description, writer_name='html')['body']
        # Interesting case: numpy 1.21.4
        # Interesting case pyjapc/2.0.6 (no documentation)
    elif description_type == 'text/markdown':

        description = markdown.markdown(raw_description)
        # Interesting case: cartopy 0.20.1
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
    index = _pypil.SimplePackageIndex()

    prj = index.project('pyjapc')
    releases = prj.releases()
    print(releases[-1])
    summaries = {}
    for release in releases[::-1]:
        print(release.version, release.files())
        info = await package_info(release)
        if info:
            summaries[release.version] = info.summary
            break
    print(summaries)


if __name__ == '__main__':
    import asyncio
    asyncio.run(_devel_to_be_turned_into_test())
