import dataclasses
import logging

from packaging.utils import InvalidWheelFilename, parse_wheel_filename
from packaging.version import InvalidVersion, Version
from simple_repository import model

logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class CompatibilityMatrixModel:
    matrix: dict[tuple[str, str], model.File]
    py_and_abi_names: tuple[str, ...]
    platform_names: tuple[str, ...]


def compatibility_matrix(
    files: tuple[model.File, ...],
) -> CompatibilityMatrixModel:
    """
    Look at the given files, and compute a compatibility matrix.

    """
    compat_matrix: dict[tuple[str, str], model.File] = {}
    # Track the py_abi_names seen, and store a sort key for those names.
    py_abi_names = {}
    # Track the platform_names (we sort by name).
    platform_names = set()

    for file in files:
        if not file.filename.lower().endswith(".whl"):
            continue
        try:
            entries = _wheel_matrix_entries(file.filename)
        except (InvalidWheelFilename, InvalidVersion) as err:
            # e.g. pydantic 0.18.1 ships a "py36+" python tag which isn't
            # PEP 425. Drop the file from the matrix rather than failing the
            # whole page.
            logger.warning(
                "Skipping %s in compatibility matrix: %s", file.filename, err
            )
            continue

        for tag_interp, platform in entries:
            compat_matrix[(tag_interp.nice_name, platform)] = file
            py_abi_names[tag_interp.nice_name] = (
                tag_interp.python_implementation,
                tag_interp.python_version,
                tag_interp.nice_name,
            )
            platform_names.add(platform)

    r_plat_names = tuple(sorted(platform_names))
    r_py_abi_names = tuple(sorted(py_abi_names, key=py_abi_names.__getitem__))

    return CompatibilityMatrixModel(compat_matrix, r_py_abi_names, r_plat_names)


def _wheel_matrix_entries(
    filename: str,
) -> list[tuple["InterpretedPyAndABITag", str]]:
    """Interpret a wheel's tags into (py/abi interpretation, platform) pairs.

    Raises InvalidWheelFilename or InvalidVersion if the filename or one of
    its tags can't be parsed.
    """
    _, _, _, tags = parse_wheel_filename(filename)

    # parse_wheel_filename returns tags as a frozenset, so establish a stable order.
    sorted_tags = sorted(tags, key=lambda tag: (tag.platform, tag.abi, tag.interpreter))

    return [
        (interpret_py_and_abi_tag(tag.interpreter, tag.abi), tag.platform)
        for tag in sorted_tags
    ]


# https://packaging.python.org/en/latest/specifications/platform-compatibility-tags/#python-tag
py_tag_implementations = {
    "py": "Python",
    "cp": "CPython",
    "ip": "IronPython",
    "pp": "PyPy",
    "jy": "Jython",
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
        if "_" in version_nodot:
            py_version = Version(".".join(version_nodot.split("_")))
        elif len(version_nodot) == 1:
            # e.g. Pure python wheels
            py_version = Version(version_nodot)
        else:
            py_version = Version(f"{version_nodot[0]}.{version_nodot[1:]}")

        if abi_tag.startswith(py_tag):
            abi_tag_flags = abi_tag[len(py_tag) :]
            if "d" in abi_tag_flags:
                abi_tag_flags = abi_tag_flags.replace("d", "")
                py_impl += " (debug)"
            if "u" in abi_tag_flags:
                abi_tag_flags = abi_tag_flags.replace("u", "")
                # A python 2 concept.
                py_impl += " (wide)"
            if "m" in abi_tag_flags:
                abi_tag_flags = abi_tag_flags.replace("m", "")
                pass
            if abi_tag_flags:
                py_impl += f" (additional flags: {abi_tag_flags})"
            return InterpretedPyAndABITag(
                f"{py_impl} {py_version}", py_impl, py_version
            )
        elif abi_tag.startswith("pypy") and py_impl == "PyPy":
            abi = abi_tag.split("_")[1]
            return InterpretedPyAndABITag(
                f"{py_impl} {py_version} ({abi})", py_impl, py_version
            )
        elif abi_tag == "abi3":
            # Example PyQt6
            return InterpretedPyAndABITag(
                f"{py_impl} >={py_version} (abi3)", py_impl, py_version
            )
        elif abi_tag == "none":
            # Seen with pydantic-core 2.11.0
            return InterpretedPyAndABITag(
                f"{py_impl} {py_version}", py_impl, py_version
            )
        else:
            return InterpretedPyAndABITag(
                f"{py_impl} {py_version} ({abi_tag})", py_impl, py_version
            )

    return InterpretedPyAndABITag(f"{py_tag} ({abi_tag})")
