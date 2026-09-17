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
    assert config.validate_config(token="123456:valid_token", allowed_users=[12345]) is True


def test_validate_config_empty_token():
    assert config.validate_config(token="", allowed_users=[12345]) is False
    assert config.validate_config(token="your_bot_token_here", allowed_users=[12345]) is False


def test_validate_config_empty_users():
    # Still returns True even when allowed_users is empty (with a warning)
    assert config.validate_config(token="123456:valid_token", allowed_users=[]) is True


def test_config_constants():
    assert config.DEFAULT_MODEL == "gemini-3.6-flash-high"
    assert config.DEFAULT_EFFORT == "high"
    assert config.DEFAULT_MODE == "accept-edits"
    assert "SYSTEM DIRECTIVE" in config.SYSTEM_PERSONA_PROMPT
