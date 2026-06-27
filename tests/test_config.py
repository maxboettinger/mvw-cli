from mvw.config import DEFAULTS, load, set_value


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
