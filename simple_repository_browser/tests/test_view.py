# Copyright (C) 2023, CERN
# This software is distributed under the terms of the MIT
# licence, copied verbatim in the file "LICENSE".
# In applying this license, CERN does not waive the privileges and immunities
# granted to it by virtue of its status as Intergovernmental Organization
# or submit itself to any jurisdiction.

from packaging.requirements import Requirement

from simple_repository_browser.view import render_markers


def test_view_format__no_markers():
    req = Requirement(
        "foo",
    )

    result = render_markers(
        req, format_strings={
            'expr': "{lhs} :{op}: {rhs}",
        },
    )
    assert result == ''


def test_view_format__simple_extra():
    req = Requirement(
        "foo; extra == 'blah'",
    )

    result = render_markers(
        req, format_strings={
            'expr': "{lhs} :{op}: {rhs}",
        },
    )
    expected = 'extra :==: "blah"'

    assert result == expected


def test_view_format__nested():
    req = Requirement(
        "foo; (os_name == 'nt' or sys_platform == 'linux') and python_version <= '3.8'",
    )

    result = render_markers(
        req, format_strings={
            'combine_nested_expr': "[{lhs}] [{op}] [{rhs}]",
            'group_expr': '<<{expr}>>',
            'expr': "|{lhs}/ |{op}/ |{rhs}/",
        },
    )
    expected = (
        '[<<[|os_name/ |==/ |"nt"/] [or] [|sys_platform/ |==/ |"linux"/]>>] '
        '[and] [|python_version/ |<=/ |"3.8"/]'
    )

    assert result == expected


def test_view_format__simple_extra_plus_os():
    req = Requirement(
        "foo; python_version <= '3.8' and extra == 'blah'",
    )

    result = render_markers(
        req, format_strings={
            'expr': "{lhs} :{op}: {rhs}",
            'combine_nested_expr': '{lhs} @{op}@ {rhs}',
        },
    )
    expected = 'python_version :<=: "3.8" @and@ extra :==: "blah"'

    assert result == expected
