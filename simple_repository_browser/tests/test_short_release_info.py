from packaging.version import Version
from simple_repository import model

from simple_repository_browser.short_release_info import ReleaseInfoModel


def _file(name: str, *, yanked: bool | str = False) -> model.File:
    return model.File(
        filename=name, url=f"https://example/{name}", hashes={}, yanked=yanked
    )


def test_compute_latest_version__skips_fully_yanked_highest():
    versions = {
        Version("1.0.0"): [_file("p-1.0.0.tar.gz")],
        Version("2.0.0"): [_file("p-2.0.0.tar.gz", yanked=True)],
    }
    assert ReleaseInfoModel.compute_latest_version(versions) == Version("1.0.0")


def test_compute_latest_version__partial_yank_still_wins():
    versions = {
        Version("1.0.0"): [_file("p-1.0.0.tar.gz")],
        Version("2.0.0"): [
            _file("p-2.0.0.tar.gz", yanked=True),
            _file("p-2.0.0-py3-none-any.whl"),
        ],
    }
    assert ReleaseInfoModel.compute_latest_version(versions) == Version("2.0.0")


def test_compute_latest_version__all_yanked_falls_back_to_highest():
    versions = {
        Version("1.0.0"): [_file("p-1.0.0.tar.gz", yanked=True)],
        Version("2.0.0"): [_file("p-2.0.0.tar.gz", yanked=True)],
    }
    assert ReleaseInfoModel.compute_latest_version(versions) == Version("2.0.0")


def test_compute_latest_version__prefers_yanked_stable_over_quarantined_stable():
    # Quarantined releases have empty file lists; they should rank below yanked ones.
    versions = {
        Version("1.0.0"): [_file("p-1.0.0.tar.gz", yanked=True)],
        Version("2.0.0"): [],
    }
    assert ReleaseInfoModel.compute_latest_version(versions) == Version("1.0.0")
