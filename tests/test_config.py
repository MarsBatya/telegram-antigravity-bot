import os
from unittest.mock import patch

import config


def test_parse_allowed_user_ids_empty():
    assert config.parse_allowed_user_ids("") == []
    assert config.parse_allowed_user_ids(None) == []


def test_parse_allowed_user_ids_valid():
    assert config.parse_allowed_user_ids("12345") == [12345]
    assert config.parse_allowed_user_ids("123,456,789") == [123, 456, 789]
    assert config.parse_allowed_user_ids("  123 ,  456  ,  789  ") == [123, 456, 789]


def test_parse_allowed_user_ids_with_invalid_items():
    raw = "123, abc, -45, , 678, 90a"
    assert config.parse_allowed_user_ids(raw) == [123, 678]


def test_validate_config_valid():
    assert (
        config.validate_config(token="123456:valid_token", allowed_users=[12345])  # noqa: S106
        is True
    )


def test_validate_config_empty_token():
    assert config.validate_config(token="", allowed_users=[12345]) is False
    assert (
        config.validate_config(token="your_bot_token_here", allowed_users=[12345])  # noqa: S106
        is False
    )


def test_validate_config_empty_users():
    # Still returns True even when allowed_users is empty (with a warning)
    assert config.validate_config(token="123456:valid_token", allowed_users=[]) is True  # noqa: S106


def test_config_constants():
    assert config.DEFAULT_MODEL == "gemini-3.6-flash-high"
    assert config.DEFAULT_EFFORT == "high"
    assert config.DEFAULT_MODE == "accept-edits"
    assert "SYSTEM DIRECTIVE" in config.SYSTEM_PERSONA_PROMPT


def test_get_default_agy_path():
    with patch.dict("os.environ", {"AGY_PATH": "/custom/path/to/agy"}):
        assert config._get_default_agy_path() == "/custom/path/to/agy"

    with (
        patch.dict("os.environ", {"AGY_PATH": ""}),
        patch("shutil.which", return_value="/usr/bin/agy"),
    ):
        assert config._get_default_agy_path() == "/usr/bin/agy"

    with (
        patch.dict("os.environ", {"AGY_PATH": ""}),
        patch("shutil.which", return_value=None),
        patch("os.path.exists", return_value=True),
    ):
        assert ".local/bin/agy" in config._get_default_agy_path()


def test_default_paths_portable():
    home = os.path.expanduser("~")
    if home != "/root":
        assert "/root/" not in config.DEFAULT_WORKSPACE
        assert "/root/" not in config.BRAIN_DIR
        assert "/root/" not in config.OAUTH_TOKEN_PATH


def test_normalize_proxy_url():
    assert config.normalize_proxy_url(None) is None
    assert config.normalize_proxy_url("") is None
    assert config.normalize_proxy_url("   ") is None
    assert (
        config.normalize_proxy_url("http://127.0.0.1:8080") == "http://127.0.0.1:8080"
    )
    assert (
        config.normalize_proxy_url("https://proxy.example.com:8443")
        == "https://proxy.example.com:8443"
    )
    assert (
        config.normalize_proxy_url("socks5://127.0.0.1:1080")
        == "socks5://127.0.0.1:1080"
    )
    assert (
        config.normalize_proxy_url("socks4://127.0.0.1:1080")
        == "socks4://127.0.0.1:1080"
    )
    assert config.normalize_proxy_url("127.0.0.1:8080") == "http://127.0.0.1:8080"
    assert (
        config.normalize_proxy_url("  proxy.local:3128  ") == "http://proxy.local:3128"
    )


def test_get_http_proxy():
    clean_env = {
        "HTTP_PROXY": "",
        "http_proxy": "",
        "HTTPS_PROXY": "",
        "https_proxy": "",
    }
    with patch.dict("os.environ", clean_env):
        assert config.get_http_proxy() is None

    with patch.dict("os.environ", {**clean_env, "HTTP_PROXY": "http://10.0.0.1:8080"}):
        assert config.get_http_proxy() == "http://10.0.0.1:8080"

    with patch.dict("os.environ", {**clean_env, "http_proxy": "10.0.0.2:8080"}):
        assert config.get_http_proxy() == "http://10.0.0.2:8080"

    with patch.dict(
        "os.environ",
        {**clean_env, "HTTPS_PROXY": "socks5://10.0.0.3:1080"},
    ):
        assert config.get_http_proxy() == "socks5://10.0.0.3:1080"

    with patch.dict("os.environ", {**clean_env, "https_proxy": "http://10.0.0.4:8080"}):
        assert config.get_http_proxy() == "http://10.0.0.4:8080"
