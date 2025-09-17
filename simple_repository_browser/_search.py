from __future__ import annotations

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
    name = "name"
    summary = "summary"
    name_or_summary = "name_or_summary"


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


@dataclasses.dataclass(frozen=True)
class SQLBuilder:
    """Immutable SQL WHERE and ORDER BY clauses with parameters."""

    where_clause: str
    where_params: tuple[typing.Any, ...]
    order_clause: str
    order_params: tuple[typing.Any, ...]
    search_context: SearchContext

    def build_complete_query(
        self,
        base_select: str,
        limit: int,
        offset: int,
    ) -> tuple[str, tuple[typing.Any, ...]]:
        """Build complete query with LIMIT/OFFSET"""
        where_part = f"WHERE {self.where_clause}" if self.where_clause else ""
        query = f"{base_select} {where_part} {self.order_clause} LIMIT ? OFFSET ?"
        return query, self.where_params + self.order_params + (limit, offset)

    def with_where(self, clause: str, params: tuple[typing.Any, ...]) -> SQLBuilder:
        """Return new SQLBuilder with updated WHERE clause"""
        return dataclasses.replace(self, where_clause=clause, where_params=params)

    def with_order(self, clause: str, params: tuple[typing.Any, ...]) -> SQLBuilder:
        """Return new SQLBuilder with updated ORDER BY clause"""
        return dataclasses.replace(self, order_clause=clause, order_params=params)


@dataclasses.dataclass(frozen=True)
class SearchContext:
    """Context collected during WHERE clause building."""

    exact_names: tuple[str, ...] = ()
    fuzzy_patterns: tuple[str, ...] = ()

    def with_exact_name(self, name: str) -> SearchContext:
        """Add an exact name match."""
        if name in self.exact_names:
            return self
        else:
            return dataclasses.replace(self, exact_names=self.exact_names + (name,))

    def with_fuzzy_pattern(self, pattern: str) -> SearchContext:
        """Add a fuzzy search pattern."""
        if pattern in self.fuzzy_patterns:
            return self
        else:
            return dataclasses.replace(
                self, fuzzy_patterns=self.fuzzy_patterns + (pattern,)
            )

    def merge(self, other: SearchContext) -> SearchContext:
        """Merge contexts from multiple terms (for OR/AND)."""
        names = self.exact_names + tuple(
            name for name in other.exact_names if name not in self.exact_names
        )
        patterns = self.fuzzy_patterns + tuple(
            pattern
            for pattern in other.fuzzy_patterns
            if pattern not in self.fuzzy_patterns
        )

        return dataclasses.replace(self, exact_names=names, fuzzy_patterns=patterns)


class SearchCompiler:
    """Extensible visitor-pattern compiler for search terms to SQL.

    Uses AST-style method dispatch: visit_TermName maps to handle_term_TermName.
    Subclasses can override specific handlers for customisation.
    """

    @classmethod
    def compile(cls, term: Term | None) -> SQLBuilder:
        """Compile search terms into SQL WHERE and ORDER BY clauses."""
        if term is None:
            return SQLBuilder(
                where_clause="",
                where_params=(),
                order_clause="",
                order_params=(),
                search_context=SearchContext(),
            )

        # Build WHERE clause and collect context
        context = SearchContext()
        where_clause, where_params, final_context = cls._visit_term(term, context)

        # Build ORDER BY clause based on collected context
        order_clause, order_params = cls._build_ordering_from_context(final_context)

        return SQLBuilder(
            where_clause=where_clause,
            where_params=where_params,
            order_clause=order_clause,
            order_params=order_params,
            search_context=final_context,
        )

    @classmethod
    def _visit_term(
        cls, term: Term, context: SearchContext
    ) -> tuple[str, tuple[typing.Any, ...], SearchContext]:
        """Dispatch to appropriate handler using AST-style method naming."""
        method_name = f"handle_term_{type(term).__name__}"
        handler = getattr(cls, method_name, None)
        if handler is None:
            raise ValueError(f"No handler for term type {type(term).__name__}")
        return handler(term, context)

    # AST-style handlers for term types
    @classmethod
    def handle_term_Filter(
        cls, term: Filter, context: SearchContext
    ) -> tuple[str, tuple[typing.Any, ...], SearchContext]:
        """Dispatch to field-specific filter handler."""
        match term.filter_on:
            case FilterOn.name_or_summary:
                return cls.handle_filter_name_or_summary(term, context)
            case FilterOn.name:
                return cls.handle_filter_name(term, context)
            case FilterOn.summary:
                return cls.handle_filter_summary(term, context)
            case _:
                raise ValueError(f"Unhandled filter on {term.filter_on}")

    @classmethod
    def handle_term_And(
        cls, term: And, context: SearchContext
    ) -> tuple[str, tuple[typing.Any, ...], SearchContext]:
        """Handle AND logic between terms."""
        lhs_sql, lhs_params, lhs_context = cls._visit_term(term.lhs, context)
        rhs_sql, rhs_params, rhs_context = cls._visit_term(term.rhs, context)

        merged_context = lhs_context.merge(rhs_context)
        return f"({lhs_sql} AND {rhs_sql})", lhs_params + rhs_params, merged_context

    @classmethod
    def handle_term_Or(
        cls, term: Or, context: SearchContext
    ) -> tuple[str, tuple[typing.Any, ...], SearchContext]:
        """Handle OR logic between terms."""
        lhs_sql, lhs_params, lhs_context = cls._visit_term(term.lhs, context)
        rhs_sql, rhs_params, rhs_context = cls._visit_term(term.rhs, context)

        merged_context = lhs_context.merge(rhs_context)
        return f"({lhs_sql} OR {rhs_sql})", lhs_params + rhs_params, merged_context

    @classmethod
    def handle_term_Not(
        cls, term: Not, context: SearchContext
    ) -> tuple[str, tuple[typing.Any, ...], SearchContext]:
        """Handle NOT logic."""
        inner_sql, inner_params, _ = cls._visit_term(term.term, context)
        return f"(NOT {inner_sql})", inner_params, context

    @classmethod
    def handle_filter_name(
        cls, term: Filter, context: SearchContext
    ) -> tuple[str, tuple[typing.Any, ...], SearchContext]:
        """Handle name filtering."""
        if term.value.startswith('"'):
            # Exact quoted match
            value = term.value[1:-1]
            normalised = normalise_name(value)
            new_context = context.with_exact_name(normalised)
            return "canonical_name = ?", (normalised,), new_context
        else:
            normalised = normalise_name(term.value)
            if "*" in term.value:
                # Fuzzy wildcard search - respect wildcard position
                # "numpy*" > "numpy%", "*numpy" > "%numpy", "*numpy*" > "%numpy%"
                pattern = normalised.replace("*", "%")
                new_context = context.with_fuzzy_pattern(pattern)
                return "canonical_name LIKE ?", (pattern,), new_context
            else:
                # Simple name search
                new_context = context.with_exact_name(normalised)
                return "canonical_name LIKE ?", (f"%{normalised}%",), new_context

    @classmethod
    def handle_filter_summary(
        cls, term: Filter, context: SearchContext
    ) -> tuple[str, tuple[typing.Any, ...], SearchContext]:
        """Handle summary filtering."""
        if term.value.startswith('"'):
            value = term.value[1:-1]
        else:
            value = term.value
        value = value.replace("*", "%")
        return "summary LIKE ?", (f"%{value}%",), context

    @classmethod
    def handle_filter_name_or_summary(
        cls, term: Filter, context: SearchContext
    ) -> tuple[str, tuple[typing.Any, ...], SearchContext]:
        """Handle filtering across both name and summary fields."""
        name_sql, name_params, name_context = cls.handle_filter_name(term, context)
        summary_sql, summary_params, _ = cls.handle_filter_summary(term, context)

        combined_sql = f"({name_sql} OR {summary_sql})"
        combined_params = name_params + summary_params
        return combined_sql, combined_params, name_context

    @classmethod
    def _build_ordering_from_context(
        cls, context: SearchContext
    ) -> tuple[str, tuple[typing.Any, ...]]:
        """Build mixed ordering for exact names and fuzzy patterns.

        For "scipy or scikit-*", the ordering is:
        1. Exact matches get closeness-based priority (scipy, scipy2, etc.)
        2. Fuzzy matches get length-based priority (scikit-learn, scikit-image, etc.)
        3. Everything else alphabetical
        """

        exact_names, fuzzy_patterns = context.exact_names, context.fuzzy_patterns
        order_parts = []
        all_params = []

        # Build single comprehensive CASE statement for priority
        case_conditions = []

        # Add exact match conditions (priority 0)
        for name in exact_names:
            case_conditions.append(f"WHEN canonical_name = ? THEN 0")
            all_params.append(name)

        # Add fuzzy pattern conditions (priority 1)
        for pattern in fuzzy_patterns:
            case_conditions.append(f"WHEN canonical_name LIKE ? THEN 1")
            all_params.append(f"%{pattern}%")

        # Add exact-related conditions (priority 2)
        for name in exact_names:
            case_conditions.append(f"WHEN canonical_name LIKE ? THEN 2")  # prefix
            case_conditions.append(f"WHEN canonical_name LIKE ? THEN 2")  # suffix
            all_params.extend([f"{name}%", f"%{name}"])

        if case_conditions:
            priority_expr = f"""
                CASE
                    {chr(10).join(case_conditions)}
                    ELSE 3
                END
            """
            order_parts.append(priority_expr)

        # Length-based ordering for fuzzy matches (reuse same pattern logic)
        if fuzzy_patterns:
            length_conditions = []
            for pattern in fuzzy_patterns:
                length_conditions.append(f"canonical_name LIKE ?")
                all_params.append(f"%{pattern}%")

            length_expr = f"CASE WHEN ({' OR '.join(length_conditions)}) THEN LENGTH(canonical_name) ELSE 999999 END"
            order_parts.append(length_expr)

        # Prefix distance for exact names
        if exact_names:
            distance_conditions = []
            for name in exact_names:
                distance_conditions.append(
                    f"WHEN INSTR(canonical_name, ?) > 0 THEN (INSTR(canonical_name, ?) - 1)"
                )
                all_params.extend([name, name])

            if distance_conditions:
                cond = "\n".join(distance_conditions)
                distance_expr = f"""
                    CASE
                        {cond}
                        ELSE 999999
                    END
                """
                order_parts.append(distance_expr)

        # Alphabetical fallback
        order_parts.append("canonical_name")

        order_clause = f"ORDER BY {', '.join(order_parts)}"
        return order_clause, tuple(all_params)


def build_sql(term: Term | None) -> SQLBuilder:
    """Build SQL WHERE and ORDER BY clauses from search terms."""
    return SearchCompiler.compile(term)


def query_to_sql(query) -> SQLBuilder:
    term = parse(query)
    return build_sql(term)


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
    search_terms = (filters:filters -> filters
                   | -> None)
    """),
    {
        "And": And,
        "Or": Or,
        "Filter": Filter,
        "Not": Not,
        "FilterOn": FilterOn,
    },
)


def parse(query: str) -> Term | None:
    return grammar(query.strip()).search_terms()


ParseError = parsley.ParseError
