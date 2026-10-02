#!/usr/bin/env bash
# Atomic UAT release activation/rollback. Run only under approved change control.
set -euo pipefail

ROOT="${FUTURE_RELEASE_ROOT:-/opt/future/releases}"
CURRENT="${FUTURE_CURRENT_LINK:-/opt/future/current}"
SERVICE="${FUTURE_SERVICE_NAME:-future-backend}"
ACTION="${1:-}"
VALUE="${2:-}"

fail() { echo "ERROR: $*" >&2; exit 1; }
health() { curl --fail --silent --show-error http://127.0.0.1:8000/health >/dev/null; }

case "$ACTION" in
  activate)
    [ -n "$VALUE" ] || fail "Usage: $0 activate <release-directory>"
    TARGET="$(realpath "$VALUE")"
    case "$TARGET" in "$ROOT"/release_*) ;; *) fail "Release must be under $ROOT and start with release_" ;; esac
    [ -f "$TARGET/manifest.json" ] || fail "Release manifest missing"
    PREVIOUS="$(readlink -f "$CURRENT" 2>/dev/null || true)"
    ln -sfn "$TARGET" "${CURRENT}.next"
    mv -Tf "${CURRENT}.next" "$CURRENT"
    if ! sudo systemctl restart "$SERVICE" || ! health; then
      [ -n "$PREVIOUS" ] || fail "Activation failed and no previous release exists"
      ln -sfn "$PREVIOUS" "${CURRENT}.next"
      mv -Tf "${CURRENT}.next" "$CURRENT"
      sudo systemctl restart "$SERVICE"
      health || fail "Automatic rollback health check failed"
      fail "Activation failed; previous release restored"
    fi
    echo "$PREVIOUS" > "$TARGET/previous-release.txt"
    echo "Activated $TARGET"
    ;;
  rollback)
    ACTIVE="$(readlink -f "$CURRENT" 2>/dev/null || true)"
    [ -n "$ACTIVE" ] || fail "No active release symlink"
    [ -f "$ACTIVE/previous-release.txt" ] || fail "Previous release record missing"
    PREVIOUS="$(cat "$ACTIVE/previous-release.txt")"
    case "$PREVIOUS" in "$ROOT"/release_*) ;; *) fail "Unsafe previous release path" ;; esac
    [ -f "$PREVIOUS/manifest.json" ] || fail "Previous release manifest missing"
    ln -sfn "$PREVIOUS" "${CURRENT}.next"
    mv -Tf "${CURRENT}.next" "$CURRENT"
    sudo systemctl restart "$SERVICE"
    health || fail "Rollback health check failed"
    echo "Rolled back from $ACTIVE to $PREVIOUS"
    ;;
  *)
    fail "Usage: $0 {activate <release-directory>|rollback}"
    ;;
esac
