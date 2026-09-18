from pathlib import Path
import pytest

from storage import SessionStorage


@pytest.fixture
def storage(tmp_path: Path) -> SessionStorage:
    """Provides an isolated SessionStorage instance per test."""
    session_file = str(tmp_path / "sessions.json")
    return SessionStorage(file_path=session_file)
