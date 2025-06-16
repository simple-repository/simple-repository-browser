import parsley
import pytest

from simple_repository_browser import _search
from simple_repository_browser._search import Filter, FilterOn


@pytest.mark.parametrize(
    ["query", "expected_expression_graph"],
    [
        ("", ()),
        pytest.param("some-name", (Filter(FilterOn.name_or_summary, 'some-name'),)),
        pytest.param("some name", (_search.And(Filter(FilterOn.name_or_summary, 'some'), Filter(FilterOn.name_or_summary, 'name')),)),
        pytest.param("som*name", (Filter(FilterOn.name_or_summary, 'som*name'),)),
        pytest.param('"some name"', (Filter(FilterOn.name_or_summary, '"some name"'),)),
        pytest.param('"some-name"', (Filter(FilterOn.name_or_summary, '"some-name"'),)),
        pytest.param('"CASE"', (Filter(FilterOn.name_or_summary, '"CASE"'),)),
        pytest.param('-foo', (_search.Not(Filter(FilterOn.name_or_summary, 'foo')),)),
        pytest.param('-"foo bar"', (_search.Not(Filter(FilterOn.name_or_summary, '"foo bar"')),)),
        pytest.param('-name:"foo bar"', (_search.Not(Filter(FilterOn.name, '"foo bar"')),)),
        pytest.param('name:foo', (Filter(FilterOn.name, 'foo'),)),
        pytest.param(
            'name:foo OR name:bar', (
                _search.Or(
                    Filter(FilterOn.name, 'foo'),
                    Filter(FilterOn.name, 'bar'),
                ),
            ),
        ),
        pytest.param(
            'name:foo AND "fiddle AND sticks"', (
                _search.And(
                    Filter(FilterOn.name, 'foo'),
                    Filter(FilterOn.name_or_summary, '"fiddle AND sticks"'),
                ),
            ),
        ),
        pytest.param('summary:foo', (Filter(FilterOn.summary, 'foo'),)),
        pytest.param(
            'name:"NAME OR" AND "fiddle AND sticks"', (
                _search.And(
                    Filter(FilterOn.name, '"NAME OR"'),
                    Filter(FilterOn.name_or_summary, '"fiddle AND sticks"'),
                ),
            ),
        ),
        pytest.param('(((a)))', (Filter(FilterOn.name_or_summary, 'a'),)),
        pytest.param('(((a) OR (b)))', (_search.Or(Filter(FilterOn.name_or_summary, 'a'), Filter(FilterOn.name_or_summary, 'b')),)),
        pytest.param(
            '(a AND b) OR (c AND d)', (
                _search.Or(
                    _search.And(Filter(FilterOn.name_or_summary, 'a'), Filter(FilterOn.name_or_summary, 'b')),
                    _search.And(Filter(FilterOn.name_or_summary, 'c'), Filter(FilterOn.name_or_summary, 'd')),
                ),
            ),
        ),
        pytest.param(
            '((a AND b)) OR (c AND -d)', (
                _search.Or(
                    _search.And(Filter(FilterOn.name_or_summary, 'a'), Filter(FilterOn.name_or_summary, 'b')),
                    _search.And(Filter(FilterOn.name_or_summary, 'c'), _search.Not(Filter(FilterOn.name_or_summary, 'd'))),
                ),
            ),
        ),
    ],
)
def test_parse_query(query, expected_expression_graph):
    result = _search.parse(query)
    assert result == expected_expression_graph


@pytest.mark.parametrize(
    ["query", "expected_result"],
    [
        ("", None),
        ("name:foo", "foo"),
        ("name:foo__unnormed", "foo-unnormed"),
        ("foo", "foo"),
        ("some*.Name", None),
        ("summary:\"Some Description\"", None),
        ("foo bar", None),
        ("foo OR bar", None),
        ("-name:foo OR -bar", None),
    ],
)
def test_simple_name_proposal(query, expected_result):
    terms = _search.parse(query)
    result = _search.simple_name_from_query(terms)
    assert result == expected_result


@pytest.mark.parametrize(
    ["query", "expected_predicate"],
    [
        ("", ("", ())),
        (" ", ("", ())),
        ("name:foo", ('canonical_name LIKE ?', ('%foo%',))),
        ("name:foo__unnormed", ('canonical_name LIKE ?', ('%foo-unnormed%',))),
        ("foo", ('(canonical_name LIKE ? OR summary LIKE ?)', ('%foo%', '%foo%'))),
        ("some*.Name", ('(canonical_name LIKE ? OR summary LIKE ?)', ('%some%-name%', '%some%.Name%'))),
        ("summary:\"Some Description\"", ('summary LIKE ?', ('%Some Description%',))),
        ("foo bar", ('((canonical_name LIKE ? OR summary LIKE ?) AND (canonical_name LIKE ? OR summary LIKE ?))', ('%foo%', '%foo%', '%bar%', '%bar%'))),
        ("foo OR bar", ('((canonical_name LIKE ? OR summary LIKE ?) OR (canonical_name LIKE ? OR summary LIKE ?))', ('%foo%', '%foo%', '%bar%', '%bar%'))),
        ("-name:foo OR -bar", ('(Not (canonical_name LIKE ? OR (Not (canonical_name LIKE ? OR summary LIKE ?))))', ('%foo%', '%bar%', '%bar%'))),
        ("summary:\"Some'; DROP TABLE gotcha; ' Description\"", ('summary LIKE ?', ("%Some'; DROP TABLE gotcha; ' Description%",))),
    ],
)
def test_build_sql_predicate(query, expected_predicate):
    sql_stmt, params = _search.query_to_sql(query)
    assert (sql_stmt, params) == expected_predicate
    assert sql_stmt == expected_predicate[0]
    assert params == expected_predicate[1]


@pytest.mark.parametrize(
    ["query", "expected_exception"],
    [
        # ("", ()),   ? Should this be an error? Currently explicitly enabled.
        # (" ", pytest.raises(parsley.ParseError)),
        ("'s'", pytest.raises(parsley.ParseError)),
        ("\"imbalanced", pytest.raises(parsley.ParseError)),
        ("unacceptable;char", pytest.raises(parsley.ParseError)),
        ("unacceptable%char", pytest.raises(parsley.ParseError)),
        ("-name:(foo OR bar)", pytest.raises(parsley.ParseError)),
        ("name:", pytest.raises(parsley.ParseError)),
        ('notallowed:foo', pytest.raises(parsley.ParseError)),
    ],
)
def test_invalid_query(query, expected_exception):
    with expected_exception:
        result = _search.parse(query)
        print('Result:', result)
