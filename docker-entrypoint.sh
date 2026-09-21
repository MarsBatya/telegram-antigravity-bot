#!/bin/bash
set -e

SETTINGS_DIR="/root/.gemini/antigravity-cli"
SETTINGS_FILE="${SETTINGS_DIR}/settings.json"
SESSIONS_FILE="${SESSION_FILE:-/app/data/sessions.json}"

# ── Ensure directories exist ──
mkdir -p "${SETTINGS_DIR}/brain"
mkdir -p "${DEFAULT_WORKSPACE:-/root/workspace}"
mkdir -p "$(dirname "${SESSIONS_FILE}")"

# ── Validate AGY_PATH inside container ──
if [ -n "${AGY_PATH}" ] && [ ! -e "${AGY_PATH}" ]; then
    echo "[entrypoint] AGY_PATH (${AGY_PATH}) not found in container → falling back to /root/.local/bin/agy"
    export AGY_PATH="/root/.local/bin/agy"
fi

# ── Create sessions.json if missing ──
if [ ! -f "${SESSIONS_FILE}" ]; then
    echo "[entrypoint] Creating empty $(basename "${SESSIONS_FILE}")"
    echo '{"conversations": {}, "workspaces": {}, "settings": {}}' > "${SESSIONS_FILE}"
fi

# ── GEMINI_API_KEY auto-configuration ──
if [ -n "${GEMINI_API_KEY}" ]; then
    echo "[entrypoint] GEMINI_API_KEY detected → configuring modelProvider=gemini"

    if [ -f "${SETTINGS_FILE}" ]; then
        python3 -c "
import json
with open('${SETTINGS_FILE}', 'r') as f:
    data = json.load(f)
data['modelProvider'] = 'gemini'
with open('${SETTINGS_FILE}', 'w') as f:
    json.dump(data, f, indent=2)
" 2>/dev/null || echo '{"modelProvider": "gemini"}' > "${SETTINGS_FILE}"
    else
        echo '{"modelProvider": "gemini"}' > "${SETTINGS_FILE}"
    fi
else
    echo "[entrypoint] No GEMINI_API_KEY → using OAuth token authentication"
    if [ -f "${SETTINGS_FILE}" ]; then
        python3 -c "
import json
with open('${SETTINGS_FILE}', 'r') as f:
    data = json.load(f)
if data.get('modelProvider') == 'gemini':
    del data['modelProvider']
    with open('${SETTINGS_FILE}', 'w') as f:
        json.dump(data, f, indent=2)
" 2>/dev/null || true
    fi
fi

# ── Proxy environment normalization ──
if [ -n "${HTTP_PROXY}" ] || [ -n "${HTTPS_PROXY}" ] || [ -n "${ALL_PROXY}" ]; then
    echo "[entrypoint] Proxy settings detected → normalizing proxy env vars for agy"
    PROXY_VAL="${HTTP_PROXY:-${HTTPS_PROXY:-${ALL_PROXY}}}"
    export HTTP_PROXY="${HTTP_PROXY:-${PROXY_VAL}}"
    export HTTPS_PROXY="${HTTPS_PROXY:-${PROXY_VAL}}"
    export ALL_PROXY="${ALL_PROXY:-${PROXY_VAL}}"
    export http_proxy="${http_proxy:-${HTTP_PROXY}}"
    export https_proxy="${https_proxy:-${HTTPS_PROXY}}"
    export all_proxy="${all_proxy:-${ALL_PROXY}}"
    export NO_PROXY="${NO_PROXY:-localhost,127.0.0.1,::1}"
    export no_proxy="${no_proxy:-${NO_PROXY}}"
fi

echo "[entrypoint] Starting bot..."
exec "$@"
