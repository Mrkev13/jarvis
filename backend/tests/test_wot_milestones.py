"""Game Enrichment B: splnění grindů (100 %, historie, událost, idempotence), milníky „Mko" a screenshoty."""
import os
import shutil
import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("GROQ_API_KEY", "x")
BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import bcrypt  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import auth_service  # noqa: E402
import main  # noqa: E402
import media_storage  # noqa: E402
import tools  # noqa: E402
import wot_service as ws  # noqa: E402
from database import Base  # noqa: E402
from models import ActivityLog, WotGrind, WotGrindCompletion, WotMilestone, WotMilestoneScreenshot  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 64
NOW = datetime(2026, 10, 7, 18, 0)

# fixtures podle typu záznamů uživatele (jen testovací data – nic se nezapisuje do produkční DB)
PROGETTO = {"tank": "Progetto 65", "mastery": "ace", "map_name": "Útesy", "damage": 5205, "kills": 5, "assist": 1754,
            "base_xp": 1208, "played_on": "2026-09-14"}
ELC = {"tank": "ELC EVEN 90", "mastery": "ace", "map_name": "Karelia", "damage": 1594, "assist": 5975, "kills": 2,
       "base_xp": 1412, "played_on": "2026-09-20", "favorite": True}


class WotBase(unittest.TestCase):
    PIN = "4821"

    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        self.media = tempfile.mkdtemp(prefix="wot-media-")
        self._patches = [
            patch.object(auth_service, "SessionLocal", self.Session),
            patch.object(main, "SessionLocal", self.Session),
            patch.object(tools, "SessionLocal", self.Session),
            patch.object(media_storage, "MEDIA_DIR", self.media),
            patch.object(auth_service, "_failed_attempts", {}),
            patch.object(auth_service, "AUTH_PIN_HASH", bcrypt.hashpw(self.PIN.encode(), bcrypt.gensalt(rounds=4)).decode()),
        ]
        for p in self._patches:
            p.start()
        self.client = TestClient(main.app)

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.engine.dispose()
        shutil.rmtree(self.media, ignore_errors=True)

    def login(self):
        self.assertEqual(self.client.post("/auth/login", json={"pin": self.PIN}).status_code, 200)

    def q(self, fn):
        db = self.Session()
        try:
            return fn(db)
        finally:
            db.close()

    def files(self):
        folder = Path(self.media) / "wot-screenshots"
        return sorted(p.name for p in folder.iterdir()) if folder.exists() else []


class GrindCompletionTestCase(WotBase):
    def add_grind(self, tank="Kranvagn", xp=52000):
        r = self.client.post("/wot/grind", json={"tank": tank, "xp_remaining": xp, "priority": "high", "status": "active"})
        self.assertEqual(r.status_code, 200)
        return self.q(lambda db: db.query(WotGrind).filter_by(tank=tank).one().id)

    def test_new_grind_has_progress_baseline(self):
        self.login()
        gid = self.add_grind(xp=100000)
        self.client.post("/wot/grind", json={"tank": "Kranvagn", "xp_remaining": 25000, "priority": "high", "status": "active"})
        g = next(x for x in self.client.get("/wot/grinds").json() if x["id"] == gid)
        self.assertEqual((g["xp_start"], g["xp_remaining"], g["progress"]), (100000, 25000, 75))
        self.assertIsNotNone(g["started_at"])

    def test_complete_grind(self):
        self.login()
        gid = self.add_grind()
        r = self.client.post(f"/wot/grind/{gid}/complete")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual((body["grind"]["status"], body["grind"]["xp_remaining"], body["grind"]["progress"]), ("completed", 0, 100))
        c = body["completion"]
        self.assertEqual((c["tank"], c["xp_remaining_before"], c["xp_start"]), ("Kranvagn", 52000, 52000))
        self.assertTrue(c["completed_at"].endswith("Z"))
        self.assertEqual(c["id"], f"completion:{c['completion_id']}", "stabilní id")
        history = self.client.get("/wot/grinds/completed").json()
        self.assertEqual([h["tank"] for h in history], ["Kranvagn"])
        logs = self.q(lambda db: [(lg.action_type, lg.delta_json, lg.dedupe_key) for lg in db.query(ActivityLog).filter_by(area="wot")])
        complete = [lg for lg in logs if lg[0] == "complete"]
        self.assertEqual(len(complete), 1)
        self.assertIn("wot_grind_completed", complete[0][1])
        self.assertEqual(complete[0][2], f"wot_grind_completed:{c['completion_id']}")

    def test_double_completion_is_safe(self):
        self.login()
        gid = self.add_grind()
        self.assertEqual(self.client.post(f"/wot/grind/{gid}/complete").status_code, 200)
        again = self.client.post(f"/wot/grind/{gid}/complete")
        self.assertEqual(again.status_code, 409)
        self.assertEqual(again.json()["detail"]["error"], "already_completed")
        self.assertEqual(self.q(lambda db: db.query(WotGrindCompletion).count()), 1)
        # souběh: dvě session vidí aktivní grind, jen jedno splnění projde
        self.q(lambda db: (setattr(db.get(WotGrind, gid), "status", "active"), db.commit()))
        a, b = self.Session(), self.Session()
        try:
            ws.complete_grind(a, gid, now=NOW)
            a.commit()
            b.get(WotGrind, gid).status = "active"  # zastaralý pohled druhé záložky
            with self.assertRaises(ws.WotError):
                ws.complete_grind(b, gid, now=NOW)
        finally:
            a.close()
            b.close()

    def test_missing_grind(self):
        self.login()
        r = self.client.post("/wot/grind/999/complete")
        self.assertEqual(r.status_code, 404)

    def test_history_survives_grind_delete_and_readd(self):
        self.login()
        gid = self.add_grind()
        self.client.post(f"/wot/grind/{gid}/complete")
        self.client.delete(f"/wot/grind/{gid}")
        hist = self.client.get("/wot/grinds/completed").json()
        self.assertEqual(len(hist), 1)
        self.assertIsNone(hist[0]["grind_id"], "historie přežije smazání grindu")
        self.add_grind("Kranvagn", 40000)
        self.assertEqual(len(self.client.get("/wot/grinds/completed").json()), 1)

    def test_form_completed_status_records_history_once(self):
        self.login()
        self.add_grind("TVP T 50/51", 96000)
        self.client.post("/wot/grind", json={"tank": "TVP T 50/51", "xp_remaining": 96000, "priority": "high", "status": "completed"})
        self.client.post("/wot/grind", json={"tank": "TVP T 50/51", "xp_remaining": 0, "priority": "high", "status": "completed"})
        hist = self.client.get("/wot/grinds/completed").json()
        self.assertEqual(len(hist), 1)
        self.assertEqual(self.q(lambda db: db.query(WotGrind).one().xp_remaining), 0)
        # znovu aktivovaný grind = nový základ průběhu, historie zůstává
        self.client.post("/wot/grind", json={"tank": "TVP T 50/51", "xp_remaining": 30000, "priority": "high", "status": "active"})
        g = self.client.get("/wot/grinds").json()[0]
        self.assertEqual((g["status"], g["xp_start"], g["progress"]), ("active", 30000, 0))
        self.assertEqual(len(self.client.get("/wot/grinds/completed").json()), 1)

    def test_new_grind_cannot_be_created_completed(self):
        """Regrese B: nový grind rovnou „Dokončeno" zmizel bez historie i události – splnění jen kanonickým tokem."""
        self.login()
        r = self.client.post("/wot/grind", json={"tank": "Kranvagn", "xp_remaining": 52000, "priority": "high", "status": "completed"})
        self.assertEqual(r.status_code, 422, r.text)
        self.assertEqual(r.json()["detail"]["error"], "invalid_status")
        self.assertEqual(self.q(lambda db: db.query(WotGrind).count()), 0, "nic se nezapsalo")
        self.assertEqual(self.q(lambda db: db.query(ActivityLog).count()), 0)
        # obejití přes AI nástroj (potvrzená akce) – stejné pravidlo
        with self.assertRaises(ws.WotError):
            tools.upsert_wot_grind("Kranvagn", 52000, status="completed", user_context="ai_confirm")
        self.assertEqual(self.q(lambda db: db.query(WotGrind).count()), 0)

    def test_existing_grind_completed_via_ai_tool_records_history(self):
        self.login()
        self.add_grind("Kranvagn", 52000)
        tools.upsert_wot_grind("Kranvagn", 52000, status="completed", user_context="ai_confirm")
        g = self.q(lambda db: db.query(WotGrind).one())
        self.assertEqual((g.status, g.xp_remaining), ("completed", 0))
        hist = self.client.get("/wot/grinds/completed").json()
        self.assertEqual([(h["tank"], h["xp_remaining_before"]) for h in hist], [("Kranvagn", 52000)])
        events = self.q(lambda db: [(lg.user_context, lg.delta_json) for lg in db.query(ActivityLog).filter_by(action_type="complete")])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0][0], "ai_confirm")
        self.assertIn("wot_grind_completed", events[0][1])
        # opakované „completed" už nic nepřidá
        tools.upsert_wot_grind("Kranvagn", 0, status="completed", user_context="ai_confirm")
        self.assertEqual(len(self.client.get("/wot/grinds/completed").json()), 1)

    def test_legacy_completed_grind_in_history_without_date(self):
        self.q(lambda db: (db.add(WotGrind(tank="T-100 LT", xp_remaining=0, priority="low", status="completed")), db.commit()))
        self.login()
        hist = self.client.get("/wot/grinds/completed").json()
        self.assertEqual([(h["tank"], h["legacy"], h["completed_at"]) for h in hist], [("T-100 LT", True, None)])

    def test_progress_unknown_without_baseline(self):
        g = WotGrind(tank="X", xp_remaining=5000, status="active")
        self.assertIsNone(ws.grind_progress(g))
        g.xp_start = 10000
        self.assertEqual(ws.grind_progress(g), 50)
        g.xp_remaining = 12000  # víc než na začátku → 0, ne záporně
        self.assertEqual(ws.grind_progress(g), 0)


class MilestoneTestCase(WotBase):
    def test_create_read_edit_delete(self):
        self.login()
        r = self.client.post("/wot/milestones", json=PROGETTO)
        self.assertEqual(r.status_code, 200, r.text)
        m = r.json()
        self.assertEqual((m["tank"], m["map_name"], m["damage"], m["assist"], m["kills"], m["base_xp"], m["mastery"]),
                         ("Progetto 65", "Útesy", 5205, 1754, 5, 1208, "ace"))
        self.assertEqual((m["favorite"], m["screenshots"], m["milestone_type"]), (False, [], "mastery"))
        self.client.post("/wot/milestones", json=ELC)
        listed = self.client.get("/wot/milestones").json()
        self.assertEqual([x["tank"] for x in listed], ["ELC EVEN 90", "Progetto 65"], "nejnovější bitva první")
        upd = self.client.patch(f"/wot/milestones/{m['id']}", json={"favorite": True, "notes": "Poslední tank týmu."}).json()
        self.assertEqual((upd["favorite"], upd["notes"], upd["damage"]), (True, "Poslední tank týmu.", 5205), "PATCH mění jen poslaná pole")
        d = self.client.delete(f"/wot/milestones/{m['id']}")
        self.assertEqual(d.status_code, 200)
        self.assertEqual(self.client.patch(f"/wot/milestones/{m['id']}", json={"favorite": False}).status_code, 404)
        acts = self.q(lambda db: [lg.action_type for lg in db.query(ActivityLog).filter_by(entity_type="WotMilestone")])
        self.assertEqual(acts.count("create"), 2)
        self.assertIn("delete", acts)

    def test_only_tank_required(self):
        self.login()
        r = self.client.post("/wot/milestones", json={"tank": "Object 140"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual({k: r.json()[k] for k in ("map_name", "damage", "played_on", "mastery")}, {"map_name": None, "damage": None, "played_on": None, "mastery": None})

    def test_validation(self):
        self.login()
        bad = [
            ({}, "invalid_tank"), ({"tank": "   "}, "invalid_tank"), ({"tank": "x" * 101}, "invalid_tank"),
            ({"tank": "A", "damage": -1}, "invalid_damage"), ({"tank": "A", "kills": 16}, "invalid_kills"),
            ({"tank": "A", "base_xp": 99999}, "invalid_base_xp"), ({"tank": "A", "mastery": "legend"}, "invalid_mastery"),
            ({"tank": "A", "played_on": "2099-01-01"}, "invalid_played_on"), ({"tank": "A", "played_on": "včera"}, "invalid_played_on"),
            ({"tank": "A", "milestone_type": "achievement"}, "invalid_milestone_type"),
        ]
        for body, code in bad:
            r = self.client.post("/wot/milestones", json=body)
            self.assertEqual(r.status_code, 400 if code != "x" else 422, (body, r.text))
            self.assertEqual(r.json()["detail"]["error"], code, body)
        self.assertEqual(self.client.post("/wot/milestones", json={"tank": "A", "damage": "lots"}).status_code, 422)
        self.assertEqual(self.q(lambda db: db.query(WotMilestone).count()), 0)

    def test_requires_session(self):
        for method, url in (("get", "/wot/milestones"), ("post", "/wot/milestones"), ("post", "/wot/grind/1/complete"),
                            ("get", "/wot/grinds/completed"), ("post", "/wot/milestones/1/screenshots"),
                            ("get", "/wot/screenshots/1/file"), ("delete", "/wot/screenshots/1"), ("delete", "/wot/milestones/1")):
            kwargs = {"json": {"tank": "A"}} if method == "post" and "milestones" == url.split("/")[-1] else {}
            self.assertEqual(getattr(self.client, method)(url, **kwargs).status_code, 401, url)


class ScreenshotTestCase(WotBase):
    def setUp(self):
        super().setUp()
        self.login()
        self.mid = self.client.post("/wot/milestones", json=PROGETTO).json()["id"]

    def upload(self, data, filename="shot.png", caption=None, mid=None):
        params = {"filename": filename} if filename is not None else {}
        if caption:
            params["caption"] = caption
        return self.client.post(f"/wot/milestones/{mid or self.mid}/screenshots", params=params, content=data,
                                headers={"Content-Type": "application/octet-stream"})

    def test_upload_png_jpeg_webp_and_serve(self):
        for data, name, ctype, ext in ((PNG, "Útesy 1.png", "image/png", "png"), (JPEG, "b.JPEG", "image/jpeg", "jpg"),
                                       (WEBP, "c.webp", "image/webp", "webp")):
            r = self.upload(data, name, caption="Mko!")
            self.assertEqual(r.status_code, 200, r.text)
            s = r.json()
            self.assertEqual((s["content_type"], s["original_name"], s["caption"]), (ctype, name, "Mko!"))
            f = self.client.get(s["url"])
            self.assertEqual(f.status_code, 200)
            self.assertEqual(f.content, data)
            self.assertEqual(f.headers["content-type"], ctype)
            self.assertEqual(f.headers["x-content-type-options"], "nosniff")
        names = self.files()
        self.assertEqual(len(names), 3)
        self.assertTrue(all(media_storage.STORED_NAME_RE.fullmatch(n) for n in names), names)
        m = self.client.get("/wot/milestones").json()[0]
        self.assertEqual([s["position"] for s in m["screenshots"]], [0, 1, 2])

    def test_rejects_invalid_type_and_mismatch(self):
        self.assertEqual(self.upload(b"GIF89a" + b"\x00" * 20, "x.gif").status_code, 400)
        self.assertEqual(self.upload(b"<svg xmlns='http://www.w3.org/2000/svg'/>", "x.svg").status_code, 400)
        r = self.upload(PNG, "x.jpg")
        self.assertEqual(r.status_code, 400, "přípona musí odpovídat obsahu")
        self.assertEqual(self.upload(b"", "x.png").status_code, 400)
        self.assertEqual(self.files(), [])

    def test_rejects_oversized(self):
        with patch.object(media_storage, "MAX_BYTES", 100):
            r = self.upload(PNG + b"\x00" * 200, "big.png")
        self.assertEqual(r.status_code, 413)
        self.assertEqual(self.files(), [])

    def test_original_name_never_used_as_path(self):
        r = self.upload(PNG, "../../../etc/passwd.png")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["original_name"], "passwd.png", "jen název bez cesty, jako metadata")
        self.assertEqual(len(self.files()), 1)
        self.assertFalse((Path(self.media).parent / "etc").exists())
        with self.assertRaises(media_storage.MediaError):
            media_storage.path_for("wot-screenshots", "../../x.png")
        with self.assertRaises(media_storage.MediaError):
            media_storage.path_for("wot-screenshots", "a" * 32 + ".exe")
        # podvržený název v DB se neservíruje
        sid = r.json()["id"]
        self.q(lambda db: (setattr(db.get(WotMilestoneScreenshot, sid), "stored_name", "../main.py"), db.commit()))
        self.assertEqual(self.client.get(f"/wot/screenshots/{sid}/file").status_code, 404)

    def test_missing_file_is_404_not_crash(self):
        s = self.upload(PNG).json()
        for n in self.files():
            (Path(self.media) / "wot-screenshots" / n).unlink()
        self.assertEqual(self.client.get(s["url"]).status_code, 404)
        self.assertEqual(self.client.get("/wot/milestones").status_code, 200)

    def test_delete_cleans_files(self):
        a = self.upload(PNG).json()
        self.upload(JPEG, "b.jpg")
        d = self.client.delete(f"/wot/screenshots/{a['id']}")
        self.assertEqual(d.json()["file_removed"], True)
        self.assertEqual(len(self.files()), 1)
        self.assertEqual(self.client.delete(f"/wot/screenshots/{a['id']}").status_code, 404)
        out = self.client.delete(f"/wot/milestones/{self.mid}").json()
        self.assertEqual(out["files_removed"], 1)
        self.assertEqual(self.files(), [])
        self.assertEqual(self.q(lambda db: db.query(WotMilestoneScreenshot).count()), 0)

    def test_caption_and_reorder(self):
        ids = [self.upload(PNG).json()["id"] for _ in range(3)]
        r = self.client.patch(f"/wot/screenshots/{ids[2]}", json={"position": 0, "caption": "Výsledková tabulka"})
        self.assertEqual(r.status_code, 200)
        shots = self.client.get("/wot/milestones").json()[0]["screenshots"]
        self.assertEqual([s["id"] for s in shots], [ids[2], ids[0], ids[1]])
        self.assertEqual(shots[0]["caption"], "Výsledková tabulka")
        self.assertEqual(self.client.patch(f"/wot/screenshots/{ids[0]}", json={"position": -1}).status_code, 400)

    def test_limit_per_milestone_and_missing_milestone(self):
        with patch.object(ws, "MAX_SCREENSHOTS", 2):
            self.upload(PNG)
            self.upload(PNG)
            self.assertEqual(self.upload(PNG).status_code, 400)
        self.assertEqual(self.upload(PNG, mid=999).status_code, 404)
        self.assertEqual(len(self.files()), 2)


if __name__ == "__main__":
    unittest.main()
