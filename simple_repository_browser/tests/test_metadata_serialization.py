import json

from simple_repository_browser.fetch_description import (
    PackageInfo,
    Requirement,
    RequirementsSequence,
)
from simple_repository_browser.metadata_serialization import pkg_info_to_metadata_json


def _info(reqs):
    return PackageInfo(
        summary="s", description="d", requires_dist=RequirementsSequence(reqs)
    )


def _deps(info):
    return json.loads(pkg_info_to_metadata_json(info))["requires_dist"]


def _blob(info, **kwargs):
    return json.loads(pkg_info_to_metadata_json(info, **kwargs))


def test_source_is_lowercased_when_provided():
    assert _blob(_info([]), source="Some-Source")["source"] == "some-source"


def test_source_defaults_to_null():
    assert _blob(_info([]))["source"] is None


def test_project_urls_are_copied_verbatim():
    info = _info([])
    info.project_urls = {"Documentation": "https://d", "Homepage": "https://h"}
    assert _blob(info)["project_urls"] == {
        "Documentation": "https://d",
        "Homepage": "https://h",
    }


def test_empty_project_urls_yields_empty_dict():
    assert _blob(_info([]))["project_urls"] == {}


def test_core_dep_has_null_extra():
    assert _deps(_info([Requirement("numpy>=1")])) == [
        {"name": "numpy", "extra": None, "specifier": ">=1", "marker": None},
    ]


def test_extra_dep_is_tagged():
    deps = _deps(_info([Requirement('pytest ; extra == "test"')]))
    assert len(deps) == 1
    assert deps[0]["name"] == "pytest"
    assert deps[0]["extra"] == "test"


def test_environment_marker_preserved_without_extra():
    entry = _deps(_info([Requirement('tomli ; python_version < "3.11"')]))[0]
    assert entry["extra"] is None
    assert "python_version" in entry["marker"]


def test_name_is_canonicalised():
    entry = _deps(_info([Requirement("Flask_Login")]))[0]
    assert entry["name"] == "flask-login"


def test_invalid_requirement_is_skipped():
    from simple_repository_browser.fetch_description import (
        InvalidRequirementSpecification,
    )

    info = _info([InvalidRequirementSpecification(spec="not a req")])
    assert _deps(info) == []


def test_multi_extra_marker_emits_multiple_rows():
    # A requirement guarded on two extras should produce one entry per extra.
    req = Requirement('pytest ; extra == "test" or extra == "ci"')
    deps = _deps(_info([req]))
    assert sorted(d["extra"] for d in deps) == ["ci", "test"]
    assert all(d["name"] == "pytest" for d in deps)
