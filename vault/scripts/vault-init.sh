#!/bin/sh
# vault/scripts/vault-init.sh
#
# Permanently auto-initializes and auto-unseals Vault on every container start.
#
# Key storage strategy:
#   - Unseal key + root token → /vault/data/.init-keys  (inside vault_data volume, persists forever)
#   - Root token only         → /vault/keys/root-token  (shared vault_keys volume, backends read this)
#
# Flow:
#   First boot  → init Vault, save keys, unseal, write token file
#   Every boot  → read saved keys, unseal if sealed, refresh token file

set -e

VAULT_ADDR="${VAULT_ADDR:-http://vault:8200}"
KEYS_FILE="/vault/data/.init-keys"
TOKEN_FILE="/vault/keys/root-token"

log() { printf '[vault-init] %s\n' "$*"; }

# ── 1. Wait for Vault TCP to be listening ─────────────────────────────────────
log "Waiting for Vault to start listening on $VAULT_ADDR ..."
RETRIES=0
while true; do
  vault status -address="$VAULT_ADDR" >/dev/null 2>&1
  RC=$?
  # RC=0  → initialized + unsealed
  # RC=2  → initialized + sealed   (still responsive — stop waiting)
  # RC=1  → connection refused / other error (keep waiting)
  [ "$RC" -eq 0 ] && break
  [ "$RC" -eq 2 ] && break
  RETRIES=$((RETRIES + 1))
  [ "$RETRIES" -ge 60 ] && log "ERROR: Vault did not start after 120s." && exit 1
  log "  Not ready yet (rc=$RC), retrying in 2s... ($RETRIES/60)"
  sleep 2
done
log "Vault is responding."

# ── 2. Read current status ────────────────────────────────────────────────────
STATUS_JSON=$(vault status -address="$VAULT_ADDR" -format=json 2>/dev/null || true)
INITIALIZED=$(echo "$STATUS_JSON" | grep '"initialized"' | grep -o 'true\|false' | head -1)
SEALED=$(echo       "$STATUS_JSON" | grep '"sealed"'      | grep -o 'true\|false' | head -1)

log "Status → initialized=$INITIALIZED  sealed=$SEALED"

# ── 3. Initialize (first boot only) ──────────────────────────────────────────
if [ "$INITIALIZED" != "true" ]; then
  log "Vault not initialized. Initializing with 1 key share / threshold 1..."

  INIT_JSON=$(vault operator init \
    -key-shares=1 \
    -key-threshold=1 \
    -format=json \
    -address="$VAULT_ADDR")

  # Parse key and token from JSON without requiring jq
  UNSEAL_KEY=$(echo "$INIT_JSON" | grep -o '"unseal_keys_b64":\["[^"]*"' | grep -o '"[^"]*"' | tail -1 | tr -d '"')
  ROOT_TOKEN=$(echo "$INIT_JSON" | grep -o '"root_token":"[^"]*"' | cut -d'"' -f4)

  log "Saving keys to $KEYS_FILE ..."
  printf 'UNSEAL_KEY=%s\nROOT_TOKEN=%s\n' "$UNSEAL_KEY" "$ROOT_TOKEN" > "$KEYS_FILE"
  chmod 600 "$KEYS_FILE"
  SEALED="true"  # freshly initialized vault is always sealed
  log "Initialized successfully."
fi

# ── 4. Load persisted keys ────────────────────────────────────────────────────
if [ ! -f "$KEYS_FILE" ]; then
  log "ERROR: Vault is initialized but $KEYS_FILE is missing!"
  log "       Delete the vault_data volume and restart to re-initialize."
  exit 1
fi

# shellcheck source=/dev/null
. "$KEYS_FILE"

# ── 5. Unseal if sealed ───────────────────────────────────────────────────────
if [ "$SEALED" = "true" ]; then
  log "Unsealing Vault..."
  vault operator unseal -address="$VAULT_ADDR" "$UNSEAL_KEY"
  log "Vault unsealed."
else
  log "Vault is already unsealed — nothing to do."
fi

# ── 6. Write root token to shared volume for backends ─────────────────────────
mkdir -p "$(dirname "$TOKEN_FILE")"
printf '%s' "$ROOT_TOKEN" > "$TOKEN_FILE"
chmod 600 "$TOKEN_FILE"
log "Root token written to $TOKEN_FILE"

log "Done — Vault is initialized, unsealed, and ready."
