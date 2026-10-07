"""Game Enrichment C: knihovna replayů – parser hlavičky, úložiště, duplicity, metadata, štítky, propojení s milníkem,
stažení, mazání, bezpečnost. Jen syntetické replaye (tests/replay_fixtures.py), nic se nezapisuje do produkční DB."""
import json
import os
import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("GROQ_API_KEY", "x")
TESTS_DIR = os.path.dirname(__file__)
BACKEND_DIR = os.path.abspath(os.path.join(TESTS_DIR, ".."))
for p in (BACKEND_DIR, TESTS_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

import replay_fixtures as fx  # noqa: E402
import replay_parser as rp  # noqa: E402
import search_service  # noqa: E402
import wot_replay_service as wrs  # noqa: E402
from models import ActivityLog, WotReplay  # noqa: E402
from test_wot_milestones import ELC as ELC_MILESTONE, PNG, PROGETTO as PROGETTO_MILESTONE, WotBase  # noqa: E402


class ParserTestCase(unittest.TestCase):
    def test_parsed_full(self):
        r = rp.parse_replay(fx.PROGETTO)
        self.assertEqual(r.status, "parsed", r.warnings)
        self.assertEqual(r.warnings, [])
        m = r.metadata
        self.assertEqual(m["tank_tag"], "italy:It13_Progetto_M35_mod_46")
        self.assertEqual((m["map_name"], m["damage"], m["assist"], m["kills"], m["base_xp"], m["mastery"]),
                         ("Útesy", 5205, 1754, 5, 1208, "ace"))
        self.assertEqual(m["battle_result"], "win")
        self.assertEqual(m["game_version"], "1.26.0.0")
        self.assertEqual(m["played_at"], datetime(2026, 9, 14, 18, 15, 3), "arenaCreateTime (UTC) má přednost")
        self.assertEqual(r.parser_version, rp.PARSER_VERSION)

    def test_assist_is_radio_plus_track(self):
        self.assertEqual(rp.parse_replay(fx.ELC).metadata["assist"], 5975)

    def test_partial_header_only(self):
        r = rp.parse_replay(fx.PARTIAL)
        self.assertEqual(r.status, "partial")
        self.assertEqual(r.metadata["tank_tag"], "sweden:S16_Kranvagn")
        self.assertEqual(r.metadata["map_name"], "Himmelsdorf")
        self.assertEqual(r.metadata["played_at"], datetime(2026, 7, 11, 19, 40), "dateTime = Praha (CEST) → UTC")
        for k in ("damage", "kills", "assist", "base_xp", "mastery", "battle_result"):
            self.assertNotIn(k, r.metadata, "nic se nehádá")
        self.assertTrue(any("výsledky" in w for w in r.warnings))

    def test_unsupported_and_invalid(self):
        self.assertEqual(rp.parse_replay(fx.UNSUPPORTED).status, "unsupported")
        self.assertEqual(rp.parse_replay(PNG).status, "invalid")
        self.assertEqual(rp.parse_replay(b"").status, "invalid")
        self.assertEqual(rp.parse_replay(b"PK\x03\x04" + b"\x00" * 100).status, "invalid")

    def test_unknown_magic_with_valid_structure_warns(self):
        r = rp.parse_replay(fx.build(fx.header(), fx.results(), magic=b"\x00\x00\x00\x00"))
        self.assertEqual(r.status, "parsed")
        self.assertTrue(any("signatura" in w for w in r.warnings))

    def test_out_of_range_values_are_dropped_not_guessed(self):
        r = rp.parse_replay(fx.build(fx.header(), fx.results(damage=10_000_000, kills=40)))
        self.assertEqual(r.status, "partial")
        self.assertNotIn("damage", r.metadata)
        self.assertNotIn("kills", r.metadata)
        self.assertEqual(r.metadata["base_xp"], 1208)

    def test_no_mastery_loss_and_draw(self):
        r = rp.parse_replay(fx.build(fx.header(), fx.results(mark=0, winner=2)))
        self.assertNotIn("mastery", r.metadata)
        self.assertEqual(r.metadata["battle_result"], "loss")
        self.assertEqual(rp.parse_replay(fx.build(fx.header(), fx.results(winner=0))).metadata["battle_result"], "draw")
        self.assertEqual(rp.parse_replay(fx.build(fx.header(), fx.results(mark=2))).metadata["mastery"], "second")

    def test_flat_personal_and_team_from_header(self):
        res = fx.results(flat=True)
        del res[0]["personal"]["team"]
        r = rp.parse_replay(fx.build(fx.header(team=2), res))
        self.assertEqual(r.metadata["damage"], 5205)
        self.assertEqual(r.metadata["battle_result"], "loss", "tým hráče z hlavičky (2), vyhrál tým 1")

    def test_truncated_and_hostile_inputs_never_crash(self):
        data = fx.PROGETTO
        for cut in (0, 3, 7, 8, 11, 12, 40, len(data) // 2):
            self.assertIn(rp.parse_replay(data[:cut]).status, rp.STATUSES)
        huge = fx.MAGIC + (2**31).to_bytes(4, "little") + b"{}"
        self.assertEqual(rp.parse_replay(huge).status, "unsupported")
        bad_len = fx.MAGIC + (1).to_bytes(4, "little") + (10**9).to_bytes(4, "little") + b"{}"
        self.assertEqual(rp.parse_replay(bad_len).status, "unsupported")
        weird = fx.build(None, raw_blocks=[b'{"playerVehicle": "../../etc-passwd", "mapDisplayName": 5}'])
        r = rp.parse_replay(weird)
        self.assertNotIn("tank_tag", r.metadata)
        self.assertNotIn("map_name", r.metadata)


class RealClientShapeTestCase(unittest.TestCase):
    """Regrese z lokálního ověření na skutečných replayích klienta 2.x (hodnoty z reálných souborů, bez binárek)."""

    def test_real_2x_full_battle(self):
        r = rp.parse_replay(fx.REAL_ELC)
        self.assertEqual(r.status, "parsed", r.warnings)
        m = r.metadata
        self.assertEqual(m["tank_tag"], "france:F97_ELC_EVEN_90")
        self.assertEqual(m["map_name"], "Karélie", "lokalizovaný název mapy z klienta")
        self.assertEqual((m["damage"], m["kills"], m["mastery"], m["battle_result"]), (1594, 2, "ace", "win"))
        self.assertEqual(m["assist"], 5975, "spotování 5874 + pásy 101; stun/smoke/inspire se nepočítají")
        self.assertEqual(m["base_xp"], 1412, "základní XP = originalXP, ne xp/factualXP po prémii (2330)")
        self.assertEqual(m["played_at"], datetime(2026, 9, 29, 14, 30, 0), "arenaCreateTime UTC (16:30 Praha)")

    def test_real_2x_version_comes_from_xml_not_stale_exe(self):
        self.assertEqual(rp.parse_replay(fx.REAL_ELC).metadata["game_version"], "2.4.0.1", "exe říká 2.4.0.0")
        self.assertEqual(rp.parse_replay(fx.REAL_T57_LOSS).metadata["game_version"], "2.2.1.2", "exe říká 2.2.1.0")

    def test_real_2x_loss_with_achievement_xp(self):
        m = rp.parse_replay(fx.REAL_T57_LOSS).metadata
        self.assertEqual((m["battle_result"], m["base_xp"], m["assist"], m["mastery"]), ("loss", 1225, 0, "ace"))

    def test_real_2x_left_early_header_only(self):
        r = rp.parse_replay(fx.REAL_HEADER_ONLY)
        self.assertEqual(r.status, "partial")
        self.assertEqual((r.metadata["tank_tag"], r.metadata["map_name"], r.metadata["game_version"]),
                         ("czech:Cz17_Vz_55", "Klidné pobřeží", "2.4.0.2"))
        self.assertEqual(r.metadata["played_at"], datetime(2026, 10, 7, 14, 55, 31), "dateTime = Praha (CEST) → UTC")
        for k in ("damage", "kills", "assist", "base_xp", "mastery", "battle_result"):
            self.assertNotIn(k, r.metadata)


class ReplayApiBase(WotBase):
    def upload(self, data=fx.PROGETTO, name="20260914_2015_italy-It13_Progetto_M35_mod_46_18_cliff.wotreplay", status=200):
        params = {} if name is None else {"filename": name}
        r = self.client.post("/wot/replays", params=params, content=data, headers={"Content-Type": "application/octet-stream"})
        self.assertEqual(r.status_code, status, r.text)
        return r.json()

    def replay_files(self):
        folder = Path(self.media) / "wot-replays"
        return sorted(p.name for p in folder.iterdir()) if folder.exists() else []


class UploadTestCase(ReplayApiBase):
    def test_upload_parsed_stores_original_and_metadata(self):
        self.login()
        body = self.upload()
        self.assertEqual(body["parser_status"], "parsed")
        self.assertEqual((body["tank_tag"], body["map_name"], body["damage"], body["assist"], body["kills"], body["base_xp"],
                          body["mastery"], body["battle_result"]), ("italy:It13_Progetto_M35_mod_46", "Útesy", 5205, 1754, 5, 1208, "ace", "win"))
        self.assertIsNone(body["tank_name"], "lidský název doplní uživatel / manifest ve frontendu")
        self.assertEqual(body["file_size"], len(fx.PROGETTO))
        self.assertEqual(body["sha256"], wrs.sha256(fx.PROGETTO))
        self.assertEqual(body["download_url"], f"/wot/replays/{body['id']}/file")
        files = self.replay_files()
        self.assertEqual(len(files), 1)
        self.assertRegex(files[0], r"^[0-9a-f]{32}\.wotreplay$")
        self.assertEqual((Path(self.media) / "wot-replays" / files[0]).read_bytes(), fx.PROGETTO, "originál beze změny")
        self.assertNotIn(self.media, str(body), "žádná serverová cesta v odpovědi")
        act = self.q(lambda db: db.query(ActivityLog).filter_by(entity_type="WotReplay").one())
        self.assertEqual(json.loads(act.delta_json)["event"], "replay_uploaded")

    def test_partial_and_unsupported_are_kept(self):
        self.login()
        partial = self.upload(fx.PARTIAL, "kranvagn.wotreplay")
        self.assertEqual(partial["parser_status"], "partial")
        self.assertIsNone(partial["damage"])
        self.assertTrue(partial["parser_warnings"])
        unsupported = self.upload(fx.UNSUPPORTED, "novy-format.wotreplay")
        self.assertEqual(unsupported["parser_status"], "unsupported")
        self.assertEqual(len(self.replay_files()), 2, "selhání parseru ≠ selhání uploadu")

    def test_invalid_extension_and_fake_replay(self):
        self.login()
        for name in ("battle.zip", "battle.wotreplay.exe", "battle", None):
            self.assertEqual(self.upload(fx.PROGETTO, name, status=400)["detail"]["error"], "invalid_file", name)
        self.assertEqual(self.upload(PNG, "screenshot.wotreplay", status=400)["detail"]["error"], "invalid_file")
        self.assertEqual(self.upload(b"", "empty.wotreplay", status=400)["detail"]["error"], "invalid_file")
        self.assertEqual(self.replay_files(), [])

    def test_oversize(self):
        self.login()
        with patch.object(wrs, "MAX_BYTES", 100):
            self.assertEqual(self.upload(fx.PROGETTO, "big.wotreplay", status=413)["detail"]["error"], "invalid_file")
        self.assertEqual(self.replay_files(), [])

    def test_failed_db_write_leaves_no_file(self):
        self.login()
        with patch.object(wrs, "log_activity", side_effect=RuntimeError("db down")):
            with self.assertRaises(RuntimeError):
                self.upload(fx.PROGETTO, "x.wotreplay", status=500)
        self.assertEqual(self.replay_files(), [])

    def test_traversal_filename_is_metadata_only(self):
        self.login()
        body = self.upload(fx.PROGETTO, "../../etc/evil\x00name.wotreplay")
        self.assertEqual(body["original_filename"], "evilname.wotreplay")
        self.assertEqual(len(self.replay_files()), 1)
        self.assertFalse((Path(self.media).parent / "etc").exists())

    def test_duplicate_by_checksum_not_filename(self):
        self.login()
        first = self.upload()
        dup = self.upload(fx.PROGETTO, "jiny-nazev.wotreplay", status=409)
        self.assertEqual(dup["detail"]["error"], "duplicate")
        self.assertEqual(dup["detail"]["replay_id"], first["id"])
        self.assertEqual(len(self.replay_files()), 1, "žádná druhá kopie")
        self.upload(fx.ELC, first["original_filename"])  # stejný název, jiný obsah = jiný replay
        self.assertEqual(len(self.replay_files()), 2)


class MetadataTestCase(ReplayApiBase):
    def test_manual_edit_and_validation(self):
        self.login()
        rid = self.upload(fx.PARTIAL, "kranvagn.wotreplay")["id"]
        r = self.client.patch(f"/wot/replays/{rid}", json={
            "tank_name": " Kranvagn ", "damage": 6120, "kills": 3, "assist": 800, "base_xp": 1100, "mastery": "ace",
            "battle_result": "win", "notes": "Poslední tank týmu", "played_at": "2026-07-11"})
        self.assertEqual(r.status_code, 200, r.text)
        b = r.json()
        self.assertEqual((b["tank_name"], b["damage"], b["mastery"], b["battle_result"]), ("Kranvagn", 6120, "ace", "win"))
        self.assertEqual(b["played_at"], "2026-07-11T10:00:00Z", "ruční datum = poledne v Praze")
        self.assertEqual(b["parser_status"], "partial", "stav parseru se ruční úpravou nemění")
        for body, code in (({"kills": 99}, "invalid_kills"), ({"mastery": "gold"}, "invalid_mastery"),
                           ({"battle_result": "maybe"}, "invalid_battle_result"), ({"played_at": "2099-01-01"}, "invalid_played_at"),
                           ({"played_at": "včera"}, "invalid_played_at"), ({"tank_name": "x" * 101}, "invalid_tank_name")):
            res = self.client.patch(f"/wot/replays/{rid}", json=body)
            self.assertEqual((res.status_code, res.json()["detail"]["error"]), (400, code), body)
        cleared = self.client.patch(f"/wot/replays/{rid}", json={"damage": None, "mastery": None}).json()
        self.assertEqual((cleared["damage"], cleared["mastery"]), (None, None))
        self.assertEqual(self.q(lambda db: db.query(ActivityLog).filter_by(entity_type="WotReplay").count()), 1,
                         "ruční úpravy se do Aktivity nepíšou")

    def test_tags_and_favorite(self):
        self.login()
        rid = self.upload()["id"]
        b = self.client.patch(f"/wot/replays/{rid}", json={"tags": ["Mko", "carry", "  Těsná   výhra ", "mko"], "favorite": True}).json()
        self.assertEqual(b["tags"], ["mko", "carry", "těsná výhra"])
        self.assertTrue(b["favorite"])
        for bad in (["<script>"], ["x" * 25], [f"t{i}" for i in range(9)], [""]):
            self.assertEqual(self.client.patch(f"/wot/replays/{rid}", json={"tags": bad}).status_code, 400, bad)
        self.assertFalse(self.client.patch(f"/wot/replays/{rid}", json={"favorite": False}).json()["favorite"])

    def test_list_filters_sort_and_facets(self):
        self.login()
        p = self.upload()["id"]
        e = self.upload(fx.ELC, "elc.wotreplay")["id"]
        k = self.upload(fx.PARTIAL, "kranvagn.wotreplay")["id"]
        self.client.patch(f"/wot/replays/{p}", json={"tank_name": "Progetto 65", "tags": ["mko", "carry"], "notes": "1 vs 3 na konci"})
        self.client.patch(f"/wot/replays/{e}", json={"tank_name": "ELC EVEN 90", "tags": ["mko", "spotting"], "favorite": True})
        ids = lambda **params: [x["id"] for x in self.client.get("/wot/replays", params=params).json()["items"]]  # noqa: E731
        self.assertEqual(ids(), [e, p, k], "nejnovější bitva první")
        self.assertEqual(ids(sort="played_asc"), [k, p, e])
        self.assertEqual(ids(sort="uploaded_desc"), [k, e, p])
        self.assertEqual(ids(tag="MKO"), [e, p])
        self.assertEqual(ids(tag="spotting"), [e])
        self.assertEqual(ids(favorite="true"), [e])
        self.assertEqual(ids(favorite="false"), [p, k])
        self.assertEqual(ids(mastery="ace"), [e, p])
        self.assertEqual(ids(mastery="none"), [k])
        self.assertEqual(ids(tank="Progetto 65"), [p])
        self.assertEqual(ids(tank="sweden:S16_Kranvagn"), [k])
        self.assertEqual(ids(map="Karelia"), [e])
        self.assertEqual(ids(result="win"), [e, p])
        self.assertEqual(ids(parser_status="partial"), [k])
        self.assertEqual(ids(q="utesy"), [p], "bez diakritiky")
        self.assertEqual(ids(q="vs 3"), [p], "poznámka")
        self.assertEqual(ids(q="kranvagn"), [k], "název souboru / tag vozidla")
        body = self.client.get("/wot/replays").json()
        self.assertEqual(body["facets"]["tags"], ["mko", "carry", "spotting"], "předvolené první")
        self.assertIn("Karelia", body["facets"]["maps"])
        self.assertEqual(body["preset_tags"], list(wrs.PRESET_TAGS))
        self.assertEqual(self.client.get("/wot/replays", params={"sort": "nonsense"}).status_code, 400)


class MilestoneLinkTestCase(ReplayApiBase):
    def test_link_unlink_and_independent_deletes(self):
        self.login()
        mid = self.client.post("/wot/milestones", json=PROGETTO_MILESTONE).json()["id"]
        other = self.client.post("/wot/milestones", json=ELC_MILESTONE).json()["id"]
        self.client.post(f"/wot/milestones/{mid}/screenshots", params={"filename": "a.png"}, content=PNG)
        rid = self.upload()["id"]
        b = self.client.patch(f"/wot/replays/{rid}", json={"linked_milestone_id": mid}).json()
        self.assertEqual(b["linked_milestone_id"], mid)
        self.assertEqual((b["milestone"]["tank"], len(b["milestone"]["screenshots"])), ("Progetto 65", 1), "screenshoty milníku v detailu")
        ms = {m["id"]: m for m in self.client.get("/wot/milestones").json()}
        self.assertEqual((ms[mid]["replay_ids"], ms[other]["replay_ids"]), ([rid], []))
        events = self.q(lambda db: [json.loads(a.delta_json).get("event") for a in db.query(ActivityLog).filter_by(entity_type="WotReplay").all()])
        self.assertIn("replay_linked_to_milestone", events)
        missing = self.client.patch(f"/wot/replays/{rid}", json={"linked_milestone_id": 999})
        self.assertEqual((missing.status_code, missing.json()["detail"]["error"]), (404, "milestone_not_found"))
        self.assertEqual(self.client.patch(f"/wot/replays/{rid}", json={"linked_milestone_id": 0}).status_code, 400)
        self.assertIsNone(self.client.patch(f"/wot/replays/{rid}", json={"linked_milestone_id": None}).json()["milestone"])
        # smazání milníku → replay zůstane, jen bez odkazu
        self.client.patch(f"/wot/replays/{rid}", json={"linked_milestone_id": mid})
        self.assertEqual(self.client.delete(f"/wot/milestones/{mid}").status_code, 200)
        after = self.client.get(f"/wot/replays/{rid}").json()
        self.assertIsNone(after["linked_milestone_id"])
        self.assertEqual(len(self.replay_files()), 1)
        # smazání replaye → milník zůstane
        self.client.patch(f"/wot/replays/{rid}", json={"linked_milestone_id": other})
        self.assertEqual(self.client.delete(f"/wot/replays/{rid}").status_code, 200)
        ms = {m["id"]: m for m in self.client.get("/wot/milestones").json()}
        self.assertEqual(ms[other]["replay_ids"], [])


class FileAndSecurityTestCase(ReplayApiBase):
    def test_download_original(self):
        self.login()
        b = self.upload(fx.ELC, 'elc "best".wotreplay')
        r = self.client.get(b["download_url"])
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.content, fx.ELC)
        self.assertEqual(r.headers["content-type"], "application/octet-stream")
        self.assertIn("attachment", r.headers["content-disposition"])
        self.assertIn("elc%20_best_.wotreplay", r.headers["content-disposition"], "uvozovky z názvu pryč")
        self.assertEqual(r.headers["x-content-type-options"], "nosniff")

    def test_delete_removes_file_and_invalid_ids(self):
        self.login()
        rid = self.upload()["id"]
        self.assertEqual(len(self.replay_files()), 1)
        r = self.client.delete(f"/wot/replays/{rid}")
        self.assertEqual((r.status_code, r.json()["file_removed"]), (200, True))
        self.assertEqual(self.replay_files(), [])
        for method, url in (("get", f"/wot/replays/{rid}"), ("get", f"/wot/replays/{rid}/file"), ("delete", f"/wot/replays/{rid}"),
                            ("patch", f"/wot/replays/{rid}")):
            kwargs = {"json": {}} if method == "patch" else {}
            self.assertEqual(getattr(self.client, method)(url, **kwargs).status_code, 404, url)
        self.assertEqual(self.client.get("/wot/replays/abc").status_code, 422)
        events = self.q(lambda db: [json.loads(a.delta_json).get("event") for a in db.query(ActivityLog).filter_by(entity_type="WotReplay").all()])
        self.assertEqual(events, ["replay_uploaded", "replay_deleted"])

    def test_missing_or_tampered_file_is_404(self):
        self.login()
        rid = self.upload()["id"]
        for name in self.replay_files():
            (Path(self.media) / "wot-replays" / name).unlink()
        self.assertEqual(self.client.get(f"/wot/replays/{rid}/file").status_code, 404)

        def tamper(db):
            db.query(WotReplay).filter_by(id=rid).update({"stored_filename": "../../../etc/passwd"})
            db.commit()
        self.q(tamper)
        self.assertEqual(self.client.get(f"/wot/replays/{rid}/file").status_code, 404)
        self.assertEqual(self.client.delete(f"/wot/replays/{rid}").json()["file_removed"], False)

    def test_requires_auth(self):
        self.login()
        rid = self.upload()["id"]
        self.client.cookies.clear()
        for method, url, kwargs in (("get", "/wot/replays", {}), ("get", f"/wot/replays/{rid}", {}), ("get", f"/wot/replays/{rid}/file", {}),
                                    ("post", "/wot/replays?filename=a.wotreplay", {"content": fx.ELC}),
                                    ("patch", f"/wot/replays/{rid}", {"json": {"favorite": True}}), ("delete", f"/wot/replays/{rid}", {})):
            self.assertEqual(getattr(self.client, method)(url, **kwargs).status_code, 401, url)
        self.assertEqual(len(self.replay_files()), 1)

    def test_global_search_finds_replay(self):
        self.login()
        rid = self.upload()["id"]
        self.client.patch(f"/wot/replays/{rid}", json={"tank_name": "Progetto 65", "tags": ["carry"], "notes": "Poslední tank"})
        for q in ("progetto", "utesy", "carry", "posledni tank"):
            res = self.q(lambda db: search_service.search(db, q))["results"]
            hit = next((x for x in res if x["type"] == "wot_replay"), None)
            self.assertIsNotNone(hit, q)
            self.assertEqual(hit["href"], f"/wot/replays?replay={rid}")
            self.assertTrue(hit["subtitle"].startswith("Replay · Útesy · 14. 9. 2026"), hit["subtitle"])



class FriendlyTankNameTestCase(ReplayApiBase):
    """Regrese z lokálního ověření: replay znal jen technický tag → Global Search / Aktivita ukazovaly
    „It08_Progetto_M40_mod_65" a „Progetto 65" / „T57 Heavy" se nenašly. Frontend při uploadu pošle název
    z manifestu Tankopedie (Game Enrichment A); backend ho uloží vedle tagu, tag zůstává technická identita."""

    def upload_named(self, data, tank_name, name="real.wotreplay", status=200):
        r = self.client.post("/wot/replays", params={"filename": name, "tank_name": tank_name}, content=data,
                             headers={"Content-Type": "application/octet-stream"})
        self.assertEqual(r.status_code, status, r.text)
        return r.json()

    def test_upload_persists_friendly_name_and_keeps_raw_tag(self):
        self.login()
        body = self.upload_named(fx.REAL_T57_LOSS, "T57 Heavy")
        self.assertEqual((body["tank_name"], body["tank_tag"]), ("T57 Heavy", "usa:A67_T57_58"))
        act = self.q(lambda db: db.query(ActivityLog).filter_by(entity_type="WotReplay").one())
        self.assertEqual(act.summary, "Replay nahrán: T57 Heavy · Overlord", "Aktivita s lidským názvem, ne tagem")

    def test_name_hint_is_cleaned_and_untrusted_without_vehicle(self):
        self.login()
        body = self.upload_named(fx.REAL_ELC, "  ELC   EVEN 90 ")
        self.assertEqual(body["tank_name"], "ELC EVEN 90", "mezery sjednocené stejným validátorem jako úprava")
        # bez rozpoznaného vozidla (nečitelná hlavička) se název z klienta neukládá – nemá k čemu patřit
        bad = self.upload_named(fx.UNSUPPORTED, "Cokoli", name="x.wotreplay")
        self.assertIsNone(bad["tank_name"])
        # příliš dlouhý / prázdný název upload nezablokuje (soubor je důležitější než popisek), jen se ignoruje
        long_name = self.upload_named(fx.REAL_HEADER_ONLY, "X" * 300, name="y.wotreplay")
        self.assertIsNone(long_name["tank_name"])
        self.assertEqual(long_name["tank_tag"], "czech:Cz17_Vz_55")

    def test_natural_name_search_library_and_global(self):
        self.login()
        ids = {
            "T57 Heavy": self.upload_named(fx.REAL_T57_LOSS, "T57 Heavy", name="t57.wotreplay")["id"],
            "ELC EVEN 90": self.upload_named(fx.REAL_ELC, "ELC EVEN 90", name="elc.wotreplay")["id"],
        }
        for q, name in (("T57 Heavy", "T57 Heavy"), ("heavy", "T57 Heavy"), ("ELC EVEN 90", "ELC EVEN 90"), ("elc 90", "ELC EVEN 90")):
            lib = self.client.get("/wot/replays", params={"q": q}).json()["items"]
            self.assertEqual([x["id"] for x in lib], [ids[name]], f"knihovna: {q}")
            hits = [x for x in self.q(lambda db: search_service.search(db, q))["results"] if x["type"] == "wot_replay"]
            self.assertEqual([x["title"] for x in hits], [name], f"Global Search: {q}")
        # technický tag zůstává dohledatelný
        hits = [x for x in self.q(lambda db: search_service.search(db, "A67_T57_58"))["results"] if x["type"] == "wot_replay"]
        self.assertEqual([x["title"] for x in hits], ["T57 Heavy"])

    def test_legacy_replay_without_name_falls_back_to_tag(self):
        self.login()
        body = self.upload()  # bez názvu (starší klient / chybí manifest)
        self.assertIsNone(body["tank_name"])
        hits = [x for x in self.q(lambda db: search_service.search(db, "progetto"))["results"] if x["type"] == "wot_replay"]
        self.assertEqual([x["title"] for x in hits], ["It13_Progetto_M35_mod_46"])
        act = self.q(lambda db: db.query(ActivityLog).filter_by(entity_type="WotReplay").one())
        self.assertIn("italy:It13_Progetto_M35_mod_46", act.summary)

if __name__ == "__main__":
    unittest.main()
