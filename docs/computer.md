# Počítač – Jarvis na PC (MRK-154)

Agent Jarvise na Windows PC: spustí aplikaci, vypne / uspí / zamkne PC (i s časovačem), hlásí stav a nahrává WoT
replaye. Tenhle dokument popisuje backendový základ (MRK-155): párování, token zařízení, stav a frontu příkazů.
Aplikace pro Windows je MRK-156, stránka Počítač a Jarvis MRK-157 (níže), replaye MRK-158, postavička MRK-17.

## Principy bezpečnosti

- **Agent se připojuje sám ven** k Hubu (přes Tailscale, stejná adresa API jako frontend). Na PC se neotevírá port.
- **Token zařízení** (`secrets.token_urlsafe(32)`) vidí jen agent v odpovědi na párování; v DB je jen SHA-256 hash
  (`devices.token_hash`). Platí **jen** pro `/device/agent/*`:
  - `main.require_auth` tuhle cestu propouští bez session cookie (`DEVICE_AGENT_PREFIX`) a `router.require_device`
    tam vyžaduje `Authorization: Bearer <token>` – session cookie na endpointy agenta nestačí;
  - jinde token neplatí, protože `require_auth` čte jen session cookie.
  - Pozor: když je přihlašování vypnuté (prázdný `AUTH_PIN_HASH`, jen vývoj), uživatelské `/devices/*` jsou otevřené
    jako celé API; endpointy agenta token chtějí vždy.
- **Párovací kód** – 8 znaků bez zaměnitelných (`ABCD-EFGH`), v DB hash, platí 10 min, jednou; nový kód zneplatní
  předchozí. Neplatné pokusy: max 5 za 10 min z jedné adresy (pak 429). Max 5 aktivních zařízení.
- **Odvolání** (`POST /devices/{id}/revoke`) nastaví `revoked_at`: token přestane platit okamžitě, čekající příkazy
  propadnou. Řádek se nemaže (historie příkazů).
- **Jen allowlist příkazů** (`modules/computer/models.COMMAND_KINDS`), payload se přepíše jen na povolená pole:

  | kind | payload | poznámka |
  |---|---|---|
  | `launch_app` | `app_id` | jen aplikace, kterou agent sám nahlásil v heartbeatu; Hub nikdy neposílá cestu ani argumenty |
  | `power` | `action` (`shutdown` / `sleep` / `lock`), `delay_seconds` 0–14400 | časovač drží agent |
  | `power_cancel` | – | zruší časovač |

- **Krátká platnost** – příkaz platí 2 min (`COMMAND_TTL`); nevyzvednutý propadne (`expired`), vypnuté PC ho nikdy
  neprovede pozdě. Vyzvednutý bez výsledku do 10 min taky propadne. Příkaz pro PC, které není online (heartbeat
  starší než 90 s), se vůbec nevytvoří (409). Propadání je líné (při čtení / vyzvednutí), bez scheduleru.
- Tlačítko v Hubu = potvrzení. Jarvis bude příkazy zakládat až po potvrzení pending akce (MRK-157), nikdy přímo.

## API

Uživatel (session):

| | |
|---|---|
| `GET /devices` | aktivní zařízení: `online`, `last_seen_at`, `status`, `apps` (nikdy token ani hash) |
| `POST /devices/pairing-code` | `{code, expires_at}` |
| `PATCH /devices/{id}` | přejmenování `{name}` |
| `POST /devices/{id}/revoke` | odvolání |
| `GET /devices/{id}/commands?limit=` | posledních N příkazů se stavem a výsledkem |
| `POST /devices/{id}/commands` | `{kind, payload}` → zařazený příkaz |

Agent (token zařízení, kromě párování):

| | |
|---|---|
| `POST /device/agent/pair` | `{code, name, platform: "windows", agent_version}` → `{device_id, name, token}` |
| `POST /device/agent/heartbeat` | `{status, apps, agent_version}` každých ~30 s |
| `GET /device/agent/commands?wait=0..25` | long-poll; vrací a označí `delivered` čekající platné příkazy |
| `POST /device/agent/commands/{id}/result` | `{ok, message}` → `succeeded` / `failed` |

Heartbeat ukládá jen známá pole s mezemi (`service.sanitize_status`): `cpu_percent`, `ram_percent`,
`uptime_minutes`, `disks` [`name`, `free_gb`, `total_gb`] (max 12) a `running` (jen id z nahlášených aplikací).
Aplikace: `[{id, name}]`, `id` = `[a-z0-9][a-z0-9_-]{0,39}`, max 50.

## Audit a události

Do Aktivity (oblast `computer`) ve stejné transakci: vytvoření párovacího kódu, spárování, přejmenování, odvolání,
zařazení příkazu, výsledek a propadnutí. Fakta jsou doménové události (`docs/domain-events.md`):
`computer.device.paired`, `computer.device.revoked`, `computer.command.completed` / `.failed` / `.expired`.
Heartbeat (`last_seen_at`, `status`, `apps`) a čas vyzvednutí (`delivered_at`) jsou provozní telemetrie bez Aktivity
(jako `last_seen_at` přihlašovací session).

## Aplikace pro Windows (MRK-156)

`desktop/` – Tauri 2 aplikace „Jarvis pro PC“ (návod: [desktop/README.md](../desktop/README.md)). Token ve Správci
pověření Windows, nastavení (bez tokenu) v `%APPDATA%\StandaHub\jarvis-agent.json`. Heartbeat každých 30 s,
long-poll 15 s, po chybě backoff 5–60 s; odmítnutý token (odvoláno) agenta zastaví, dokud se znovu nespáruje.
Napájení běží přes časovač v aplikaci (okamžitá akce počká 3 s na nahlášení výsledku). CI: workflow
`.github/workflows/desktop.yml` (jádro na Linuxu, build + instalátor NSIS na Windows → artefakt
`jarvis-pro-pc-windows`).

## Stránka Počítač a Jarvis (MRK-157)

- **Stránka `/devices`** (navigace „Počítač“ ve skupině Další, `frontend/modules/computer/`). Ukazuje:
  - online / offline, kdy se PC naposledy ohlásilo, procesor, paměť, jak dlouho je zapnuté, co běží a disky;
  - tlačítka aplikací z místního seznamu PC;
  - **Napájení**: časovač Hned / 15 min / 30 min / hodina / 2 h / 4 h. Vypnout a uspat jen přes potvrzovací dialog,
    zamknout hned. K tomu **Zrušit časovač**;
  - posledních 5 příkazů se stavem (Čeká na PC → Hotovo / Selhalo / Propadlo);
  - **Spárovat počítač**: kód a adresa Hubu pro aplikaci;
  - **Odvolat počítač**.

  Klik na tlačítko je potvrzení. Dokud čeká nějaký příkaz, stránka se obnovuje každé 3 s, jinak každých 15 s.
- **Jarvis**:
  - jeden write tool `manage_computer`: `launch_app` (aplikace podle názvu nebo id ze seznamu PC), `shutdown` /
    `sleep` / `lock` (volitelně `delay_minutes` ≤ 240) a `cancel_timer`;
  - resolver (`modules/computer/ai_actions.py`) ověří PC (jedno, nebo podle názvu), aplikaci (nejednoznačná nebo
    neznámá → `not_prepared` s kandidáty) a online stav. Do plánu uloží přesný příkaz;
  - potvrzení pending akce ho zařadí do fronty (`user_context=ai_confirm`). PC mezitím offline, odvolané nebo bez
    aplikace → `StaleTarget`, nic se neodešle;
  - stav PC dostává Jarvis v CURRENT STATE sekci modulu (`integrations.context_computer`: online, co běží, co umí
    spustit, poslední příkaz). Samostatný read tool není, ušetří tokeny.
- **Routing** (`tool_router.py`):
  - slovesa `spusť / pusť / vypni / uspi / zamkni / zapni` znamenají write záměr;
  - s oblastí Počítač a příkazovým slovesem (nebo „zruš“) se nabídne jen `manage_computer`, takže „hodinu“
    není práce a „WoT“ není grind;
  - „připomeň mi za hodinu vypnout PC“ zůstává připomínka;
  - „zapiš 2 hodiny práce na počítači“ zůstává práce.

Migrace `0037_computer_devices` (tabulky `devices`, `device_pairing_codes`, `device_commands`), testy
`backend/tests/test_computer_devices.py`, `backend/tests/test_computer_ai.py`.
