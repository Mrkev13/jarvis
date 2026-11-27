#!/usr/bin/env bash
# MRK-151: stav posledního běhu updateru pro Hub (oznámení „Nasazení čeká na migraci“ / „se zastavilo“).
#
# Spouští ho systemd jako ExecStopPost= jednotky standa-hub-auto-update.service (drop-in 30-status.conf), tedy po
# KAŽDÉM běhu, i neúspěšném. Čte jen journal TOHOTO běhu ($INVOCATION_ID) a zapíše malý JSON bez tajemství:
#   {"at": UTC, "state": "ok"|"blocked"|"waiting", "reason": "MIGRATION_HEAD_CHANGED"|"BACKUP_NOT_FRESH"|
#    "DEPLOY_FAILED"|"", "target": <40 hex>}
# do $UPDATER_STATUS_DIR (výchozí /srv/standa-hub-data/backups/ops = /data/backups/ops v backend kontejneru, už
# připojené – žádná změna compose šablony). Backend ho jen čte (backend/deploy_notice.py).
# Nikdy neselže běh updateru: každá chyba = nic nezapsat, exit 0. Žádné hostname, URL ani výstup příkazů do souboru.
set -uo pipefail

OUT_DIR=${UPDATER_STATUS_DIR:-/srv/standa-hub-data/backups/ops}
inv=${INVOCATION_ID:-}
[[ $inv =~ ^[0-9a-f]{32}$ ]] || exit 0

log=$(journalctl -q --no-pager -o cat "_SYSTEMD_INVOCATION_ID=$inv" 2>/dev/null) || exit 0
target=$(sed -n 's/^Target: *\([0-9a-f]\{40\}\)$/\1/p' <<<"$log" | tail -n 1)
[[ $target =~ ^[0-9a-f]{40}$ ]] || exit 0   # běh skončil dřív, než zjistil cíl – nic nehlásit

if grep -q 'MIGRATION_HEAD_CHANGED' <<<"$log"; then
  state=blocked; reason=MIGRATION_HEAD_CHANGED
elif grep -Eq 'CI_NOT_FOUND|CI_NOT_APPROVED' <<<"$log"; then
  state=waiting; reason=''                    # CI nové verze ještě běží – běžný přechodný stav
elif grep -Eq 'BACKUP_(NOT_FOUND|NOT_SUCCESSFUL|TOO_OLD|FILE_MISSING|SIZE_MISMATCH|CHECKSUM_MISMATCH)' <<<"$log"; then
  state=blocked; reason=BACKUP_NOT_FRESH
elif [[ ${SERVICE_RESULT:-} == success ]]; then
  state=ok; reason=''
else
  state=blocked; reason=DEPLOY_FAILED
fi

mkdir -p -- "$OUT_DIR" 2>/dev/null && chmod 755 -- "$OUT_DIR" 2>/dev/null || exit 0
tmp=$(mktemp "$OUT_DIR/.status.XXXXXXXX" 2>/dev/null) || exit 0
printf '{"at": "%s", "state": "%s", "reason": "%s", "target": "%s"}\n' \
  "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$state" "$reason" "$target" >"$tmp" &&
  chmod 644 -- "$tmp" && mv -f -- "$tmp" "$OUT_DIR/updater-status.json" || rm -f -- "$tmp"
exit 0
