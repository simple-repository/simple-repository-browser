import typing

from pypil.simple.index import SimplePackageIndex
from pypil.in_memory.project import InMemoryProjectRelease

import dataclasses


@dataclasses.dataclass
class PackageInfo:
    summary: str
    description: str


# from pkginfo import Distribution


async def package_info(release: InMemoryProjectRelease) -> typing.Optional[PackageInfo]:
    import tempfile
    from pkginfo import SDist
    from pkginfo import Wheel

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

    is_wheel = file.filename.endswith('.whl')
    # Limiting ourselves to wheels and sdists is the 80-20 rule.
    archive_type = Wheel if is_wheel else SDist

    with tempfile.NamedTemporaryFile() as tmp:
        file.copy_to(tmp.name)
        tmp.flush()
        tmp.seek(0)
        try:
            mypackage = archive_type(tmp.name)
        except ValueError:
            return None

        description = generate_safe_description_html(mypackage)

        return PackageInfo(mypackage.summary or '', description)
    # print(mypackage)
    # print(mypackage.version)
    # print(mypackage.description)
    # print(mypackage.summary)


from pkginfo import Distribution
def generate_safe_description_html(package_info: Distribution):
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
        import markdown
        description = markdown.markdown(raw_description)
        # Interesting case: cartopy 0.20.1
    else:
        # Plain, or otherwise.
        description = raw_description

    import bleach

    ALLOWED_TAGS = [
        "h1", "h2", "h3", "h4", "h5", "h6", "hr",
        "div",
        "ul", "ol", "li", "p", "br",
        "pre", "code", "blockquote",
        "strong", "em", "a", "img", "b", "i",
        "table", "thead", "tbody", "tr", "th", "td",
    ]
    ALLOWED_ATTRIBUTES = {
        "h1": ["id"], "h2": ["id"], "h3": ["id"], "h4": ["id"],
        "a": ["href", "title"],
        "img": ["src", "title", "alt"],
    }

    description = bleach.clean(description, tags=bleach.sanitizer.ALLOWED_TAGS + ALLOWED_TAGS, attributes=ALLOWED_ATTRIBUTES)

    return description


if __name__ == '__main__':
    index = SimplePackageIndex()

    prj = index.project('pyjapc')
    releases = prj.releases()
    print(releases[-1])
    summaries = {}
    for release in releases[::-1]:
        print(release.version, release.files())
        info = package_info(release)
        if info:
            summaries[release.version] = info.summary
            break
    print(summaries)
