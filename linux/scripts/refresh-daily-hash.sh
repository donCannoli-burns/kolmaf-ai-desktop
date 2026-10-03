#!/usr/bin/env bash
# ────────────────────────────────────────────────────────────
# scripts/refresh-daily-hash.sh
#
# Refreshes the KoLmafia daily pwd hash after the 19:30 MST
# rotation window. Run on login (via .bashrc) or via systemd
# timer / cron.
#
# Usage:
#   ./refresh-daily-hash.sh                   # auto-detect paths
#   KOLMAFA_HASH_STORE=/path ./refresh-daily-hash.sh
#   KOLMAFA_RELAY_BASE_URL=http://host:60080 ./refresh-daily-hash.sh
#
# Exit codes:
#   0 → hash is current or was updated
#   1 → relay unreachable or not logged in (transient, retry later)
#   2 → stored hash is malformed (manual intervention needed)
# ────────────────────────────────────────────────────────────
set -euo pipefail

# ── Configuration ──────────────────────────────────────────────────────────
HASH_STORE="${KOLMAFA_HASH_STORE:-$HOME/.kolmafia/daily-hash}"
META_STORE="${HASH_STORE}.meta"
RELAY_URL="${KOLMAFA_RELAY_BASE_URL:-http://localhost:60080}"
API_ENDPOINT="${RELAY_URL}/api.php?what=status&for=hash-refresh"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Help ────────────────────────────────────────────────────────────────────
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    echo "Usage: refresh-daily-hash.sh"
    echo ""
    echo "Refreshes the KoLmafia daily pwd hash after 19:30 MST rotation."
    echo ""
    echo "Environment variables:"
    echo "  KOLMAFA_HASH_STORE       Path to store the hash (default: ~/.kolmafia/daily-hash)"
    echo "  KOLMAFA_RELAY_BASE_URL   KoLmafia relay URL (default: http://localhost:60080)"
    exit 0
fi

# ── Time Check ──────────────────────────────────────────────────────────────
# Arizona is always MST (no DST). America/Phoenix is the canonical IANA zone.
# The KoLmafia pwd hash rotates at 19:30 MST daily. We wait 5 minutes past
# rotation (19:35) before refreshing to avoid racing the server-side rotation.

if command -v python3 &>/dev/null; then
    # Use Python for reliable cross-platform date arithmetic
    TIME_CHECK=$(python3 -c "
from datetime import datetime, timezone, timedelta
import os

# Arizona MST offset = -7 hours (no DST)
arizona_offset = timedelta(hours=-7)
now_utc = datetime.now(timezone.utc)
now_az = now_utc + arizona_offset

# Build 19:30 MST today
reset_az = now_az.replace(hour=19, minute=30, second=0, microsecond=0)

# If we're past midnight Arizona time, reset is for today
# If we're before 19:30, reset was yesterday
if now_az < reset_az:
    # Before rotation window. Refresh only if:
    #   - no hash file at all (first-ever boot), OR
    #   - hash exists but meta is missing (incomplete setup from earlier run)
    if os.path.exists('$HASH_STORE') and os.path.exists('$META_STORE'):
        # Both files exist, hash is from a previous day — wait for 19:30
        print('SKIP')
    else:
        # Missing meta = first-time setup or incomplete boot — force refresh
        print('REFRESH')
else:
    # Past 19:30 — check if we've already refreshed since rotation
    if os.path.exists('$META_STORE'):
        import json
        try:
            with open('$META_STORE') as f:
                meta = json.load(f)
            last_update = datetime.fromisoformat(meta.get('last_updated', '2000-01-01T00:00:00+00:00'))
            # If last update was before 19:30 today, refresh
            if last_update < reset_az.replace(tzinfo=timezone.utc) - timedelta(hours=7):
                # Actually compare in UTC
                reset_utc = reset_az.replace(tzinfo=timezone.utc) - arizona_offset
                if last_update < reset_utc:
                    print('REFRESH')
                else:
                    print('SKIP')
            else:
                print('SKIP')
        except Exception:
            print('REFRESH')
    else:
        print('REFRESH')
" 2>/dev/null || echo "REFRESH")
else
    # Fallback: shell-only time check (less precise)
    ARIZONA_HOUR=$(TZ='America/Phoenix' date +%H)
    ARIZONA_MIN=$(TZ='America/Phoenix' date +%M)
    ARIZONA_EPOCH=$(TZ='America/Phoenix' date +%s)

    # Convert 19:30 MST today to epoch
    RESET_DATE=$(TZ='America/Phoenix' date +%Y-%m-%d)
    RESET_EPOCH=$(TZ='America/Phoenix' date -d "${RESET_DATE} 19:30" +%s 2>/dev/null || echo 0)

    if [[ "$ARIZONA_EPOCH" -lt "$RESET_EPOCH" ]]; then
        # Before 19:30 — only refresh if no hash exists
        if [[ -f "$HASH_STORE" ]]; then
            TIME_CHECK="SKIP"
        else
            TIME_CHECK="REFRESH"
        fi
    else
        TIME_CHECK="REFRESH"
    fi
fi

if [[ "$TIME_CHECK" == "SKIP" ]]; then
    echo "[hash-refresh] Current hash is still valid. Next window: 19:30 MST."
    exit 0
fi

# ── Staleness Check ─────────────────────────────────────────────────────────
# If the stored hash is less than 1 hour old, don't re-fetch (anti-flap).
if [[ -f "$HASH_STORE" ]]; then
    HASH_AGE=$(($(date +%s) - $(stat -c %Y "$HASH_STORE" 2>/dev/null || echo 0)))
    if [[ "$HASH_AGE" -lt 3600 ]]; then
        echo "[hash-refresh] Hash was updated ${HASH_AGE}s ago — too recent, skipping."
        exit 0
    fi
fi

echo "[hash-refresh] Time window open. Fetching new hash..."

# ── Fetch the Hash from Relay ──────────────────────────────────────────────
HTTP_RESPONSE=$(curl -s -w "\n%{http_code}" --max-time 10 "$API_ENDPOINT" 2>/dev/null || true)
HTTP_BODY=$(echo "$HTTP_RESPONSE" | head -n -1)
HTTP_CODE=$(echo "$HTTP_RESPONSE" | tail -n1)

if [[ "$HTTP_CODE" != "200" ]]; then
    echo "[hash-refresh] Relay unreachable or not responding (HTTP $HTTP_CODE)."
    echo "[hash-refresh] Try: curl $API_ENDPOINT"
    exit 1
fi

# Extract pwd from JSON response
NEW_HASH=$(echo "$HTTP_BODY" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    pwd = data.get('pwd', '')
    if len(pwd) == 32 and all(c in '0123456789abcdef' for c in pwd):
        print(pwd)
    else:
        print('')
except Exception:
    print('')
" 2>/dev/null || echo "")

if [[ -z "$NEW_HASH" ]]; then
    echo "[hash-refresh] Could not extract valid pwd hash from relay response."
    echo "[hash-refresh] Response body:"
    echo "$HTTP_BODY" | head -c 500
    echo ""
    exit 1
fi

# ── Store ───────────────────────────────────────────────────────────────────
mkdir -p "$(dirname "$HASH_STORE")"
echo "$NEW_HASH" > "$HASH_STORE"
chmod 600 "$HASH_STORE"

# Write meta
cat > "$META_STORE" <<METAEOF
{
  "last_updated": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "rotation_window": "$(TZ='America/Phoenix' date -d 'tomorrow 19:30' +%Y-%m-%dT%H:%M:%S 2>/dev/null || TZ='America/Phoenix' date -d '+1 day 19:30' +%s 2>/dev/null)MST",
  "source": "relay-api",
  "player": "$(echo "$HTTP_BODY" | python3 -c "import sys,json; print(json.load(sys.stdin).get('name','unknown'))" 2>/dev/null || echo 'unknown')"
}
METAEOF
chmod 600 "$META_STORE"

echo "[hash-refresh] ✅ Hash updated: ${NEW_HASH:0:8}... (stored at $HASH_STORE)"
echo "[hash-refresh] Next rotation window: 19:30 MST daily."

# ── Update runtime mirror for Docker ────────────────────────────────────────
# If the project data/runtime directory exists, mirror the hash there
PROJECT_MIRROR="${SCRIPT_DIR}/../data/runtime/secrets/daily-hash"
if [[ -d "$(dirname "$PROJECT_MIRROR")" ]]; then
    mkdir -p "$(dirname "$PROJECT_MIRROR")"
    cp "$HASH_STORE" "$PROJECT_MIRROR"
    chmod 600 "$PROJECT_MIRROR"
    echo "[hash-refresh] Mirrored to $PROJECT_MIRROR"
fi

exit 0
