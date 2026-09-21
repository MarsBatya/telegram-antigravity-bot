from pathlib import Path
from typing import Any
import pytest

from app.core.model_manager import ModelManager
from app.core.storage import SessionStorage


@pytest.fixture
def storage(tmp_path: Path) -> SessionStorage:
    """Provides an isolated SessionStorage instance per test."""
    session_file = str(tmp_path / "sessions.json")
    return SessionStorage(file_path=session_file)


@pytest.fixture(autouse=True)
def isolate_model_manager(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolates ModelManager from running local CLI binaries or making
    external network requests during tests.
    """
    orig_cli = ModelManager.fetch_from_cli
    orig_cloudcode = ModelManager.fetch_from_cloudcode

    def _mock_fetch_cli(self: ModelManager) -> list[dict[str, Any]]:
        if getattr(self, "_allow_cli_fetch", False):
            return orig_cli(self)
        return []

    def _mock_fetch_cloudcode(
        self: ModelManager,
        token_file: str | None = None,
    ) -> list[dict[str, Any]]:
        if token_file is None:
            return []
        return orig_cloudcode(self, token_file)

    monkeypatch.setattr(ModelManager, "fetch_from_cli", _mock_fetch_cli)
    monkeypatch.setattr(ModelManager, "fetch_from_cloudcode", _mock_fetch_cloudcode)
