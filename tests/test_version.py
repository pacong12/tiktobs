"""Sanity checks for the application version used in versioned exe builds."""

import re

from app.version import __version__, get_version


def test_version_is_semver_like():
    assert re.match(r"^\d+\.\d+\.\d+", __version__), __version__


def test_get_version_matches():
    assert get_version() == __version__


def test_build_script_reads_same_version():
    import build_exe

    assert build_exe.read_version() == __version__


def test_version_tuple_pads_and_parses():
    import build_exe

    assert build_exe.version_tuple("1.2.3") == (1, 2, 3, 0)
    assert build_exe.version_tuple("1.2.3-beta") == (1, 2, 3, 0)
    assert build_exe.version_tuple("2.0", length=4) == (2, 0, 0, 0)
