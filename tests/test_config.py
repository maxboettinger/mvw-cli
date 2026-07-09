import pytest

from mvw.config import DEFAULTS, ConfigError, load, set_value


def test_load_missing_returns_defaults(tmp_path):
    cfg = load(tmp_path / "none.toml")
    assert cfg["resolution"] == DEFAULTS["resolution"]
    assert cfg["page_size"] == 50


def test_set_then_load_roundtrip_with_coercion(tmp_path):
    p = tmp_path / "config.toml"
    set_value("resolution", "high", p)
    set_value("page_size", "25", p)
    cfg = load(p)
    assert cfg["resolution"] == "high"
    assert cfg["page_size"] == 25  # coerced to int


def test_load_invalid_toml_raises_config_error(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text("not = = valid")
    with pytest.raises(ConfigError, match=r"config\.toml"):
        load(p)


def test_set_value_unknown_key_raises(tmp_path):
    with pytest.raises(ConfigError, match="unknown config key"):
        set_value("pagesize", "50", tmp_path / "config.toml")


def test_set_value_bad_int_raises(tmp_path):
    with pytest.raises(ConfigError, match="page_size"):
        set_value("page_size", "abc", tmp_path / "config.toml")


def test_set_value_bad_float_raises(tmp_path):
    with pytest.raises(ConfigError, match="request_timeout"):
        set_value("request_timeout", "soon", tmp_path / "config.toml")


def test_set_value_on_corrupt_file_raises(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text("not = = valid")
    with pytest.raises(ConfigError, match=r"config\.toml"):
        set_value("resolution", "high", p)


def test_default_user_agent_tracks_package_version():
    import mvw

    assert DEFAULTS["user_agent"] == f"mvw/{mvw.__version__}"
