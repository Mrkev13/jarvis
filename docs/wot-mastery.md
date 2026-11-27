# WoT – M-ka všech tanků z Wargaming API (MRK-106)

Tabulka na `/wot` („M-ka všech tanků“) ukazuje u každého odehraného tanku **nejvyšší odznak mistrovství**
(M / I / II / III / žádný) bez ručního zadávání. Nové M se zapíše samo do milníků a čeká na replay, který doplní
statistiky bitvy.

## Co Wargaming API umí a co ne

Ověřeno v oficiální referenci (developers.wargaming.net, 2026-11-24):

- `tanks/stats` → `mark_of_mastery`: *0 — None, 1 — 3rd Class, 2 — 2nd Class, 3 — 1st Class, 4 — Ace Tanker*.
  Jen **nejvyšší** odznak na tank.
- `tanks/achievements` / `account/achievements`: odznaky mistrovství mají hodnotu *1-4 (type: "class")*. Je to zase
  třída, **ne počet**. API tedy nikde neřekne, kolikrát má tank M.
- Statistiky jsou **součty za tank**, ne za bitvu. Poškození, mapu a výsledek konkrétní bitvy má jen replay.
- Veřejná data: stačí `application_id` + `account_id` (dohledá se přes `account/list`, `type=exact`), žádný token.

## Jak to funguje

1. Hodinový krok `wot mastery sync` (každou hodinu, nejvýš jednou za 50 min – MRK-146) a tlačítko *Obnovit* stáhnou odznaky všech tanků
   do `wot_vehicle_mastery` (migrace `0034_wot_vehicle_mastery`). U nových tanků doplní název, tag, tier, národ
   a typ z `encyclopedia/vehicles`.
2. **První synchronizace je jen výchozí stav.** Stará M nemají datum, takže žádné milníky nevznikají.
3. Každá další synchronizace, která uvidí přechod tanku na 4 (Ace), založí milník `source="api"`:
   - tank, odznak M, datum detekce, poznámka „nahraj replay“;
   - doménová událost `wot.mastery.ace_detected` → „Mise splněna“, Co se změnilo.

   Podmíněný update zajistí, že i při souběhu vznikne jen jeden milník.
4. Milník „čeká na replay“, dokud k němu není propojený replay. Nahraný replay se **spáruje sám**, když platí:
   - odznak v replayi je M,
   - stejný tank (tag z hlavičky, jinak název),
   - bitva nejpozději den po detekci. Pozdější bitva je opakované M, to se nepáruje.

   Párování doplní mapu, datum bitvy, poškození, asistenci, zabití a základní XP. *Vytvořit Mko z replaye* použije
   čekající milník místo zakládání duplicity.
5. **Opakovaná M na tanku, který už M má, API nepozná.** Zapisují se jako dřív: ručně nebo z replaye. Tabulka je
   ukáže jako „M ×N“ (počet M milníků toho tanku).

## Cíl „M-ka celkem“

Zdroj `wot_ace_mastery_count` se nemění: počítá všechny M milníky (MRK-82, včetně opakovaných). Automaticky
zjištěná M jsou milníky, takže se započítají sama (Standa, 2026-11-24: cíl = M-ka celkem).

## AI

- Read tool `get_wot_mastery` (`tool_registry.py`) přijímá filtry `tier`, `nation` (ussr / SSSR…) a `mastery`
  (`ace`, `first`, `second`, `third`, `none`, `without_ace`), plus `limit`.
- Vrací spočítaný výsledek ze snapshotu, bez API a bez počítání v LLM. Odpoví třeba na „Které osmičky ještě nemám
  na M?“.
- AI kontext WoT má navíc jeden souhrnný řádek (počty podle odznaku, M čekající na replay).

## Konfigurace (jen server, `.env.production`)

| Proměnná | Význam |
| --- | --- |
| `WG_APPLICATION_ID` | aplikace z developers.wargaming.net (stejná jako pro obrázky tanků, `docs/game-assets.md`) |
| `WG_REGION` | `eu` (výchozí), `na`, `asia` |
| `WOT_NICKNAME` | přezdívka hráče (účet se dohledá podle ní) |

Bez nich tabulka ukáže návod a ruční M-ka fungují dál. Skrytý profil ve hře = stav „statistiky jsou skryté“.

## Bezpečnost

- Jen HTTPS na `api.worldoftanks.{eu,com,asia}`, bez přesměrování, timeout 15 s, odpověď max 4 MB.
- Chyby nesou jen kód (`unauthorized`, `rate_limited`, `private`…), nikdy URL (obsahuje `application_id`) ani odpověď.
- Do DB, odpovědí REST, Aktivity ani AI kontextu se nedostane `application_id`, `account_id` ani přezdívka.
- Testy `backend/tests/test_wot_mastery_api.py` používají falešný transport, nikdy síť.
