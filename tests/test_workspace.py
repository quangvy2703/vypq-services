import sys

import vypq_contracts


def test_python_version_is_312():
    assert sys.version_info[:2] == (3, 12)


def test_contracts_package_importable():
    assert vypq_contracts.__all__ == []
