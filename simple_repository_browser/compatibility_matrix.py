import dataclasses
from dataclasses import dataclass

from packaging.version import Version
from simple_repository import model


@dataclass(frozen=True)
class WheelMeta:
    project_name: str
    version: str
    build_tag: str
    python_tag: str
    abi_tag: str
    platform_tag: str


def parse_wheel_filename_format(filename):
    """
    Return the (pkg_name, version, build_tag or 0, python tag, abi tag, platform_tag) tuple for the
    given wheel filename  PEP427 states that a wheel's filename convention is:
    {distribution}-{version}(-{build tag})?-{python tag}-{abi tag}-{platform tag}.whl
    Ref: https://www.python.org/dev/peps/pep-0427/#file-name-convention
    """
    if filename.endswith('.whl'):
        filename = filename[:-4]
    parts = filename.split('-')
    names = ['project_name', 'version', 'build_tag', 'python_tag', 'abi_tag', 'platform_tag']
    kwargs = {}
    if len(parts) == len(names)-1:
        # Build tag is optional.
        names.remove('build_tag')
        kwargs['build_tag'] = ''
    if len(parts) != len(names):
        raise ValueError(f'Unexpected number of parts to the wheel filename: {parts} {names}')
    kwargs.update(zip(names, parts))
    return WheelMeta(**kwargs)


def compatibility_matrix(
        files: tuple[model.File],
) -> tuple[
    tuple[str, ...],
    tuple[str, ...],
    dict[tuple[str, str], model.File],
]:
    """
    Look at the given files, and compute a compatibility matrix.

    The return is a tuple of:
        py_abi_names, platform_names, {(py_abi_name, platform_name): file}

    """
    r_compat_matrix: dict[tuple[str, str], model.File] = {}
    # Track the py_abi_names seen, and store a sort key for those names.
    py_abi_names = {}
    # Track the platform_names (we sort by name).
    platform_names = set()

    interpreted_py_abi_tags: dict[tuple[str, str], InterpretedPyAndABITag] = {}

    for file in files:
        if not file.filename.lower().endswith('.whl'):
            continue
        whl_meta = parse_wheel_filename_format(file.filename)
        for platform_tag in whl_meta.platform_tag.split('.'):
            for python_tag in whl_meta.python_tag.split('.'):
                for abi_tag in whl_meta.abi_tag.split('.'):
                    k = (python_tag, abi_tag)
                    if k not in interpreted_py_abi_tags:
                        interpreted_py_abi_tags[k] = interpret_py_and_abi_tag(python_tag, abi_tag)

                    tag_interp = interpreted_py_abi_tags[k]
                    py_abi = tag_interp.nice_name
                    r_compat_matrix[(py_abi, platform_tag)] = file

                    # Track the seen tags, and define a sort order.
                    py_abi_names[py_abi] = (
                        tag_interp.python_implementation,
                        tag_interp.python_version,
                        tag_interp.nice_name,
                    )
                    platform_names.add(platform_tag)

    r_plat_names = tuple(sorted(platform_names))
    r_py_abi_names = tuple(sorted(py_abi_names, key=py_abi_names.__getitem__))

    return r_py_abi_names, r_plat_names, r_compat_matrix


# https://packaging.python.org/en/latest/specifications/platform-compatibility-tags/#python-tag
py_tag_implementations = {
    'py': 'Python',
    'cp': 'CPython',
    'ip': 'IronPython',
    'pp': 'PyPy',
    'jy': 'Jython',
}


@dataclasses.dataclass(frozen=True)
class InterpretedPyAndABITag:
    nice_name: str
    python_implementation: str | None = None
    python_version: Version | None = None


def interpret_py_and_abi_tag(py_tag: str, abi_tag: str) -> InterpretedPyAndABITag:
    if py_tag[:2] in py_tag_implementations:
        py_impl, version_nodot = py_tag[:2], py_tag[2:]
        py_impl = py_tag_implementations.get(py_impl, py_impl)
        if '_' in version_nodot:
            py_version = Version('.'.join(version_nodot.split('_')))
        elif len(version_nodot) == 1:
            # e.g. Pure python wheels
            py_version = Version(version_nodot)
        else:
            py_version = Version(f'{version_nodot[0]}.{version_nodot[1:]}')

        if abi_tag.startswith(py_tag):
            abi_tag_flags = abi_tag[len(py_tag):]
            if 'd' in abi_tag_flags:
                abi_tag_flags = abi_tag_flags.replace('d', '')
                py_impl += ' (debug)'
            if 'u' in abi_tag_flags:
                abi_tag_flags = abi_tag_flags.replace('u', '')
                # A python 2 concept.
                py_impl += ' (wide)'
            if 'm' in abi_tag_flags:
                abi_tag_flags = abi_tag_flags.replace('m', '')
                pass
            if abi_tag_flags:
                py_impl += f' (additional flags: {abi_tag_flags})'
            return InterpretedPyAndABITag(f'{py_impl} {py_version}', py_impl, py_version)
        elif abi_tag.startswith('pypy') and py_impl == 'PyPy':
            abi = abi_tag.split('_')[1]
            return InterpretedPyAndABITag(f'{py_impl} {py_version} ({abi})', py_impl, py_version)
        elif abi_tag == 'abi3':
            # Example PyQt6
            return InterpretedPyAndABITag(f'{py_impl} >={py_version} (abi3)', py_impl, py_version)
        elif abi_tag == 'none':
            # Seen with pydantic-core 2.11.0
            return InterpretedPyAndABITag(f'{py_impl} {py_version}', py_impl, py_version)
        else:
            return InterpretedPyAndABITag(f'{py_impl} {py_version} ({abi_tag})', py_impl, py_version)

    return InterpretedPyAndABITag(f'{py_tag} ({abi_tag})')
