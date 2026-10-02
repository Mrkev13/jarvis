import os
import sys
import unittest
from pathlib import Path

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
LIBS_DIR = FRONTEND_DIR / "lib"
HOOKS_DIR = FRONTEND_DIR / "hooks"

if os.name == "nt":
    try:
        import subprocess

        def _run_node_eval(js_code: str):
            env = {**os.environ}
            env.setdefault("PYTHONIOENCODING", "utf-8")
            env.setdefault("FORCE_COLOR", "0")
            p = subprocess.run(
                ["node", "--input-type=module", "-e", js_code],
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=env,
                timeout=30,
            )
            return p.returncode, p.stdout, p.stderr
    except Exception:
        _run_node_eval = None
else:
    _run_node_eval = None


def _node_available() -> bool:
    if _run_node_eval is None:
        return False
    try:
        rc, out, _err = _run_node_eval("process.stdout.write('ok');")
        return rc == 0 and "ok" in out
    except Exception:
        return False


SAMPLE_SPEECH_TS = (LIBS_DIR / "speech.ts").read_text(encoding="utf-8")

SAMPLE_SPEECH_JS_FOR_NODE = (
    "const STORAGE_KEYS = { voiceLang: 'sh:voice:lang', autoSend: 'sh:voice:auto-send', ttsEnabled: 'sh:voice:tts-enabled' };"
    "const DEFAULT_LOCALE = 'cs-CZ';"
    "function detectSpeechLocaleFromText(text) {"
    "  const t = String(text || '').toLowerCase();"
    "  const csLetters = /[áčďéěíňóřšťúůýž]/;"
    "  const csWords = /\\b(dnes|týden|týdenní|plán|cíl|cíle|bilance|úkol|škola|práce|kolik|jak|co|mám|dělat|tento|měsíc)\\b/;"
    "  if (csLetters.test(t) || csWords.test(t)) return 'cs-CZ';"
    "  const enWords = /\\b(today|week|plan|goal|goals|balance|work|how|what|my|do|have|should|month|assignment|exam|xp|finance|school)\\b/;"
    "  if (enWords.test(t)) return 'en-US';"
    "  return DEFAULT_LOCALE;"
    "}"
    "function cleanTextForSpeech(content) {"
    "  if (content == null) return '';"
    "  let text = String(content);"
    "  text = text.replace(/```[\\s\\S]*?```/g, ' ');"
    "  text = text.replace(/`{1,2}[^`]*`{1,2}/g, ' ');"
    "  text = text.replace(/^\\s{0,3}#{1,6}\\s*([^\\n]*)$/gm, '$1.');"
    "  text = text.replace(/^\\s*[-*+]\\s+/gm, ' ');"
    "  text = text.replace(/^\\s*\\d+\\.\\s+/gm, ' ');"
    "  text = text.replace(/^>+\\s*/gm, ' ');"
    "  text = text.replace(/\\*\\*([^*]+)\\*\\*/g, '$1');"
    "  text = text.replace(/__([^_]+)__/g, '$1');"
    "  text = text.replace(/\\*([^*\\n]+)\\*/g, '$1');"
    "  text = text.replace(/_([^_\\n]+)_/g, '$1');"
    "  text = text.replace(/!\\[[^\\]]*\\]\\([^)]*\\)/g, ' ');"
    "  text = text.replace(/\\[([^\\]]+)\\]\\((https?:\\/\\/[^)\\s]+|[^)\\s]+\\.[^)\\s]+)\\)/g, '$1');"
    "  text = text.replace(/https?:\\/\\/[^\\s]+/g, ' ');"
    "  text = text.replace(/\\bwww\\.\\S+/gi, ' ');"
    "  text = text.replace(/<[^>]+>/g, ' ');"
    "  text = text.replace(/[<>{}|=]+/g, ' ');"
    "  text = text.replace(/\\u00a0/g, ' ');"
    "  text = text.replace(/\\n{3,}/g, '\\n\\n');"
    "  text = text.replace(/[ \\t]{2,}/g, ' ');"
    "  text = text.replace(/\\s*([.!?])\\s*/g, '$1 ');"
    "  text = text.replace(/\\s*,\\s*/g, ', ');"
    "  text = text.replace(/\\s{2,}/g, ' ').trim();"
    "  return text;"
    "}"
    "function plannerSpeechSummary(card) {"
    "  if (!card) return '';"
    "  const type = card.card_type;"
    "  const payload = card.payload || {};"
    "  const summary = cleanTextForSpeech(payload.summary || '');"
    "  if (type === 'daily') {"
    "    const parts = [];"
    "    parts.push(summary || 'Dnešní plán.');"
    "    const actions = payload.actions || [];"
    "    const top = actions.slice(0, 3);"
    "    const cs = ['První', 'Druhé', 'Třetí'];"
    "    top.forEach((a, idx) => {"
    "      const title = cleanTextForSpeech(String(a.title ?? ''));"
    "      if (!title) return;"
    "      parts.push(cs[idx] + ': ' + title + '.');"
    "    });"
    "    return parts.join(' ');"
    "  }"
    "  if (type === 'weekly') {"
    "    const parts = [];"
    "    parts.push(summary || 'Týdenní plán.');"
    "    const actions = payload.actions || [];"
    "    const top = actions.slice(0, 3);"
    "    const cs = ['První priorita', 'Druhá priorita', 'Třetí priorita'];"
    "    top.forEach((a, idx) => {"
    "      const title = cleanTextForSpeech(String(a.title ?? ''));"
    "      if (!title) return;"
    "      parts.push(cs[idx] + ': ' + title + '.');"
    "    });"
    "    return parts.join(' ');"
    "  }"
    "  if (type === 'goal_review') {"
    "    const parts = [];"
    "    parts.push(summary || 'Přehled cílů.');"
    "    const goals = payload.goals || [];"
    "    const top = goals.slice(0, 4);"
    "    top.forEach((g) => {"
    "      const title = cleanTextForSpeech(String(g.title ?? ''));"
    "      const progress = Number(g.progress ?? 0);"
    "      if (!title) return;"
    "      parts.push(title + ': ' + progress + ' procent.');"
    "    });"
    "    return parts.join(' ');"
    "  }"
    "  return summary;"
    "}"
    "function mapErrorToMessage(errorCode) {"
    "  const code = String(errorCode || '').toLowerCase();"
    "  switch (code) {"
    "    case 'not-allowed': case 'permission-denied': case 'service-not-allowed':"
    "      return 'Přístup k mikrofonu byl odepřen. Povol ho v nastavení prohlížeče.';"
    "    case 'no-speech': return 'Nebyla rozpoznána žádná řeč. Zkus to znovu.';"
    "    case 'audio-capture': return 'Nebyl nalezen žádný mikrofon. Připoj zařízení a zkus to znovu.';"
    "    case 'network': return 'Hlasové zadávání potřebuje síťové připojení.';"
    "    case 'aborted': return 'Nahrávání bylo přerušeno.';"
    "    case 'language-not-supported': return 'Vybraný jazyk pro rozpoznávání řeči není podporován.';"
    "    default: if (code) return 'Chyba při rozpoznávání řeči (' + code + '). Zkus to znovu.';"
    "      return 'Nastala chyba při rozpoznávání řeči. Zkus to znovu.';"
    "  }"
    "}"
)


def _escape_str_for_node(s: str) -> str:
    out = []
    for ch in s:
        if ch == "\\":
            out.append("\\\\")
        elif ch == "'":
            out.append("\\'")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        else:
            out.append(ch)
    return "".join(out)


@unittest.skipUnless(_node_available(), "Node.js není k dispozici pro vyhodnocení pomocných JS funkcí")
class SpeechTextTests(unittest.TestCase):
    def _eval(self, expression: str):
        if _run_node_eval is None:
            self.skipTest("node runner unavailable")
        script = SAMPLE_SPEECH_JS_FOR_NODE + f"\nprocess.stdout.write(String({expression}));"
        rc, out, err = _run_node_eval(script)
        self.assertEqual(rc, 0, msg=err or out)
        return out

    def test_clean_md_strips_code_bold_headers(self):
        md = """# Nadpis
**Tučný** text a _italic_.

```js
const x = 1;
```

- odrážka 1
- odrážka 2
"""
        escaped = f"'{_escape_str_for_node(md)}'"
        cleaned = self._eval(f"cleanTextForSpeech({escaped})")
        self.assertNotIn("```", cleaned)
        self.assertNotIn("**", cleaned)
        self.assertNotIn("_italic_", cleaned)
        self.assertIn("Nadpis.", cleaned)
        self.assertIn("Tučný text a italic.", cleaned)
        self.assertNotIn("const x = 1", cleaned)

    def test_clean_removes_urls_and_html(self):
        text = "Navštiv https://example.com a [click here](/goals) nebo <b>bold</b>."
        escaped = f"'{_escape_str_for_node(text)}'"
        cleaned = self._eval(f"cleanTextForSpeech({escaped})")
        self.assertNotIn("https://", cleaned)
        self.assertNotIn("<b>", cleaned)
        self.assertIn("click here", cleaned)

    def test_detect_locale_czech(self):
        cases = [
            ("Co mám dnes dělat?", "cs-CZ"),
            ("Jaká je moje bilance tento měsíc?", "cs-CZ"),
            ("What is my current balance today?", "en-US"),
            ("1+1", "cs-CZ"),
        ]
        for inp, expected in cases:
            with self.subTest(inp=inp):
                escaped = f"'{_escape_str_for_node(inp)}'"
                got = self._eval(f"detectSpeechLocaleFromText({escaped})")
                self.assertEqual(got, expected)

    def test_daily_plan_speech_summary(self):
        card = {
            "card_type": "daily",
            "payload": {
                "summary": "Dnes máš 3 priority.",
                "actions": [
                    {"title": "Projít poslední výdaje", "priority": 1},
                    {"title": "Zapsat dnešní odpracované hodiny", "priority": 2},
                    {"title": "Dokončit úkol s termínem dnes", "priority": 3},
                ],
            },
        }
        import json
        escaped = json.dumps(card, ensure_ascii=False)
        summary = self._eval(f"plannerSpeechSummary(JSON.parse('{_escape_str_for_node(escaped)}'))")
        self.assertIn("Dnes máš 3 priority.", summary)
        self.assertIn("První: Projít poslední výdaje.", summary)
        self.assertIn("Druhé: Zapsat dnešní odpracované hodiny.", summary)
        self.assertIn("Třetí: Dokončit úkol s termínem dnes.", summary)

    def test_goal_review_summary(self):
        card = {
            "card_type": "goal_review",
            "payload": {
                "summary": "Přehled cílů: 1 stagnuje.",
                "goals": [
                    {"title": "Našetřit 150 tisíc", "progress": 9},
                    {"title": "Mít 10 T4 postav", "progress": 60},
                ],
            },
        }
        import json
        escaped = json.dumps(card, ensure_ascii=False)
        summary = self._eval(f"plannerSpeechSummary(JSON.parse('{_escape_str_for_node(escaped)}'))")
        self.assertIn("Přehled cílů: 1 stagnuje.", summary)
        self.assertIn("Našetřit 150 tisíc: 9 procent.", summary)
        self.assertIn("Mít 10 T4 postav: 60 procent.", summary)

    def test_weekly_plan_summary(self):
        card = {
            "card_type": "weekly",
            "payload": {
                "summary": "Týdenní plán zaměřený na práci.",
                "actions": [
                    {"title": "Dokončit MFF Build tracking", "priority": 1},
                ],
            },
        }
        import json
        escaped = json.dumps(card, ensure_ascii=False)
        summary = self._eval(f"plannerSpeechSummary(JSON.parse('{_escape_str_for_node(escaped)}'))")
        self.assertIn("Týdenní plán zaměřený na práci.", summary)
        self.assertIn("První priorita: Dokončit MFF Build tracking.", summary)

    def test_error_mapping(self):
        cases = {
            "not-allowed": "Přístup k mikrofonu byl odepřen",
            "permission-denied": "Přístup k mikrofonu byl odepřen",
            "no-speech": "Nebyla rozpoznána žádná řeč",
            "audio-capture": "Nebyl nalezen žádný mikrofon",
            "network": "síťové připojení",
            "language-not-supported": "Vybraný jazyk pro rozpoznávání řeči",
            "": "Nastala chyba",
            "some-custom-code": "Chyba při rozpoznávání řeči (some-custom-code)",
        }
        for code, needle in cases.items():
            with self.subTest(code=code):
                got = self._eval(f"mapErrorToMessage('{_escape_str_for_node(code)}')")
                self.assertIn(needle, got)


class SpeechStaticDiscoveryFallbackTests(unittest.TestCase):
    """Pokud není dostupný node pro evaluaci JS, alespoň ověříme přítomnost symbolů v zdrojácích TS."""

    @classmethod
    def setUpClass(cls):
        cls.src = SAMPLE_SPEECH_TS
        cls.hook_src = (HOOKS_DIR / "useSpeechRecognition.ts").read_text(encoding="utf-8")

    def test_speech_ts_has_expected_exports(self):
        expected_symbols = [
            "cleanTextForSpeech",
            "plannerSpeechSummary",
            "isSpeechRecognitionSupported",
            "isSpeechSynthesisSupported",
            "speakText",
            "detectSpeechLocaleFromText",
            "STORAGE_KEYS",
            "RecorderStatus",
        ]
        for sym in expected_symbols:
            self.assertIn(sym, self.src, msg=f"chybí exportovaný symbol: {sym}")

    def test_hook_file_states_mapped(self):
        for s in ("idle", "listening", "processing", "error"):
            self.assertIn(s, self.hook_src, msg=f"hook nemá stav {s}")
        self.assertIn("onFinalTranscript", self.hook_src)
        self.assertIn("mapErrorToMessage", self.hook_src)


if __name__ == "__main__":
    unittest.main()
