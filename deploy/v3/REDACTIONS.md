# MRK-108 v3 – redakce produkčních souborů

Zdroj: root-owned instalace na Ubuntu serveru.

Původní soubory nebyly změněny.

## Změny

U následujících souborů byl konkrétní tailnet hostname
nahrazen zástupcem `<tailnet-host>`:

- `lib/auto-update-v2.sh` – 1 výskyt
- `lib/auto-update-v3.sh` – 1 výskyt
- `lib/deploy-transaction-mrk108.sh` – 1 výskyt
- `lib/deploy-transaction-v2.sh` – 1 výskyt
- `lib/deploy-transaction-v3.sh` – 1 výskyt
- `mrk108/frontend-original.yaml` – 1 výskyt

## Ověření

- 21 původních souborů ověřeno pomocí SHA-256.
- Žádné jiné obsahové úpravy nebyly provedeny.
- Originální kontrolní součty jsou v SHA256SUMS.original.
- Zástupné hodnoty jsou auditní; nejsou produkční konfigurací.
- Secrets a lokální konfigurace se do Gitu neukládají.
