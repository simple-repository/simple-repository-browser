from simple_repository_browser.fetch_description import (
    Requirement,
    RequirementsSequence,
)


def test_extra__basic():
    s = RequirementsSequence((Requirement('foo'), Requirement('bar; extra == "bar"')))
    assert s.extras() == {'bar'}


def test_extras__multiple_specs():
    s = RequirementsSequence(
        (
            Requirement('bar; extra == "bar" and extra == "foo"'),
            Requirement('wobble; extra == "wibble"'),
        ),
    )
    assert s.extras() == {'bar', 'foo', 'wibble'}


def test_extras__2_extras_or():
    s = RequirementsSequence(
        (
            Requirement('foo'),
            Requirement('bar; extra == "bar" or extra == "foo"'),
        ),
    )
    assert s.extras() == {'bar', 'foo'}


def test_extras__2_extras_and():
    # Not realistic, but technically possible.
    s = RequirementsSequence((Requirement('bar; extra == "bar" and extra == "foo"'),))
    assert s.extras() == {'bar', 'foo'}


def test_extras__and_py_version():
    s = RequirementsSequence(
        (
            Requirement('foo'),
            Requirement('bar; extra == "bar" and python_version>="4.0"'),
        ),
    )
    assert s.extras() == {'bar'}


def test_extras__legacy_format():
    # As seen in cliff/2.10.0
    s = RequirementsSequence((Requirement("unicodecsv (>=0.8.0); (python_version<'3.0')"),))
    assert s.extras() == set()


def test_extras__none():
    s = RequirementsSequence((
        Requirement("foo; (os_name == 'nt' or sys_platform == 'linux') and python_version <= '3.8'"),
        Requirement("bar; python_version > '3.8'"),
    ))
    assert s.extras() == set()
