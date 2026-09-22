import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

from app.core import config

DEFAULT_MODELS_FALLBACK: list[dict[str, Any]] = [
    {"id": "gemini-3.8-flash-high", "displayName": "Gemini 3.8 Flash (High)"},
    {"id": "gemini-3.8-flash-medium", "displayName": "Gemini 3.8 Flash (Medium)"},
    {"id": "gemini-3.8-flash-low", "displayName": "Gemini 3.8 Flash (Low)"},
    {"id": "gemini-3.7-flash-high", "displayName": "Gemini 3.7 Flash (High)"},
    {"id": "gemini-3.7-flash-medium", "displayName": "Gemini 3.7 Flash (Medium)"},
    {"id": "gemini-3.7-flash-low", "displayName": "Gemini 3.7 Flash (Low)"},
    {"id": "gemini-3.6-flash-high", "displayName": "Gemini 3.6 Flash (High)"},
    {"id": "gemini-3.6-flash-medium", "displayName": "Gemini 3.6 Flash (Medium)"},
    {"id": "gemini-3.6-flash-low", "displayName": "Gemini 3.6 Flash (Low)"},
    {"id": "gemini-3.1-pro-high", "displayName": "Gemini 3.1 Pro (High)"},
    {"id": "gemini-3.1-pro-low", "displayName": "Gemini 3.1 Pro (Low)"},
    {"id": "claude-sonnet-4-6", "displayName": "Claude Sonnet 4.6 (Thinking)"},
    {"id": "claude-opus-4-6-thinking", "displayName": "Claude Opus 4.6 (Thinking)"},
    {"id": "gpt-oss-120b-medium", "displayName": "GPT-OSS 120B (Medium)"},
]


def normalize_model_name(name: str) -> str:
    """Normalizes a model name or identifier for fuzzy comparison."""
    return re.sub(r"[^a-z0-9\-\.]+", "-", name.lower()).strip("-")


class ModelManager:
    """Encapsulates AI model catalog discovery, tiered expansion, caching,
    and resolution.
    """

    def __init__(
        self,
        cache_ttl: float = 300.0,
        agy_path: str | None = None,
        fallback_models: list[dict[str, Any]] | None = None,
    ) -> None:
        self.cache_ttl = cache_ttl
        self.agy_path = agy_path
        self.fallback_models = list(fallback_models) if fallback_models is not None else list(DEFAULT_MODELS_FALLBACK)
        self._cache: list[dict[str, Any]] = []
        self._cache_time: float = 0.0

    def clear_cache(self) -> None:
        """Invalidates the internal model catalog cache."""
        self._cache = []
        self._cache_time = 0.0

    def fetch_from_cli(self) -> list[dict[str, Any]]:
        """Queries the agy CLI directly for canonical supported models."""
        agy_bin = self.agy_path or shutil.which("agy") or getattr(config, "AGY_PATH", "agy")
        if not agy_bin or not shutil.which(agy_bin):
            return []
        try:
            is_win = sys.platform == "win32"
            use_shell = is_win and agy_bin.lower().endswith((".cmd", ".bat"))
            res = subprocess.run(  # noqa: S603
                [agy_bin, "models"],
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
                shell=use_shell,
            )
            if res.returncode != 0:
                return []
            models: list[dict[str, Any]] = []
            for line in res.stdout.splitlines():
                line_str = line.strip()
                if not line_str:
                    continue
                parts = line_str.split("\t", 1)
                if len(parts) == 2:
                    mid, disp = parts[0].strip(), parts[1].strip()
                elif "  " in line_str:
                    split_parts = [p.strip() for p in line_str.split(None, 1)]
                    if len(split_parts) == 2:
                        mid, disp = split_parts[0], split_parts[1]
                    else:
                        continue
                else:
                    continue
                if mid and disp:
                    models.append(
                        {
                            "id": mid,
                            "displayName": disp,
                            "supportsThinking": "thinking" in disp.lower()
                            or "flash" in mid.lower()
                            or "pro" in mid.lower(),
                            "recommended": True,
                        },
                    )
            return models
        except Exception as e:
            print(f"[WARN] ModelManager.fetch_from_cli: {e}")
            return []

    def _parse_cloudcode_models(
        self,
        data: dict[str, Any],
    ) -> list[dict[str, Any]]:
        models: list[dict[str, Any]] = []
        seen_ids: set[str] = set()

        for m_id, m_info in data.get("models", {}).items():
            disp = m_info.get("displayName")
            thinking = m_info.get("supportsThinking", False)
            rec = m_info.get("recommended", False)
            if m_id.endswith("-tiered"):
                base_id = m_id[:-7]
                base_disp = disp or " ".join(
                    w.upper() if w.lower() in ("gpt", "oss", "ai") else w.capitalize() for w in base_id.split("-")
                )
                for tier, tier_name in [
                    ("high", "High"),
                    ("medium", "Medium"),
                    ("low", "Low"),
                ]:
                    tier_id = f"{base_id}-{tier}"
                    if tier_id not in seen_ids:
                        seen_ids.add(tier_id)
                        models.append(
                            {
                                "id": tier_id,
                                "displayName": f"{base_disp} ({tier_name})",
                                "supportsThinking": thinking,
                                "recommended": rec,
                            },
                        )
            elif disp and m_id not in seen_ids:
                seen_ids.add(m_id)
                models.append(
                    {
                        "id": m_id,
                        "displayName": disp,
                        "supportsThinking": thinking,
                        "recommended": rec,
                    },
                )

        models.sort(
            key=lambda x: (
                not x.get("recommended", False),
                x.get("displayName", ""),
            ),
        )
        return models

    def fetch_from_cloudcode(
        self,
        token_file: str | None = None,
    ) -> list[dict[str, Any]]:
        """Queries Google CloudCode API directly for model definitions."""
        default_token_path = str(
            Path.home() / ".gemini" / "antigravity-cli" / "antigravity-oauth-token",
        )
        target_token_file = token_file or getattr(
            config,
            "OAUTH_TOKEN_PATH",
            default_token_path,
        )
        if not os.path.exists(target_token_file):
            return []

        try:
            with open(target_token_file, "r", encoding="utf-8") as f:
                token_data = json.load(f)

            access_token = token_data.get("token", {}).get("access_token")
            if not access_token:
                return []

            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
                "User-Agent": "antigravity-cli/1.2.7",
            }

            base_url = getattr(
                config,
                "CLOUDCODE_BASE_URL",
                "https://daily-cloudcode-pa.googleapis.com",
            ).rstrip("/")
            url = f"{base_url}/v1internal:fetchAvailableModels"
            req = urllib.request.Request(  # noqa: S310
                url,
                data=b"{}",
                headers=headers,
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
                data = json.loads(resp.read().decode("utf-8"))

            return self._parse_cloudcode_models(data)
        except Exception as e:
            print(f"[ERROR] ModelManager.fetch_from_cloudcode: {e}")
            return []

    def get_available_models(
        self,
        token_file: str | None = None,
        force_refresh: bool = False,
    ) -> list[dict[str, Any]]:
        """Retrieves available models with caching, CLI discovery, and
        CloudCode fallback.
        """
        # If an explicit token file is provided, query CloudCode directly
        if token_file is not None:
            return self.fetch_from_cloudcode(token_file=token_file)

        if not force_refresh and self._cache and (time.time() - self._cache_time < self.cache_ttl):
            return list(self._cache)

        # 1. Try CLI first when no explicit token_file specified
        cli_models = self.fetch_from_cli()
        if cli_models:
            self._cache = list(cli_models)
            self._cache_time = time.time()
            return cli_models

        # 2. Try CloudCode API
        cloud_models = self.fetch_from_cloudcode(token_file=None)
        if cloud_models:
            self._cache = list(cloud_models)
            self._cache_time = time.time()
            return cloud_models

        # 3. If everything fails, return fallback models
        return list(self.fallback_models)

    def resolve_model_id(
        self,
        query: str,
        available_models: list[dict[str, Any]] | None = None,
    ) -> str:
        """Resolves a user-provided model query or shorthand to a valid model ID."""
        cleaned = query.strip()
        norm = normalize_model_name(cleaned)
        models = available_models if available_models is not None else self.get_available_models()

        # 1. Exact ID or without "-flash"
        for m in models:
            mid = m["id"]
            mid_low = mid.lower()
            if mid_low == norm or mid_low == cleaned.lower():
                return mid
            if mid_low.replace("-flash", "") == norm:
                return mid

        # 2. Match against display name or partial string
        for m in models:
            mid = m["id"]
            disp_norm = normalize_model_name(m.get("displayName", ""))
            if disp_norm == norm or disp_norm.replace("-flash", "") == norm:
                return mid
            mid_clean = mid.lower().replace("-flash", "")
            if norm in mid.lower() or norm in disp_norm or norm in mid_clean:
                return mid

        return cleaned
