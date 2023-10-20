from simple_repository import model

from simple_repository_browser.compatibility_matrix import compatibility_matrix


def test_compat_mtx__no_wheel():
    mtx = compatibility_matrix(
        (model.File("lxml-4.9.3.tar.gz", "", {}),),
    )
    assert mtx.py_and_abi_names == ()
    assert mtx.platform_names == ()
    assert mtx.matrix == {}


def test_compat_mtx__pure_wheel():
    mtx = compatibility_matrix(
        (model.File("cycler-0.12.1-py3-none-any.whl", "", {}),),
    )
    assert mtx.py_and_abi_names == ('Python 3',)
    assert mtx.platform_names == ('any',)
    assert tuple(mtx.matrix.keys()) == (('Python 3', 'any'),)


def test_compat_mtx__invalid_filename():
    files = [
        model.File("fake-4.9.3-madeup27-madeup2_7m-anything_you_like.whl", "", {}),
    ]

    mtx = compatibility_matrix(files)

    assert mtx.py_and_abi_names == ('madeup27 (madeup2_7m)',)
    assert mtx.platform_names == ('anything_you_like',)


def test_compat_mtx__pyqt6():
    files = [
        model.File("PyQt6-6.5.3-cp37-abi3-macosx_10_14_universal2.whl", "", {}),
        model.File("PyQt6-6.5.3-cp37-abi3-manylinux_2_28_x86_64.whl", "", {}),
        model.File("PyQt6-6.5.3-cp37-abi3-win_amd64.whl", "", {}),
        model.File("PyQt6-6.5.3.tar.gz", "", {}),
    ]

    mtx = compatibility_matrix(files)

    assert mtx.py_and_abi_names == ('CPython >=3.7 (abi3)',)
    assert mtx.platform_names == ('macosx_10_14_universal2', 'manylinux_2_28_x86_64', 'win_amd64')

    assert tuple(mtx.matrix.keys()) == (('CPython >=3.7 (abi3)', 'macosx_10_14_universal2'), ('CPython >=3.7 (abi3)', 'manylinux_2_28_x86_64'), ('CPython >=3.7 (abi3)', 'win_amd64'))


def test_compat_mtx__lxml_py2_flags():
    files = [
        model.File("lxml-4.9.3-cp27-cp27m-manylinux_2_5_i686.whl", "", {}),
        model.File("lxml-4.9.3-cp27-cp27mu-manylinux_2_5_i686.whl", "", {}),
        model.File("lxml-4.9.3-cp27-cp27du-manylinux_2_5_i686.manylinux1_i686.whl", "", {}),
    ]

    mtx = compatibility_matrix(files)

    assert mtx.py_and_abi_names == ('CPython 2.7', 'CPython (debug) (wide) 2.7', 'CPython (wide) 2.7')
    assert mtx.platform_names == ('manylinux1_i686', 'manylinux_2_5_i686')

    assert tuple(mtx.matrix.keys()) == (
        ('CPython 2.7', 'manylinux_2_5_i686'),
        ('CPython (wide) 2.7', 'manylinux_2_5_i686'),
        ('CPython (debug) (wide) 2.7', 'manylinux1_i686'),
        ('CPython (debug) (wide) 2.7', 'manylinux_2_5_i686'),
    )


def test_compat_mtx__unexpected_flags():
    files = [
        model.File("lxml-4.9.3-cp27-cp27abd-manylinux_2_5_i686.whl", "", {}),
    ]

    mtx = compatibility_matrix(files)

    assert mtx.py_and_abi_names == ('CPython (debug) (additional flags: ab) 2.7',)


def test_compat_mtx__underscore_version():
    files = [
        model.File("lxml-4.9.3-cp3_99-cp3_99d-manylinux_2_5_i686.whl", "", {}),
    ]

    mtx = compatibility_matrix(files)

    assert mtx.py_and_abi_names == ('CPython (debug) 3.99',)


def test_compat_mtx__lxml_pypy_flags():
    mtx = compatibility_matrix(
        (model.File("lxml-4.9.3-pp310-pypy310_pp73-manylinux_2_28_x86_64.whl", "", {}),),
    )
    assert mtx.py_and_abi_names == ('PyPy 3.10 (pp73)',)
    assert mtx.platform_names == ('manylinux_2_28_x86_64',)


def test_compat_mtx__none_abi():
    mtx = compatibility_matrix(
        (
            model.File(
                "pydantic_core-2.11.0-cp38-cp38-manylinux2014_x86_64.whl", "", {},
            ),
            model.File("pydantic_core-2.11.0-cp38-none-win32.whl", "", {}),
            model.File("pydantic_core-2.11.0-cp38-none-win_amd64.whl", "", {}),
        ),
    )
    assert mtx.py_and_abi_names == ('CPython 3.8',)
    assert mtx.platform_names == ('manylinux2014_x86_64', 'win32', 'win_amd64')


def test_compat_mtx__abi3_many_python():
    # A completely wild but real name. Specifying multiple Python targets makes no sense when
    # using abi3.
    mtx = compatibility_matrix(
        (
            model.File(
                "PyQt6-6.0.2-cp36.cp37.cp38.cp39-abi3-manylinux_2_28_x86_64.whl", "", {},
            ),
        ),
    )
    # In practice, this should be 1 ('py36_abi3', ), but no attempt has been made
    # to honour this (given how unnecessary it is).
    assert len(mtx.py_and_abi_names) == 4
