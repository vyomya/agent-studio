#!/usr/bin/env bash
# Checks each free model key by listing models (costs no tokens).
# Usage:  set -a; source ~/agent-studio-secrets/.env; set +a; ./scripts/check-model-keys.sh
set -uo pipefail

check() {
  local name="$1" base="$2" key="${3:-}"
  if [ -z "$key" ]; then printf "%-11s SKIP (no key set)\n" "$name"; return; fi
  local body code
  body=$(mktemp)
  code=$(curl -s -o "$body" -w "%{http_code}" -H "Authorization: Bearer $key" "$base/models")
  if [ "$code" = "200" ]; then
    local n; n=$(jq '.data | length' "$body" 2>/dev/null || echo "?")
    printf "%-11s OK   (%s models)\n" "$name" "$n"
    if [ "$name" = "openrouter" ]; then
      jq -r '.data[].id | select(endswith(":free"))' "$body" | head -15 | sed 's/^/              free: /'
    else
      jq -r '.data[].id' "$body" 2>/dev/null | head -10 | sed 's/^/              /'
    fi
  else
    printf "%-11s FAIL (HTTP %s) %s\n" "$name" "$code" "$(head -c 200 "$body")"
  fi
  rm -f "$body"
}

check ollama     "https://ollama.com/v1"                                   "${OLLAMA_API_KEY:-}"
check gemini     "https://generativelanguage.googleapis.com/v1beta/openai" "${GEMINI_API_KEY:-}"
check groq       "https://api.groq.com/openai/v1"                          "${GROQ_API_KEY:-}"
check openrouter "https://openrouter.ai/api/v1"                            "${OPENROUTER_API_KEY:-}"
