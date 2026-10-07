"""Deterministický parser hlavičky souboru .wotreplay (Game Enrichment C). Žádné AI, žádné externí služby.

Formát není oficiálně dokumentovaný Wargamingem. Parser čte jen tu část, kterou popisují komunitní nástroje
(např. open-source „wotreplay-parser“ a převodníky replay → JSON) a kterou jde ověřit bez dešifrování:

    [4 B signatura 12 32 34 11][uint32 LE počet bloků N]
    N× [uint32 LE délka][blok – UTF-8 JSON]
    [zbytek: šifrovaný a komprimovaný záznam bitvy – parser ho NEČTE]

- blok 1 = JSON se začátkem bitvy: `playerVehicle` („ussr-R04_T-34“), `mapDisplayName`, `mapName`, `dateTime`
  („dd.mm.rrrr hh:mm:ss“, místní čas klienta), `clientVersionFromExe`, `playerName`, `vehicles`.
- blok 2 (jen u dohrané bitvy) = JSON pole, jehož první prvek jsou výsledky bitvy: `common.winnerTeam`,
  `common.arenaCreateTime`, `personal` (podle verze buď přímo statistiky, nebo slovník vozidel s `damageDealt`,
  `damageAssistedRadio`, `damageAssistedTrack`, `kills`, `originalXP`, `markOfMastery`, `team`).

Co nejde spolehlivě zjistit, se NEHÁDÁ: pole zůstane prázdné a výsledek nese varování. Stavy:
- parsed      – hlavička i výsledky bitvy přečtené,
- partial     – hlavička ano, výsledky ne (nedohraná bitva, jiný tvar) nebo část polí chybí,
- unsupported – signatura sedí, ale hlavičku nejde přečíst (nová verze formátu) → soubor se uloží, metadata ručně,
- invalid     – nejde o replay (žádná signatura ani čitelná struktura) → upload se odmítne.
"""
from __future__ import annotations

import json
import re
import struct
from dataclasses import dataclass, field
from datetime import datetime, timezone

from time_utils import APP_TZ

PARSER_VERSION = "1"
MAGIC = b"\x12\x32\x34\x11"
MAX_BLOCKS = 16
MAX_JSON_BLOCK = 8 * 1024 * 1024
STATUSES = ("parsed", "partial", "unsupported", "invalid")
MASTERY_BY_MARK = {4: "ace", 3: "first", 2: "second", 1: "third"}
# stejné meze jako u milníků (wot_service.FIELD_LIMITS) – hodnota mimo = chyba čtení, ne rekord
LIMITS = {"damage": 100_000, "assist": 100_000, "kills": 15, "base_xp": 10_000}
_VEHICLE_RE = re.compile(r"^([a-z]+)-([A-Za-z0-9_\-]{1,80})$")


@dataclass
class ReplayParseResult:
    status: str
    metadata: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    parser_version: str = PARSER_VERSION


def _read_blocks(data: bytes) -> list | None:
    """JSON bloky z hlavičky; None = struktura neodpovídá (žádný čitelný první blok)."""
    if len(data) < 12:
        return None
    (count,) = struct.unpack_from("<I", data, 4)
    if not 1 <= count <= MAX_BLOCKS:
        return None
    blocks: list = []
    pos = 8
    for _ in range(count):
        if pos + 4 > len(data):
            break
        (size,) = struct.unpack_from("<I", data, pos)
        pos += 4
        if size == 0 or size > MAX_JSON_BLOCK or pos + size > len(data):
            break
        try:
            blocks.append(json.loads(data[pos:pos + size].decode("utf-8")))
        except (UnicodeDecodeError, ValueError):
            break
        pos += size
    return blocks or None


def _int_in(value, limit: int) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= limit:
        return None
    return value


def _text(value, max_len: int) -> str | None:
    if not isinstance(value, str):
        return None
    v = "".join(ch for ch in value if ch.isprintable()).strip()
    return v[:max_len] or None


def _local_to_utc(raw) -> datetime | None:
    """„22.07.2026 18:31:05“ = místní čas klienta → bereme Europe/Prague (osobní aplikace), ukládá se naive UTC."""
    if not isinstance(raw, str):
        return None
    try:
        local = datetime.strptime(raw.strip(), "%d.%m.%Y %H:%M:%S")
    except ValueError:
        return None
    return local.replace(tzinfo=APP_TZ).astimezone(timezone.utc).replace(tzinfo=None)


def _version(header: dict) -> str | None:
    exe = header.get("clientVersionFromExe")
    if isinstance(exe, str) and re.fullmatch(r"\d+(,\s*\d+){1,4}", exe.strip()):
        return ".".join(p.strip() for p in exe.split(","))
    xml = _text(header.get("clientVersionFromXml"), 40)
    if xml:
        m = re.search(r"\d+(\.\d+){1,4}", xml)
        return m.group(0) if m else None
    return None


def _player_team(header: dict) -> int | None:
    name = header.get("playerName")
    vehicles = header.get("vehicles")
    if not isinstance(name, str) or not isinstance(vehicles, dict):
        return None
    teams = {v.get("team") for v in vehicles.values() if isinstance(v, dict) and v.get("name") == name}
    teams.discard(None)
    return teams.pop() if len(teams) == 1 else None


def _personal_stats(results: dict) -> dict | None:
    personal = results.get("personal")
    if not isinstance(personal, dict):
        return None
    if "damageDealt" in personal:
        return personal
    entries = [v for v in personal.values() if isinstance(v, dict) and "damageDealt" in v]
    return entries[0] if len(entries) == 1 else None


def parse_replay(data: bytes) -> ReplayParseResult:
    magic_ok = data[:4] == MAGIC
    blocks = _read_blocks(data)
    header = blocks[0] if blocks and isinstance(blocks[0], dict) else None
    if header is None:
        if magic_ok:
            return ReplayParseResult("unsupported", warnings=["Hlavičku replaye se nepodařilo přečíst (neznámá verze formátu)."])
        return ReplayParseResult("invalid", warnings=["Soubor nevypadá jako replay World of Tanks."])

    meta: dict = {}
    warnings: list[str] = []
    if not magic_ok:
        warnings.append("Neznámá signatura souboru – údaje zkontroluj.")

    m = _VEHICLE_RE.match(header.get("playerVehicle") or "")
    if m:
        meta["tank_tag"] = f"{m.group(1)}:{m.group(2)}"
    else:
        warnings.append("Tank se z hlavičky nepodařilo zjistit.")
    map_name = _text(header.get("mapDisplayName"), 100)
    if map_name:
        meta["map_name"] = map_name
    else:
        warnings.append("Název mapy chybí" + (f" (interní kód {_text(header.get('mapName'), 40)})." if _text(header.get("mapName"), 40) else "."))
    played = _local_to_utc(header.get("dateTime"))
    if played:
        meta["played_at"] = played
    version = _version(header)
    if version:
        meta["game_version"] = version

    results = blocks[1][0] if len(blocks) > 1 and isinstance(blocks[1], list) and blocks[1] and isinstance(blocks[1][0], dict) else None
    if results is None:
        warnings.append("Replay neobsahuje výsledky bitvy (nedohraná bitva nebo jiný formát) – statistiky doplň ručně.")
        return ReplayParseResult("partial", meta, warnings)

    stats = _personal_stats(results)
    common = results.get("common") if isinstance(results.get("common"), dict) else {}
    created = common.get("arenaCreateTime")
    if isinstance(created, (int, float)) and not isinstance(created, bool) and 1_262_304_000 <= created <= 4_102_444_800:
        meta["played_at"] = datetime.fromtimestamp(created, timezone.utc).replace(tzinfo=None)  # přesnější než čas klienta
    if stats is None:
        warnings.append("Osobní statistiky ve výsledcích chybí.")
        return ReplayParseResult("partial", meta, warnings)

    for key, src in (("damage", "damageDealt"), ("kills", "kills"), ("base_xp", "originalXP")):
        v = _int_in(stats.get(src), LIMITS[key])
        if v is not None:
            meta[key] = v
        else:
            warnings.append(f"Pole {key} se nepodařilo přečíst.")
    radio, track = stats.get("damageAssistedRadio"), stats.get("damageAssistedTrack")
    if _int_in(radio, LIMITS["assist"]) is not None and _int_in(track, LIMITS["assist"]) is not None:
        meta["assist"] = min(radio + track, LIMITS["assist"])  # spotování + pásy (stun se nepočítá)
    else:
        warnings.append("Pole assist se nepodařilo přečíst.")
    mark = stats.get("markOfMastery")
    if mark in MASTERY_BY_MARK:
        meta["mastery"] = MASTERY_BY_MARK[mark]
    elif mark != 0:
        warnings.append("Odznak zvládnutí se nepodařilo přečíst.")

    team = stats.get("team") if isinstance(stats.get("team"), int) else _player_team(header)
    winner = common.get("winnerTeam")
    if isinstance(winner, int) and not isinstance(winner, bool) and team is not None:
        meta["battle_result"] = "draw" if winner == 0 else ("win" if winner == team else "loss")
    else:
        warnings.append("Výsledek bitvy se nepodařilo určit.")

    complete = all(k in meta for k in ("tank_tag", "map_name", "damage", "kills", "assist", "base_xp", "battle_result"))
    return ReplayParseResult("parsed" if complete else "partial", meta, warnings)
