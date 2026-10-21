#!/usr/bin/env bash
# Ping every model Agent Studio depends on with one tiny chat request, and show the OpenAI budget.
# Models are read from agents/agents.conf (the agent team) and deploy/.env (the live site), so the list is always
# the one actually in use. Keys are read from the env files and never printed. Cost: a few hundred tokens in total.
#   sudo bash scripts/check-models.sh
set -uo pipefail
[ "$(id -u)" = 0 ] || { echo "Run with sudo (the env files are readable by root only)." >&2; exit 1; }

ROOT="${AGENT_STUDIO_ROOT:-/srv/agent-studio}"
CONF="${CONF:-$ROOT/agents/agents.conf}"
AGENTS_ENV="${AGENTS_ENV:-$ROOT/.env}"
PRODUCT_ENV="${PRODUCT_ENV:-/home/ubuntu/agent-studio/deploy/.env}"
LEDGER="$ROOT/ledger/usage.jsonl"

OLLAMA_BASE="https://ollama.com/v1"
OPENAI_BASE="https://api.openai.com/v1"
GEMINI_BASE="https://generativelanguage.googleapis.com/v1beta/openai"

# value of KEY in FILE, tolerant of "export", spaces around "=", and quotes; last one wins
get() { sed -nE "s/^[[:space:]]*(export[[:space:]]+)?$1[[:space:]]*=[[:space:]]*//p" "$2" 2>/dev/null | tail -1 \
        | sed -E "s/^\"(.*)\"\$/\\1/; s/^'(.*)'\$/\\1/"; }

OLLAMA_KEY="$(get OLLAMA_API_KEY "$AGENTS_ENV")"
OPENAI_KEY="$(get OPENAI_API_KEY "$AGENTS_ENV")"
GEMINI_KEY="$(get GEMINI_API_KEY "$AGENTS_ENV")"
[ -n "$GEMINI_KEY" ] || GEMINI_KEY="$(get GOOGLE_API_KEY "$AGENTS_ENV")"

ping_model() {  # label base_url key model
  local label="$1" base="$2" key="$3" model="$4" body code t reply msg
  if [ -z "$key" ]; then printf '  %-44s SKIP  no key found\n' "$label"; return; fi
  body="$(mktemp)"
  read -r code t < <(curl -sS -o "$body" -w '%{http_code} %{time_total}\n' --max-time 90 \
      -H "Authorization: Bearer $key" -H 'Content-Type: application/json' \
      -d "$(jq -nc --arg m "$model" '{model:$m, messages:[{role:"user",content:"Reply with the single word OK."}]}')" \
      "$base/chat/completions" 2>/dev/null || echo "000 0")
  if [ "$code" = 200 ]; then
    reply="$(jq -r '(.choices[0].message.content // "") | gsub("\\s+"; " ") | .[0:30]' "$body" 2>/dev/null)"
    printf '  %-44s OK    %5.1fs  %s\n' "$label" "$t" "${reply:-(empty reply, still reachable)}"
  else
    msg="$(jq -r '(if type == "array" then .[0] else . end)
                  | ((.error | if type == "object" then .message else . end) // .message // empty)' "$body" 2>/dev/null \
           | tr '\n' ' ' | head -c 140)"
    [ -n "$msg" ] || msg="$(head -c 140 "$body" | tr '\n' ' ')"
    [ "$code" = 000 ] && msg="no answer in 90 s (network or timeout)"
    printf '  %-44s FAIL  HTTP %s  %s\n' "$label" "$code" "$msg"
  fi
  rm -f "$body"
}

# ---------- 1. agent team models, from agents.conf ----------
echo "== Agent team models ($CONF)"
# shellcheck disable=SC1090
. "$CONF"
declare -A WHO
add() {  # provider model who; "openai/x" and "google/x" carry their provider in the name
  local p="$1" m="$2"
  if [[ "$m" == */* ]]; then p="${m%%/*}"; m="${m#*/}"; fi
  case "$p" in ollama*) p=ollama ;; openai*) p=openai ;; google*|gemini*) p=gemini ;; esac
  WHO["$p|$m"]="${WHO["$p|$m"]:+${WHO["$p|$m"]}, }$3"
}
for a in $AGENTS; do
  v="AGENT_${a//-/_}"; pr="${v}_PROVIDER"; mo="${v}_MODEL"; fb="${v}_FALLBACK"
  add "${!pr:-}" "${!mo:-}" "$a"
  [ -n "${!fb:-}" ] && add "" "${!fb}" "$a fallback"
done
for k in $(printf '%s\n' "${!WHO[@]}" | sort); do
  p="${k%%|*}"; m="${k#*|}"
  case "$p" in
    ollama) ping_model "ollama   $m" "$OLLAMA_BASE" "$OLLAMA_KEY" "$m" ;;
    openai) ping_model "openai   $m" "$OPENAI_BASE" "$OPENAI_KEY" "$m" ;;
    gemini) ping_model "gemini   $m" "$GEMINI_BASE" "$GEMINI_KEY" "$m" ;;
    *)      printf '  %-44s SKIP  unknown provider\n' "$p $m" ;;
  esac
  printf '  %-44s       used by: %s\n' "" "${WHO[$k]}"
done

# ---------- 2. live site models, from deploy/.env ----------
echo; echo "== Live site models ($PRODUCT_ENV)"
if [ -r "$PRODUCT_ENV" ]; then
  echo "  GENERATOR_PROVIDER=$(get GENERATOR_PROVIDER "$PRODUCT_ENV")  MODEL_TIMEOUT_SECONDS=$(get MODEL_TIMEOUT_SECONDS "$PRODUCT_ENV")"
  for side in PRIMARY FALLBACK; do
    ping_model "$(printf '%-8s %s' "$(echo "$side" | tr 'A-Z' 'a-z')" "$(get "${side}_MODEL" "$PRODUCT_ENV")")" \
      "$(get "${side}_BASE_URL" "$PRODUCT_ENV")" "$(get "${side}_API_KEY" "$PRODUCT_ENV")" "$(get "${side}_MODEL" "$PRODUCT_ENV")"
  done
else
  echo "  cannot read $PRODUCT_ENV (set PRODUCT_ENV=/path/to/deploy/.env)"
fi

# ---------- 3. OpenAI budget, computed exactly as wake.sh does ----------
echo; echo "== OpenAI budget (builders)"
spent="$(jq -s --argjson pin "${OPENAI_PRICE_IN:-0.10}" --argjson pc "${OPENAI_PRICE_CACHED:-0.01}" \
            --argjson pout "${OPENAI_PRICE_OUT:-0.50}" '
    [.[] | select(.provider == "openai")
         | ((.prompt_tokens // 0) * $pin + (.cache_read_tokens // 0) * $pc + (.completion_tokens // 0) * $pout) / 1000000]
    | add // 0' "$LEDGER" 2>/dev/null || echo 0)"
printf '  spent $%.2f of the $%s cap; when the cap is reached the builders switch to their Gemini fallback\n' \
  "$spent" "${OPENAI_BUDGET_USD:-?}"
echo; echo "Quotas that only the web consoles show:"
echo "  Ollama Cloud allowance: https://ollama.com/settings"
echo "  OpenAI usage and credit: https://platform.openai.com/usage"
echo "  Gemini rate limits:      https://aistudio.google.com/usage"