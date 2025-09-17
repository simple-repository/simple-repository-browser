from pathlib import Path
import sqlite3
import tempfile

import diskcache
import parsley
import pytest

from simple_repository_browser import _search, model
from simple_repository_browser._search import Filter, FilterOn


@pytest.mark.parametrize(
    ["query", "expected_expression_graph"],
    [
        ("", ()),
        pytest.param("some-name", (Filter(FilterOn.name_or_summary, "some-name"),)),
        pytest.param(
            "some name",
            (
                _search.And(
                    Filter(FilterOn.name_or_summary, "some"),
                    Filter(FilterOn.name_or_summary, "name"),
                ),
            ),
        ),
        pytest.param("som*name", (Filter(FilterOn.name_or_summary, "som*name"),)),
        pytest.param('"some name"', (Filter(FilterOn.name_or_summary, '"some name"'),)),
        pytest.param('"some-name"', (Filter(FilterOn.name_or_summary, '"some-name"'),)),
        pytest.param('"CASE"', (Filter(FilterOn.name_or_summary, '"CASE"'),)),
        pytest.param("-foo", (_search.Not(Filter(FilterOn.name_or_summary, "foo")),)),
        pytest.param(
            '-"foo bar"', (_search.Not(Filter(FilterOn.name_or_summary, '"foo bar"')),)
        ),
        pytest.param(
            '-name:"foo bar"', (_search.Not(Filter(FilterOn.name, '"foo bar"')),)
        ),
        pytest.param("name:foo", (Filter(FilterOn.name, "foo"),)),
        pytest.param(
            "name:foo OR name:bar",
            (
                _search.Or(
                    Filter(FilterOn.name, "foo"),
                    Filter(FilterOn.name, "bar"),
                ),
            ),
        ),
        pytest.param(
            'name:foo AND "fiddle AND sticks"',
            (
                _search.And(
                    Filter(FilterOn.name, "foo"),
                    Filter(FilterOn.name_or_summary, '"fiddle AND sticks"'),
                ),
            ),
        ),
        pytest.param("summary:foo", (Filter(FilterOn.summary, "foo"),)),
        pytest.param(
            'name:"NAME OR" AND "fiddle AND sticks"',
            (
                _search.And(
                    Filter(FilterOn.name, '"NAME OR"'),
                    Filter(FilterOn.name_or_summary, '"fiddle AND sticks"'),
                ),
            ),
        ),
        pytest.param("(((a)))", (Filter(FilterOn.name_or_summary, "a"),)),
        pytest.param(
            "(((a) OR (b)))",
            (
                _search.Or(
                    Filter(FilterOn.name_or_summary, "a"),
                    Filter(FilterOn.name_or_summary, "b"),
                ),
            ),
        ),
        pytest.param(
            "(a AND b) OR (c AND d)",
            (
                _search.Or(
                    _search.And(
                        Filter(FilterOn.name_or_summary, "a"),
                        Filter(FilterOn.name_or_summary, "b"),
                    ),
                    _search.And(
                        Filter(FilterOn.name_or_summary, "c"),
                        Filter(FilterOn.name_or_summary, "d"),
                    ),
                ),
            ),
        ),
        pytest.param(
            "((a AND b)) OR (c AND -d)",
            (
                _search.Or(
                    _search.And(
                        Filter(FilterOn.name_or_summary, "a"),
                        Filter(FilterOn.name_or_summary, "b"),
                    ),
                    _search.And(
                        Filter(FilterOn.name_or_summary, "c"),
                        _search.Not(Filter(FilterOn.name_or_summary, "d")),
                    ),
                ),
            ),
        ),
    ],
)
def test_parse_query(query, expected_expression_graph):
    result = _search.parse(query)
    assert result == expected_expression_graph


@pytest.mark.parametrize(
    ["query", "expected_predicate"],
    [
        ("", ("", ())),
        (" ", ("", ())),
        ("name:foo", ("canonical_name LIKE ?", ("%foo%",))),
        ("name:foo__unnormed", ("canonical_name LIKE ?", ("%foo-unnormed%",))),
        ("foo", ("(canonical_name LIKE ? OR summary LIKE ?)", ("%foo%", "%foo%"))),
        (
            "some*.Name",
            (
                "(canonical_name LIKE ? OR summary LIKE ?)",
                ("some%-name", "%some%.Name%"),
            ),
        ),
        (
            "some*.Name*",
            (
                "(canonical_name LIKE ? OR summary LIKE ?)",
                ("some%-name%", "%some%.Name%%"),
            ),
        ),
        ('summary:"Some Description"', ("summary LIKE ?", ("%Some Description%",))),
        (
            "foo bar",
            (
                "((canonical_name LIKE ? OR summary LIKE ?) AND (canonical_name LIKE ? OR summary LIKE ?))",
                ("%foo%", "%foo%", "%bar%", "%bar%"),
            ),
        ),
        (
            "foo OR bar",
            (
                "((canonical_name LIKE ? OR summary LIKE ?) OR (canonical_name LIKE ? OR summary LIKE ?))",
                ("%foo%", "%foo%", "%bar%", "%bar%"),
            ),
        ),
        (
            "-name:foo OR -bar",
            (
                "(NOT (canonical_name LIKE ? OR (NOT (canonical_name LIKE ? OR summary LIKE ?))))",
                ("%foo%", "%bar%", "%bar%"),
            ),
        ),
        (
            "summary:\"Some'; DROP TABLE gotcha; ' Description\"",
            ("summary LIKE ?", ("%Some'; DROP TABLE gotcha; ' Description%",)),
        ),
    ],
)
def test_build_sql_predicate(query, expected_predicate):
    sql_builder = _search.query_to_sql(query)
    sql_stmt = sql_builder.where_clause
    params = sql_builder.where_params
    assert (sql_stmt, params) == expected_predicate
    assert sql_stmt == expected_predicate[0]
    assert params == expected_predicate[1]


@pytest.mark.parametrize(
    ["query", "expected_exception"],
    [
        # ("", ()),   ? Should this be an error? Currently explicitly enabled.
        # (" ", pytest.raises(parsley.ParseError)),
        ("'s'", pytest.raises(parsley.ParseError)),
        ('"imbalanced', pytest.raises(parsley.ParseError)),
        ("unacceptable;char", pytest.raises(parsley.ParseError)),
        ("unacceptable%char", pytest.raises(parsley.ParseError)),
        ("-name:(foo OR bar)", pytest.raises(parsley.ParseError)),
        ("name:", pytest.raises(parsley.ParseError)),
        ("notallowed:foo", pytest.raises(parsley.ParseError)),
    ],
)
def test_invalid_query(query, expected_exception):
    with expected_exception:
        result = _search.parse(query)


class MockSimpleRepository:
    """Mock repository for testing search functionality."""

    async def get_project_page(self, name: str):
        """Mock project page retrieval - not needed for search ordering tests."""
        raise Exception(f"Project {name} not found")


@pytest.fixture
def test_database(tmp_path: Path):
    """Create a temporary SQLite database with test data for search ordering."""
    db_path = tmp_path / "test.db"
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row

    # Create projects table matching the real schema
    con.execute("""
        CREATE TABLE projects (
            canonical_name TEXT PRIMARY KEY,
            summary TEXT,
            release_version TEXT,
            release_date TEXT
        )
    """)

    # Insert test data designed for ordering tests
    test_projects = [
        # numpy family - for testing exact name closeness
        ("numpy", "Fundamental package for array computing", "1.24.0", "2023-01-01"),
        ("numpy-image", "Image processing with numpy", "0.1.0", "2023-02-01"),
        ("xnumpy", "Extended numpy functionality", "0.2.0", "2023-03-01"),
        ("amazeballs-numpy", "Extended numpy functionality", "0.2.0", "2023-03-01"),
        ("anumpyb", "Extended numpy functionality", "0.2.0", "2023-03-01"),
        ("numpyish", "Numpy-like functionality", "0.1.0", "2023-04-01"),
        ("abc", "Not at all like numpy", "0.1.0", "2023-04-01"),
        # scipy family - for testing exact name closeness
        ("scipy", "Scientific computing library", "1.10.0", "2023-01-15"),
        ("scipy2", "Alternative scipy implementation", "0.5.0", "2023-02-15"),
        ("scipylab", "Scipy laboratory", "0.3.0", "2023-03-15"),
        # scikit family - for testing fuzzy pattern matching
        ("scikit-amazeballs", "The bee's knees of scikits", "1.2.0", "2023-01-20"),
        ("scikit-learn", "Machine learning library", "1.2.0", "2023-01-20"),
        ("scikit-image", "Image processing library", "0.20.0", "2023-02-20"),
        ("scikit-optimize", "Optimisation library", "0.9.0", "2023-03-20"),
        # Other packages
        ("pandas", "Data manipulation library", "2.0.0", "2023-03-01"),
        ("matplotlib", "Plotting library", "3.7.0", "2023-01-10"),
        ("requests", "HTTP library", "2.28.0", "2022-12-01"),
    ]

    for name, summary, version, date in test_projects:
        con.execute(
            "INSERT INTO projects (canonical_name, summary, release_version, release_date) VALUES (?, ?, ?, ?)",
            (name, summary, version, date),
        )

    con.commit()
    yield con
    # Cleanup
    con.close()


@pytest.fixture
def test_model(test_database):
    """Create a model instance with test database."""
    # Create temporary cache directory
    cache_dir = tempfile.mkdtemp()
    cache = diskcache.Cache(cache_dir)

    # Create model with mock repository
    test_model = model.Model(
        source=MockSimpleRepository(),
        projects_db=test_database,
        cache=cache,
        crawler=None,  # Not needed for search tests
    )
    yield test_model
    cache.close()


def assert_order(expected_names, actual_results):
    """Helper to assert that results appear in expected order."""
    actual_names = [item.canonical_name for item in actual_results]

    # Check that all expected names are present
    for name in expected_names:
        assert name in actual_names, (
            f"Expected '{name}' not found in results: {actual_names}"
        )

    # Check relative ordering
    indices = {name: actual_names.index(name) for name in expected_names}
    for i in range(len(expected_names) - 1):
        current_name = expected_names[i]
        next_name = expected_names[i + 1]
        assert indices[current_name] < indices[next_name], (
            f"Expected '{current_name}' to come before '{next_name}' in {actual_names}"
        )


@pytest.mark.asyncio
async def test_exact_name_search_ordering(test_model):
    """Test that exact name searches return results in closeness order."""
    result = await test_model.project_query("numpy", page_size=10, page=1)

    # numpy should come first (exact match), then prefix matches, then suffix matches
    assert_order(["numpy", "numpy-image", "xnumpy", "abc"], result["results"])


@pytest.mark.asyncio
async def test_exact_name_search_scipy_ordering(test_model):
    """Test exact name search ordering with scipy family."""
    result = await test_model.project_query("scipy", page_size=10, page=1)

    # scipy should come first, then prefix matches (scipy2, scipylab)
    assert_order(["scipy", "scipy2"], result["results"])


@pytest.mark.asyncio
async def test_fuzzy_pattern_search_ordering(test_model):
    """Test that fuzzy pattern searches work correctly."""
    result = await test_model.project_query("scikit-*", page_size=10, page=1)
    # Should include all scikit-* packages, ordered by shortest, then alphabetically
    assert_order(
        ["scikit-image", "scikit-learn", "scikit-optimize", "scikit-amazeballs"],
        result["results"],
    )


@pytest.mark.asyncio
async def test_fuzzy_pattern_search_ordering_not_matching_prefix(test_model):
    result = await test_model.project_query("name:numpy*", page_size=10, page=1)
    names = [item.canonical_name for item in result["results"]]
    assert "xnumpy" not in names
    assert "anumpyb" not in names
    assert "abc" not in names
    assert_order(["numpy", "numpy-image"], result["results"])


@pytest.mark.asyncio
async def test_mixed_search_ordering_scipy_or_scikit(test_model):
    """Test mixed search: 'scipy OR scikit-*' - scipy first, then scikit patterns."""
    result = await test_model.project_query("scipy OR scikit-*", page_size=10, page=1)
    # Should get the exact match, then all scikits, then similar to exact match (scipy2)
    assert_order(["scipy", "scikit-amazeballs", "scipy2"], result["results"])


@pytest.mark.asyncio
async def test_quoted_exact_search(test_model):
    """Test quoted exact searches."""
    result = await test_model.project_query('"numpy"', page_size=10, page=1)
    names = [item.canonical_name for item in result["results"]]
    # Should return numpy first (exact match)
    assert names[0] == "numpy"
    assert_order(["numpy", "numpy-image", "xnumpy", "anumpyb"], result["results"])


@pytest.mark.asyncio
async def test_fuzzy_search(test_model):
    """Test name field-specific searches."""
    result = await test_model.project_query("num*-*", page_size=10, page=1)
    names = [item.canonical_name for item in result["results"]]
    assert "numpy" not in names
    # We should also find numpyish because of its summary containing "Numpy-like"
    assert_order(["numpy-image", "numpyish"], result["results"])


@pytest.mark.asyncio
async def test_name_field_specific_search(test_model):
    """Test name field-specific searches."""
    result = await test_model.project_query("name:numpy", page_size=10, page=1)
    assert_order(["numpy", "numpy-image", "xnumpy"], result["results"])


@pytest.mark.asyncio
async def test_summary_field_specific_search(test_model):
    """Test summary field-specific searches."""
    result = await test_model.project_query("summary:computing", page_size=10, page=1)
    assert_order(["numpy", "scipy"], result["results"])


@pytest.mark.asyncio
async def test_not_operator(test_model):
    """Test NOT operator functionality."""
    result = await test_model.project_query("-scipy", page_size=10, page=1)

    names = [item.canonical_name for item in result["results"]]
    # Should not include scipy
    assert "scipy" not in names
    assert_order(["numpy", "pandas"], result["results"])


@pytest.mark.asyncio
async def test_complex_mixed_query(test_model):
    """Test complex mixed query with multiple exact names."""
    result = await test_model.project_query("numpy OR scipy", page_size=10, page=1)

    names = [item.canonical_name for item in result["results"]]

    # Should include both families
    assert "numpy" in names
    assert "scipy" in names
    assert "numpy-image" in names
    assert "scipy2" in names

    # Exact matches should come before their related packages
    numpy_idx = names.index("numpy")
    scipy_idx = names.index("scipy")
    numpy_image_idx = names.index("numpy-image")
    scipy2_idx = names.index("scipy2")

    assert numpy_idx < numpy_image_idx
    assert scipy_idx < scipy2_idx


@pytest.mark.asyncio
async def test_mixed_query_suffix_ordering(test_model):
    """Test that suffix matches (xnumpy) come after fuzzy patterns in mixed queries."""
    result = await test_model.project_query("numpy OR scikit-*", page_size=10, page=1)

    assert_order(
        [
            "numpy",
            "scikit-learn",
            "numpy-image",
            "xnumpy",
            "amazeballs-numpy",
            "anumpyb",
        ],
        result["results"],
    )


@pytest.mark.asyncio
async def test_empty_results(test_model):
    """Test queries that return no results."""
    result = await test_model.project_query("nonexistentpackage", page_size=10, page=1)

    assert result["results"] == []
    assert result["results_count"] == 0
