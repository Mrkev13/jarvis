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


# ---- Tvar skutečných replayů klienta 2.x (ověřeno lokálně na reálných souborech uživatele, binárky se necommitují) ----
# Rozdíly proti syntetice výše: clientVersionFromExe s tečkami a zastaralou poslední číslicí („2.4.0.0"), přesná verze
# jen v clientVersionFromXml s NBSP („World of Tanks v.2.4.0.1 #952"); výsledky klíčované typeCompDescr vedle „avatar";
# xp / factualXP už vynásobené prémií, základní XP = originalXP; achievementXP a stun/smoke/inspire asistence existují.
def real_header(vehicle, map_code, map_display, when, version_exe, version_xml, player_team):
    return {
        "playerName": "Standa", "playerID": 500000001, "playerVehicle": vehicle, "mapName": map_code,
        "mapDisplayName": map_display, "dateTime": when, "gameplayID": "ctf", "battleType": 1, "regionCode": "EU",
        "clientVersionFromExe": version_exe, "clientVersionFromXml": version_xml,
        "vehicles": {
            "11": {"name": "Standa", "team": player_team, "vehicleType": vehicle.replace("-", ":", 1)},
            "12": {"name": "Soupeř", "team": 3 - player_team, "vehicleType": "ussr:R04_T-34"},
        },
    }


def real_results(type_comp, *, team, winner, damage, radio, track, kills, original_xp, xp, achievement_xp, mark, created):
    stats = {"typeCompDescr": type_comp, "team": team, "damageDealt": damage, "damageAssistedRadio": radio,
             "damageAssistedTrack": track, "damageAssistedStun": 0, "damageAssistedSmoke": 0, "damageAssistedInspire": 0,
             "kills": kills, "xp": xp, "originalXP": original_xp, "factualXP": xp, "achievementXP": achievement_xp,
             "premiumXPFactor100": 150, "markOfMastery": mark, "spotted": 1}
    common = {"winnerTeam": winner, "finishReason": 1, "duration": 600, "arenaCreateTime": created, "bonusType": 1}
    return [{"arenaUniqueID": 1, "common": common, "personal": {str(type_comp): stats, "avatar": {"team": team}},
             "vehicles": {}}, {}, {}]


NBSP = " "
# ELC EVEN 90 (Karélie, výhra, Mistr) – verze z exe zaostává (2.4.0.0), skutečná 2.4.0.1
REAL_ELC = build(real_header("france-F97_ELC_EVEN_90", "01_karelia", "Karélie", "29.09.2026 16:30:07", "2.4.0.0",
                             f"World{NBSP}of{NBSP}Tanks v.2.4.0.1 #952", 2),
                 real_results(61505, team=2, winner=2, damage=1594, radio=5874, track=101, kills=2, original_xp=1412,
                              xp=2330, achievement_xp=0, mark=4, created=1790692200))
# T57 Heavy (Overlord, prohra týmu 2, Mistr; achievementXP ≠ 0)
REAL_T57_LOSS = build(real_header("usa-A67_T57_58", "101_dday", "Overlord", "09.05.2026 12:49:53", "2.2.1.0",
                                  f"World{NBSP}of{NBSP}Tanks v.2.2.1.2 #875", 2),
                      real_results(14881, team=2, winner=1, damage=7430, radio=0, track=0, kills=5, original_xp=1225,
                                   xp=2757, achievement_xp=439, mark=4, created=1778323785))
# hráč odešel z bitvy dřív – jen hlavička (blok 1)
REAL_HEADER_ONLY = build(real_header("czech-Cz17_Vz_55", "47_canada_a", "Klidné pobřeží", "07.10.2026 16:55:31", "2.4.0.0",
                                     f"World{NBSP}of{NBSP}Tanks v.2.4.0.2 #966", 1))
