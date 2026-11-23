"""Ověří Blizzard Battle.net API pro WoW modul (MRK-127) – klíče, token a který profile namespace zná tvou postavu.

Spouští se na serveru v backend kontejneru, např.:
    docker exec -it standa-hub-backend python scripts/check_battlenet.py --realm "Pyrewood Village" --name Thrall

Vypisuje JEN stavové řádky: jestli jsou klíče nastavené, výsledek tokenu a pro každý namespace HTTP stav a která pole
API vrací (level, item level, profese, kolekce). Nikdy nevypíše klíče, token, jméno postavy ani realm.
Doporučený `WOW_NAMESPACE` = ten, kde je postava `200`.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

CANDIDATES = ("profile-{r}", "profile-classic1x-{r}", "profile-classicann-{r}", "profile-classic-{r}")


def _status(fn) -> tuple[str, dict | None]:
    from modules.wow import battlenet
    try:
        return "200", fn()
    except battlenet.BattleNetError as err:
        return {"not_found": "404", "unauthorized": "401/403", "rate_limited": "429"}.get(err.code, err.code), None
    except Exception:  # noqa: BLE001 - nikdy traceback (mohl by nést URL)
        return "chyba", None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--env-file", type=Path, help="chráněný produkční env soubor (jinak prostředí procesu)")
    parser.add_argument("--realm", required=True, help="realm postavy (nevypisuje se)")
    parser.add_argument("--name", required=True, help="jméno postavy (nevypisuje se)")
    args = parser.parse_args(argv)
    if args.env_file:
        from production import load_production_environment
        load_production_environment(str(args.env_file))
    from modules.wow import battlenet, service

    cfg = battlenet.load_config()
    if cfg is None:
        has_keys = bool(os.environ.get("BATTLENET_CLIENT_ID")) and bool(os.environ.get("BATTLENET_CLIENT_SECRET"))
        print("KLÍČE: " + ("nastavené, ale WOW_REGION / WOW_NAMESPACE je neplatný" if has_keys else "CHYBÍ (BATTLENET_CLIENT_ID / _SECRET)"))
        return 1
    print(f"KLÍČE: nastavené · region {cfg.region} · WOW_NAMESPACE {cfg.namespace}")
    try:
        slug = service.realm_slug(args.realm)
        _display, key = service.normalize_name(args.name)
    except service.WowError as err:
        print(f"VSTUP: {err.message}")
        return 1
    status, _ = _status(lambda: battlenet._access_token(cfg, battlenet.requests.request, battlenet.time.monotonic))
    print(f"TOKEN: {'ok' if status == '200' else status}")
    if status != "200":
        return 1
    found = []
    for ns in dict.fromkeys([cfg.namespace] + [c.format(r=cfg.region) for c in CANDIDATES]):
        cli = battlenet.Client(battlenet.Config(cfg.client_id, cfg.client_secret, cfg.region, ns, cfg.locale))
        status, data = _status(lambda: cli.character(slug, key))
        if data is None:
            print(f"{ns}: postava {status}")
            continue
        found.append(ns)
        fields = [f for f in ("level", "character_class", "race", "equipped_item_level", "average_item_level",
                              "active_spec", "last_login_timestamp") if f in data]
        prof_status, _ = _status(lambda: cli._get(cli._char_path(slug, key) + "/professions"))
        mounts_status, _ = _status(lambda: cli._get(cli._char_path(slug, key) + "/collections/mounts"))
        ach_status, _ = _status(lambda: cli._get(cli._char_path(slug, key) + "/achievements/statistics"))
        print(f"{ns}: postava 200 · pole {', '.join(fields) or '–'} · profese {prof_status} · mounty {mounts_status}"
              f" · achievementy {ach_status}")
    if found:
        print(f"DOPORUČENÍ: WOW_NAMESPACE={found[0]}")
        return 0
    print("DOPORUČENÍ: postava se nenašla v žádném namespace – zkontroluj realm a jméno")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
