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


def test_v1_to_v2_nulls_existing_metadata_json():
    c = sqlite3.connect(":memory:")
    # Simulate a v1 DB with populated metadata_json.
    fetch_projects.create_table(c)
    c.execute("PRAGMA user_version = 1")
    c.execute(
        "INSERT INTO projects(canonical_name, preferred_name, metadata_json) "
        "VALUES ('acme','acme',?)",
        (json.dumps({"requires_dist": []}),),
    )
    c.commit()

    fetch_projects.migrate(c)

    assert (
        c.execute("PRAGMA user_version").fetchone()[0] == fetch_projects.SCHEMA_VERSION
    )
    assert fetch_projects.SCHEMA_VERSION == 3
    assert (
        c.execute(
            "SELECT metadata_json FROM projects WHERE canonical_name = 'acme'"
        ).fetchone()[0]
        is None
    )
    # dependencies_idx cascades — nulling metadata_json fires the UPDATE trigger,
    # which clears the shadow rows for that project.
    assert (
        c.execute(
            "SELECT COUNT(*) FROM dependencies_idx WHERE canonical_name = 'acme'"
        ).fetchone()[0]
        == 0
    )


def test_v2_migrate_is_noop_on_fresh_db():
    c = sqlite3.connect(":memory:")
    fetch_projects.migrate(c)
    assert (
        c.execute("PRAGMA user_version").fetchone()[0] == fetch_projects.SCHEMA_VERSION
    )
    fetch_projects.migrate(c)  # second call must be a no-op


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


def test_backfill_uses_cached_private_metadata_for_source(con):
    con.execute(
        "INSERT INTO projects(canonical_name, preferred_name, release_version) "
        "VALUES ('acme','acme','1.0')"
    )
    con.execute(
        "INSERT INTO projects(canonical_name, preferred_name, release_version) "
        "VALUES ('legacy','legacy','1.0')"
    )
    con.commit()

    cache = {
        # 4-tuple: private_metadata cached — source flows through.
        ("pkg-info", "acme", "1.0"): (
            None,
            [],
            PackageInfo(
                summary="s", description="d", requires_dist=RequirementsSequence([])
            ),
            {"_source_repository": "cern-internal"},
        ),
        # 3-tuple: pre-fix cache entry — must still backfill (without source).
        ("pkg-info", "legacy", "1.0"): (
            None,
            [],
            PackageInfo(
                summary="s", description="d", requires_dist=RequirementsSequence([])
            ),
        ),
    }

    assert Crawler.backfill_metadata_from_cache(con, cache) == 2
    acme_blob = json.loads(
        con.execute(
            "SELECT metadata_json FROM projects WHERE canonical_name = 'acme'"
        ).fetchone()[0]
    )
    legacy_blob = json.loads(
        con.execute(
            "SELECT metadata_json FROM projects WHERE canonical_name = 'legacy'"
        ).fetchone()[0]
    )
    assert acme_blob["source"] == "cern-internal"
    assert legacy_blob["source"] is None


def test_search_source_and_has_docs(con):
    con.execute(
        "INSERT INTO projects(canonical_name, preferred_name, metadata_json) VALUES (?,?,?)",
        (
            "acme",
            "acme",
            json.dumps(
                {
                    "requires_dist": [],
                    "project_urls": {"Documentation": "https://d"},
                    "source": "some-source",
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
                    "requires_dist": [],
                    "project_urls": {"Homepage": "https://h"},
                    "source": "other-source",
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

    assert _run("source:some-source") == ["acme"]
    assert _run("source:Other-Source") == ["widget"]  # case-insensitive
    assert _run("has:docs") == ["acme"]
    assert _run("source:some-source AND has:docs") == ["acme"]
    assert _run("source:other-source AND has:docs") == []


def test_negation_excludes_uncrawled_rows(con):
    # populated: has docs, depends on numpy, source=s
    con.execute(
        "INSERT INTO projects(canonical_name, preferred_name, summary, metadata_json) VALUES (?,?,?,?)",
        (
            "populated",
            "populated",
            "hi",
            json.dumps(
                {
                    "requires_dist": [
                        {
                            "name": "numpy",
                            "extra": None,
                            "specifier": "",
                            "marker": None,
                        }
                    ],
                    "project_urls": {"Documentation": "https://d"},
                    "source": "s",
                }
            ),
        ),
    )
    # crawled but doesn't have docs / doesn't depend on numpy
    con.execute(
        "INSERT INTO projects(canonical_name, preferred_name, summary, metadata_json) VALUES (?,?,?,?)",
        (
            "bare",
            "bare",
            "hi",
            json.dumps({"requires_dist": [], "project_urls": {}, "source": "other"}),
        ),
    )
    # uncrawled: NULL metadata_json + NULL summary
    con.execute(
        "INSERT INTO projects(canonical_name, preferred_name) VALUES ('uncrawled','uncrawled')"
    )
    con.commit()

    def _run(query):
        builder = _search.query_to_sql(query)
        sql, params = builder.build_complete_query(
            "SELECT canonical_name FROM projects", limit=10, offset=0
        )
        return sorted(r[0] for r in con.execute(sql, params).fetchall())

    # All four negated filters must exclude the uncrawled row.
    assert _run("-has:docs") == ["bare"]
    assert _run("-depends:numpy") == ["bare"]
    assert _run("-source:s") == ["bare"]
    assert _run("-summary:missing") == ["bare", "populated"]


def test_has_docs_matches_case_variants(con):
    # Core-metadata `Project-URL` labels aren't case-normalised, so
    # `has:docs` must match any casing of "Documentation".
    for name, label in [
        ("cap", "Documentation"),
        ("lower", "documentation"),
        ("upper", "DOCUMENTATION"),
    ]:
        con.execute(
            "INSERT INTO projects(canonical_name, preferred_name, metadata_json) VALUES (?,?,?)",
            (
                name,
                name,
                json.dumps(
                    {
                        "requires_dist": [],
                        "project_urls": {label: "https://d"},
                        "source": None,
                    }
                ),
            ),
        )
    # Different label entirely — must not match.
    con.execute(
        "INSERT INTO projects(canonical_name, preferred_name, metadata_json) VALUES (?,?,?)",
        (
            "other",
            "other",
            json.dumps(
                {
                    "requires_dist": [],
                    "project_urls": {"Homepage": "https://h"},
                    "source": None,
                }
            ),
        ),
    )
    con.commit()

    builder = _search.query_to_sql("has:docs")
    sql, params = builder.build_complete_query(
        "SELECT canonical_name FROM projects", limit=10, offset=0
    )
    assert sorted(r[0] for r in con.execute(sql, params).fetchall()) == [
        "cap",
        "lower",
        "upper",
    ]
