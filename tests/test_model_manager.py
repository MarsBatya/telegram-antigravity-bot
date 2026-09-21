import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.core.model_manager import ModelManager, normalize_model_name


def test_normalize_model_name() -> None:
    assert normalize_model_name("Gemini 3.8 Flash (High)") == "gemini-3.8-flash-high"
    assert normalize_model_name("gemini-3.8-flash-high") == "gemini-3.8-flash-high"
    assert normalize_model_name(" Claude 3.5 Sonnet ") == "claude-3.5-sonnet"


def test_model_manager_resolve_model_id() -> None:
    custom_models = [
        {"id": "gemini-3.8-flash-high", "displayName": "Gemini 3.8 Flash (High)"},
        {
            "id": "gemini-3.8-flash-medium",
            "displayName": "Gemini 3.8 Flash (Medium)",
        },
        {"id": "gemini-3.7-flash-high", "displayName": "Gemini 3.7 Flash (High)"},
        {"id": "claude-sonnet-4-6", "displayName": "Claude Sonnet 4.6 (Thinking)"},
    ]
    mgr = ModelManager(fallback_models=custom_models)

    # Exact ID match
    assert mgr.resolve_model_id("gemini-3.8-flash-high") == "gemini-3.8-flash-high"

    # Shorthand missing "-flash"
    assert mgr.resolve_model_id("gemini-3.8-high") == "gemini-3.8-flash-high"
    assert mgr.resolve_model_id("3.8-high") == "gemini-3.8-flash-high"

    # Display name match
    assert (
        mgr.resolve_model_id("Gemini 3.8 Flash (Medium)") == "gemini-3.8-flash-medium"
    )
    assert mgr.resolve_model_id("Claude Sonnet 4.6") == "claude-sonnet-4-6"

    # Unknown model fallback as-is
    assert mgr.resolve_model_id("custom-local-model") == "custom-local-model"


def test_model_manager_caching() -> None:
    mgr = ModelManager(cache_ttl=60.0)
    mock_models = [{"id": "test-model-1", "displayName": "Test Model 1"}]

    with patch.object(mgr, "fetch_from_cli", return_value=mock_models) as mock_cli:
        # First call hits CLI
        models1 = mgr.get_available_models()
        assert models1 == mock_models
        assert mock_cli.call_count == 1

        # Second call within TTL hits cache
        models2 = mgr.get_available_models()
        assert models2 == mock_models
        assert mock_cli.call_count == 1

        # Clear cache forces refetch
        mgr.clear_cache()
        models3 = mgr.get_available_models()
        assert models3 == mock_models
        assert mock_cli.call_count == 2


def test_model_manager_cloudcode_tiered_parsing() -> None:
    mgr = ModelManager()
    data = {
        "models": {
            "gemini-3.8-flash-tiered": {
                "supportsThinking": True,
                "recommended": True,
            },
            "custom-pro": {
                "displayName": "Custom Pro",
                "recommended": False,
            },
        },
    }
    parsed = mgr._parse_cloudcode_models(data)
    ids = [m["id"] for m in parsed]
    assert "gemini-3.8-flash-high" in ids
    assert "gemini-3.8-flash-medium" in ids
    assert "gemini-3.8-flash-low" in ids
    assert "custom-pro" in ids


def test_model_manager_fetch_with_token_file(tmp_path: Path) -> None:
    token_file = str(tmp_path / "token.json")
    mgr = ModelManager()

    # Missing file returns []
    assert mgr.get_available_models(token_file=str(tmp_path / "missing")) == []

    # Valid token file
    with open(token_file, "w", encoding="utf-8") as f:
        json.dump({"token": {"access_token": "ya29.mock"}}, f)

    fake_api_response = {
        "models": {
            "model-x": {"displayName": "Model X", "recommended": True},
        },
    }
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(fake_api_response).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        res = mgr.get_available_models(token_file=token_file)
        assert len(res) == 1
        assert res[0]["id"] == "model-x"
