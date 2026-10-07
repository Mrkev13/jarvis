"""Syntetické soubory .wotreplay pro testy (Game Enrichment C) – žádné skutečné replaye uživatele.

Tvar podle komunitně popsané struktury: signatura, počet bloků, bloky [délka + JSON], pak (zde náhodný) šifrovaný
zbytek, který parser nečte. Hodnoty odpovídají testovacím milníkům (Progetto 65 / ELC EVEN 90).
"""
from __future__ import annotations

import json
import struct
from datetime import datetime, timezone

MAGIC = b"\x12\x32\x34\x11"
TAIL = bytes(range(256)) * 4  # „šifrovaná" data – parser je ignoruje


def build(header: dict | None, results: list | None = None, *, magic: bytes = MAGIC, tail: bytes = TAIL,
          raw_blocks: list[bytes] | None = None) -> bytes:
    blocks = raw_blocks if raw_blocks is not None else [json.dumps(b, ensure_ascii=False).encode() for b in [header, results] if b is not None]
    out = magic + struct.pack("<I", len(blocks))
    for b in blocks:
        out += struct.pack("<I", len(b)) + b
    return out + tail


def header(vehicle="italy-It13_Progetto_M35_mod_46", map_display="Útesy", when="14.09.2026 20:15:03", player="Standa", team=1):
    return {
        "playerName": player, "playerID": 500000001, "playerVehicle": vehicle, "mapName": "18_cliff",
        "mapDisplayName": map_display, "dateTime": when, "gameplayID": "ctf", "battleType": 1,
        "clientVersionFromExe": "1, 26, 0, 0", "clientVersionFromXml": "ver. 1.26.0.0 #1234",
        "vehicles": {
            "11": {"name": player, "team": team, "vehicleType": vehicle.replace("-", ":", 1)},
            "12": {"name": "Soupeř", "team": 3 - team, "vehicleType": "ussr:R04_T-34"},
        },
    }


def results(damage=5205, radio=1500, track=254, kills=5, base_xp=1208, mark=4, team=1, winner=1, played=None, flat=False):
    stats = {"damageDealt": damage, "damageAssistedRadio": radio, "damageAssistedTrack": track, "damageAssistedStun": 90,
             "kills": kills, "originalXP": base_xp, "xp": base_xp * 2, "markOfMastery": mark, "team": team}
    played = played or datetime(2026, 9, 14, 18, 15, 3, tzinfo=timezone.utc)
    common = {"winnerTeam": winner, "arenaCreateTime": int(played.timestamp()), "duration": 412, "finishReason": 1}
    personal = stats if flat else {"avatar": {"credits": 1, "team": team}, "53809": stats}
    return [{"arenaUniqueID": 1234567890, "common": common, "personal": personal}, {"11": {}}, {"11": {"frags": kills}}]


PROGETTO = build(header(), results())
ELC = build(header("france-F97_ELC_EVEN_90", "Karelia", "20.09.2026 19:02:44"),
            results(damage=1594, radio=5100, track=875, kills=2, base_xp=1412, mark=4,
                    played=datetime(2026, 9, 20, 17, 2, 44, tzinfo=timezone.utc)))
PARTIAL = build(header("sweden-S16_Kranvagn", "Himmelsdorf", "11.07.2026 21:40:00"))  # nedohraná bitva: jen hlavička
UNSUPPORTED = MAGIC + struct.pack("<I", 2) + b"\xff" * 64  # signatura sedí, hlavička nečitelná
