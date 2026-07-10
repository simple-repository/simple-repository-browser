import json
import sqlite3

import pytest

from simple_repository_browser import _search, fetch_projects
from simple_repository_browser.crawler import Crawler
from simple_repository_browser.fetch_description import (
    PackageInfo,
    Requirement,
    RequirementsSequence,
)


@pytest.fixture
def con():
    c = sqlite3.connect(":memory:")
    fetch_projects.create_table(c)
    return c


def _insert(con, name, requires_dist):
    blob = json.dumps({"requires_dist": requires_dist})
    con.execute(
        "INSERT INTO projects(canonical_name, preferred_name, metadata_json) VALUES (?, ?, ?)",
        (name, name, blob),
    )
    con.commit()


def test_insert_populates_shadow(con):
    _insert(
        con,
        "acme",
        [
            {"name": "numpy", "extra": None, "specifier": ">=1", "marker": None},
            {
                "name": "pytest",
                "extra": "test",
                "specifier": "",
                "marker": "extra == 'test'",
            },
        ],
    )
    rows = con.execute(
        "SELECT canonical_name, dep_canonical_name, extra FROM dependencies_idx "
        "ORDER BY dep_canonical_name"
    ).fetchall()
    assert rows == [("acme", "numpy", None), ("acme", "pytest", "test")]


def test_update_replaces_shadow_rows(con):
    _insert(
        con,
        "acme",
        [{"name": "numpy", "extra": None, "specifier": "", "marker": None}],
    )
    con.execute(
        "UPDATE projects SET metadata_json = ? WHERE canonical_name = 'acme'",
        (
            json.dumps(
                {
                    "requires_dist": [
                        {
                            "name": "scipy",
                            "extra": None,
                            "specifier": "",
                            "marker": None,
                        },
                    ]
                }
            ),
        ),
    )
    con.commit()
    rows = con.execute(
        "SELECT dep_canonical_name FROM dependencies_idx WHERE canonical_name = 'acme'"
    ).fetchall()
    assert rows == [("scipy",)]


def test_delete_removes_shadow_rows(con):
    _insert(
        con,
        "acme",
        [{"name": "numpy", "extra": None, "specifier": "", "marker": None}],
    )
    con.execute("DELETE FROM projects WHERE canonical_name = 'acme'")
    con.commit()
    assert con.execute("SELECT COUNT(*) FROM dependencies_idx").fetchone()[0] == 0


def test_null_metadata_is_tolerated(con):
    con.execute(
        "INSERT INTO projects(canonical_name, preferred_name) VALUES ('empty', 'empty')"
    )
    con.commit()
    assert con.execute("SELECT COUNT(*) FROM dependencies_idx").fetchone()[0] == 0


def test_migrate_upgrades_pre_v1_db():
    c = sqlite3.connect(":memory:")
    c.execute(
        "CREATE TABLE projects (canonical_name text unique, preferred_name text, "
        "summary text, release_date timestamp, release_version text)"
    )
    c.commit()
    assert c.execute("PRAGMA user_version").fetchone()[0] == 0

    fetch_projects.migrate(c)
    fetch_projects.migrate(c)  # second call must be a no-op

    cols = {row[1] for row in c.execute("PRAGMA table_info(projects)").fetchall()}
    assert "metadata_json" in cols
    assert (
        c.execute("PRAGMA user_version").fetchone()[0] == fetch_projects.SCHEMA_VERSION
    )


def test_migrate_on_fresh_db_sets_version_and_creates_tables():
    c = sqlite3.connect(":memory:")
    fetch_projects.migrate(c)
    assert (
        c.execute("PRAGMA user_version").fetchone()[0] == fetch_projects.SCHEMA_VERSION
    )
    tables = {
        row[0] for row in c.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {"projects", "dependencies_idx"} <= tables


def test_update_metadata_writes_blob_and_triggers_shadow(con):
    con.execute(
        "INSERT INTO projects(canonical_name, preferred_name) VALUES ('acme', 'acme')"
    )
    con.commit()
    fetch_projects.update_metadata(
        con,
        name="acme",
        metadata_json=json.dumps(
            {
                "requires_dist": [
                    {
                        "name": "numpy",
                        "extra": None,
                        "specifier": "",
                        "marker": None,
                    },
                ]
            }
        ),
    )
    assert con.execute(
        "SELECT dep_canonical_name FROM dependencies_idx WHERE canonical_name = 'acme'"
    ).fetchall() == [("numpy",)]


def test_search_depends_and_depends_via_extra(con):
    con.execute(
        "INSERT INTO projects(canonical_name, preferred_name, metadata_json) VALUES (?,?,?)",
        (
            "acme",
            "acme",
            json.dumps(
                {
                    "requires_dist": [
                        {
                            "name": "numpy",
                            "extra": None,
                            "specifier": "",
                            "marker": None,
                        },
                    ]
                }
            ),
        ),
    )
    con.execute(
        "INSERT INTO projects(canonical_name, preferred_name, metadata_json) VALUES (?,?,?)",
        (
            "widget",
            "widget",
            json.dumps(
                {
                    "requires_dist": [
                        {
                            "name": "pytest",
                            "extra": "test",
                            "specifier": "",
                            "marker": "extra == 'test'",
                        },
                    ]
                }
            ),
        ),
    )
    con.commit()

    def _run(query):
        builder = _search.query_to_sql(query)
        sql, params = builder.build_complete_query(
            "SELECT canonical_name FROM projects", limit=10, offset=0
        )
        return [r[0] for r in con.execute(sql, params).fetchall()]

    assert _run("depends:numpy") == ["acme"]
    assert _run("depends:pytest") == []  # pytest is only pulled in via extra
    assert _run("depends-via-extra:pytest") == ["widget"]
    assert _run("depends-via-extra:numpy") == []


def test_backfill_from_cache_populates_shadow(con):
    con.execute(
        "INSERT INTO projects(canonical_name, preferred_name, release_version) "
        "VALUES ('acme','acme','1.0')"
    )
    con.execute(
        "INSERT INTO projects(canonical_name, preferred_name, release_version) "
        "VALUES ('widget','widget','1.0')"
    )
    con.commit()

    cache = {
        ("pkg-info", "acme", "1.0"): (
            None,
            [],
            PackageInfo(
                summary="s",
                description="d",
                requires_dist=RequirementsSequence([Requirement("numpy>=1")]),
            ),
        ),
        ("other-cache-key", "foo", "1.0"): "irrelevant",
    }

    count = Crawler.backfill_metadata_from_cache(con, cache)
    assert count == 1
    assert con.execute(
        "SELECT dep_canonical_name FROM dependencies_idx WHERE canonical_name = 'acme'"
    ).fetchall() == [("numpy",)]
    # widget has no cached PackageInfo, so it remains NULL.
    assert (
        con.execute(
            "SELECT metadata_json FROM projects WHERE canonical_name = 'widget'"
        ).fetchone()[0]
        is None
    )

    # Second call is a no-op once the target row already has metadata_json.
    assert Crawler.backfill_metadata_from_cache(con, cache) == 0
