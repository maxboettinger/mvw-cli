import mvw


def test_package_has_version():
    assert isinstance(mvw.__version__, str)
    assert mvw.__version__
