import os
import re
from urllib.parse import urlsplit, urlunsplit

from app.core import config


class PathMapper:
    """Maps long absolute paths to short tokens to keep callback_data
    well under Telegram's 64-byte limit.
    """

    def __init__(self) -> None:
        self._to_token: dict[str, str] = {}
        self._to_path: dict[str, str] = {}
        self._counter: int = 0

    def encode(self, path: str) -> str:
        norm = os.path.abspath(path)
        if norm in self._to_token:
            return self._to_token[norm]
        self._counter += 1
        token = f"p{self._counter}"
        self._to_token[norm] = token
        self._to_path[token] = norm
        return token

    def decode(self, token: str) -> str | None:
        return self._to_path.get(token)


path_mapper = PathMapper()


def mask_proxy_url(url: str | None) -> str:
    """Masks sensitive password/credentials in proxy URLs for safe logging/display."""
    if not url:
        return ""
    try:
        parts = urlsplit(url)
        if parts.password:
            user = parts.username or ""
            host = parts.hostname or ""
            port_str = f":{parts.port}" if parts.port else ""
            masked_netloc = f"{user}:***@{host}{port_str}"
            return urlunsplit(
                (parts.scheme, masked_netloc, parts.path, parts.query, parts.fragment),
            )
    except Exception:  # noqa: S110
        pass
    return url


def make_progress_bar(percent: float, length: int = 10) -> str:
    filled = int(round(length * percent / 100))
    filled = max(0, min(length, filled))
    bar = "█" * filled + "░" * (length - filled)
    return f"[{bar}] {percent:.1f}%"


def format_file_size(size_bytes: int | float) -> str:
    """Formats bytes into human-readable size string (B, KB, MB, GB)."""
    if size_bytes < 1024:
        return f"{int(size_bytes)} B"
    if size_bytes < 1024 * 1024:
        return f"{round(size_bytes / 1024, 1)} KB"
    if size_bytes < 1024 * 1024 * 1024:
        return f"{round(size_bytes / (1024 * 1024), 1)} MB"
    return f"{round(size_bytes / (1024 * 1024 * 1024), 1)} GB"


def is_authorized(user_id: int) -> bool:
    if not config.ALLOWED_USER_IDS:
        return False
    return user_id in config.ALLOWED_USER_IDS


_HTML_TAG_RE = re.compile(r"<\/?([a-zA-Z0-9-]+)(?:\s+[^>]*?)?\/?>")


def _chunk_text_safely(text: str, max_length: int = 3800) -> list[str]:
    """Splits text into chunks strictly under max_length, breaking oversized lines."""
    raw_lines = text.split("\n")
    lines: list[str] = []
    for line in raw_lines:
        if len(line) <= max_length:
            lines.append(line)
        else:
            for i in range(0, len(line), max_length):
                lines.append(line[i : i + max_length])

    chunks: list[str] = []
    curr_chunk: list[str] = []
    curr_len = 0

    for line in lines:
        added_len = len(line) + (1 if curr_chunk else 0)
        if curr_len + added_len > max_length:
            if curr_chunk:
                chunks.append("\n".join(curr_chunk))
            curr_chunk = [line]
            curr_len = len(line)
        else:
            curr_chunk.append(line)
            curr_len += added_len

    if curr_chunk:
        chunks.append("\n".join(curr_chunk))
    return chunks


def balance_html_chunks(chunks: list[str]) -> list[str]:
    """Ensures each chunk has balanced HTML tags so Telegram parsing never crashes."""
    balanced_chunks: list[str] = []
    open_stack: list[tuple[str, str]] = []

    for chunk in chunks:
        # Re-open any tags carried over from the previous chunk
        prefix = "".join(full_tag for _, full_tag in open_stack)
        current_content = prefix + chunk

        current_stack: list[tuple[str, str]] = []
        for match in _HTML_TAG_RE.finditer(current_content):
            raw_tag = match.group(0)
            tag_name = match.group(1).lower()
            if raw_tag.endswith("/>"):
                continue
            if raw_tag.startswith("</"):
                for i in range(len(current_stack) - 1, -1, -1):
                    if current_stack[i][0] == tag_name:
                        current_stack.pop(i)
                        break
            else:
                current_stack.append((tag_name, raw_tag))

        closing = "".join(f"</{tag}>" for tag, _ in reversed(current_stack))
        balanced_chunks.append(current_content + closing)
        open_stack = current_stack

    return balanced_chunks
