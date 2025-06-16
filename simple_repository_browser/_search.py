import dataclasses
from enum import Enum
import re
import textwrap
import typing

import parsley


@dataclasses.dataclass
class Term:
    pass


class FilterOn(Enum):
    name = 'name'
    summary = 'summary'
    name_or_summary = 'name_or_summary'


@dataclasses.dataclass
class Filter(Term):
    filter_on: FilterOn
    value: str


@dataclasses.dataclass
class And(Term):
    lhs: Term
    rhs: Term


@dataclasses.dataclass
class Or(Term):
    lhs: Term
    rhs: Term


@dataclasses.dataclass
class Not(Term):
    term: Term


def normalise_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


# A safe SQL statement must not use *any* user-defined input in the resulting first argument (the SQL query),
# rather any user input MUST be provided as part of the arguments (second part of the value), which will be passed
# to SQLITE to deal with.
SafeSQLStmt = typing.Tuple[str, typing.Tuple[typing.Any, ...]]


def prepare_name(term: Filter) -> SafeSQLStmt:
    if term.value.startswith('"'):
        # Match the phase precisely.
        value = term.value[1:-1]
    else:
        value = normalise_name(term.value)
    value = value.replace('*', '%')
    return "canonical_name LIKE ?", (f'%{value}%',)


def prepare_summary(term: Filter) -> SafeSQLStmt:
    if term.value.startswith('"'):
        # Match the phase precisely.
        value = term.value[1:-1]
    else:
        value = term.value
    value = value.replace('*', '%')
    return "summary LIKE ?", (f'%{value}%',)


def build_sql(term: typing.Union[Term, typing.Tuple[Term, ...]]) -> SafeSQLStmt:
    # Return query and params to be used in SQL. query MUST not be produced using untrusted input, as is vulnerable to SQL injection.
    # Instead, any user input must be in the parameters, which undergoes sqllite built-in cleaning.
    if isinstance(term, tuple):
        if len(term) == 0:
            return '', ()

        # No known query can produce a multi-value term
        assert len(term) == 1
        return build_sql(term[0])

    if isinstance(term, Filter):
        if term.filter_on == FilterOn.name_or_summary:
            sql1, terms1 = prepare_name(term)
            sql2, terms2 = prepare_summary(term)
            return f"({sql1} OR {sql2})", terms1 + terms2
        elif term.filter_on == FilterOn.name:
            return prepare_name(term)
        elif term.filter_on == FilterOn.summary:
            return prepare_summary(term)
        else:
            raise ValueError(f"Unhandled filter on {term.filter_on}")
    elif isinstance(term, And):
        sql1, terms1 = build_sql(term.lhs)
        sql2, terms2 = build_sql(term.rhs)
        return f"({sql1} AND {sql2})", terms1 + terms2
    elif isinstance(term, Or):
        sql1, terms1 = build_sql(term.lhs)
        sql2, terms2 = build_sql(term.rhs)
        return f"({sql1} OR {sql2})", terms1 + terms2
    elif isinstance(term, Not):
        sql1, terms1 = build_sql(term.term)
        return f'(Not {sql1})', terms1
    else:
        raise ValueError(f"unknown term type {type(term)}")


def query_to_sql(query) -> SafeSQLStmt:
    terms = parse(query)
    return build_sql(terms)


grammar = parsley.makeGrammar(
    textwrap.dedent("""\
    quoted_string = '"' <(~'"' anything)*>:c '"' -> f'"{c}"'

    # Anything that looks like a Python package name. Note that wildcard (*) is supported.
    name_like = <letter (letterOrDigit | '-' | '_' | '.' | '*')*>

    # Allow specifying specific fields to filter on
    filter_on = (
        'name:' -> FilterOn.name
        |'summary:' -> FilterOn.summary
        | -> FilterOn.name_or_summary
    )

    # Either a quoted string, or a name-like
    filter_value = (quoted_string | name_like):term -> term

    filter = filter_on:filter_on filter_value:filter_value -> Filter(filter_on, filter_value)

    AND_OR = (ws 'AND' ws -> And
             |ws 'OR' ws -> Or
             |ws -> And)
    filters = (
            filters:lhs AND_OR:op filters:rhs -> op(lhs, rhs)
            |'(' ws? filters:filters ws? ')' -> filters
            |filter:filter -> filter
            |'-' filters:filters -> Not(filters)
    )
    search_terms = (filters+:filters -> tuple(filters)
                   | -> ())
    """),
    {
        'And': And,
        'Or': Or,
        'Filter': Filter,
        'Not': Not,
        'FilterOn': FilterOn,
    },
)


def parse(query: str) -> typing.Tuple[Term, ...]:
    return grammar(query.strip()).search_terms()


ParseError = parsley.ParseError


def simple_name_from_query(terms: typing.Tuple[Term, ...]) -> typing.Optional[str]:
    """If possible, give a simple (normalized) package name which represents the query terms provided"""
    for term in terms:
        if isinstance(term, Filter):
            if term.filter_on in [FilterOn.name_or_summary, FilterOn.name]:
                if '*' in term.value or '"' in term.value:
                    break
                return normalise_name(term.value)
        else:
            break
    return None
