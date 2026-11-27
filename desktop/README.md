# Jarvis pro PC (MRK-156)

Malá aplikace pro Windows. Běží na pozadí s ikonou v oznamovací oblasti a provádí potvrzené příkazy ze
Standa Hubu:

- spustit aplikaci ze seznamu;
- vypnout, uspat nebo zamknout PC, i s časovačem a možností zrušit;
- posílat stav PC: online, vytížení, disky a co běží.

Backend a bezpečnost: [docs/computer.md](../docs/computer.md).

## Instalace

1. Stáhni instalátor z GitHub Actions: workflow **Desktop agent** → poslední běh → artefakt
   `jarvis-pro-pc-windows` (.zip s instalátorem `Jarvis pro PC_…_x64-setup.exe`).
2. Spusť ho. Instaluje se jen pro tvůj účet a nepotřebuje práva správce.
   Instalátor zatím není podepsaný, takže Windows SmartScreen ukáže varování: **Další informace → Přesto spustit**.
3. Aplikace potřebuje WebView2. Windows 10 a 11 ho obvykle mají, jinak ho instalátor doinstaluje.

## Spárování

1. V Hubu vytvoř párovací kód. Zatím jen přes API `POST /devices/pairing-code`, stránka Počítač přijde s MRK-157.
2. V okně Jarvise vyplň:
   - **Adresa Hubu** – stejná jako adresa API v prohlížeči, `https://…:8443`;
   - **kód** – platí 10 minut a jen jednou;
   - **název počítače**.
3. Token zařízení se uloží do **Správce pověření Windows**, nikam jinam. Odvolat ho jde v Hubu. Odpárování
   v aplikaci token smaže jen z PC, v Hubu zařízení ještě odvolej.

## Aplikace

- Při prvním spuštění Jarvis sám najde World of Tanks (běžná umístění klienta), Wargaming Game Center, Steam a
  Discord. **Najít znovu** hledání zopakuje a ručně přidané položky přitom zachová.
- Další aplikaci přidáš pod **Přidat aplikaci**: název, cesta k `.exe`, zástupce `.lnk` nebo odkaz (`steam://…`).
  Volitelně přidáš argumenty a název procesu, podle kterého Hub pozná, že aplikace běží.
- Hub zná jen id a název aplikace. Cestu a argumenty má jen tohle PC a Hub je poslat nemůže.

## Napájení

- **Vypnout**, **uspat** a **zamknout** běží přes časovač v aplikaci (0 s až 4 h).
- Okamžitá akce počká 3 s, aby aplikace stihla Hubu nahlásit výsledek.
- Zrušit jde:
  - z Hubu;
  - z okna;
  - z ikony v oznamovací oblasti (**Zrušit časovač napájení**).
- Když aplikaci ukončíš, časovač zanikne.
- Se zapnutou hibernací Windows místo uspání hibernuje (`powercfg /hibernate off` to vypne).

## Okno a ikona

- Zavření okna aplikaci neukončí, dál běží v oznamovací oblasti. Ukončí se přes ikonu → **Ukončit**.
- **Pozastavit** zastaví komunikaci s Hubem a v Hubu bude PC offline.
- **Spouštět s Windows** zapne automatický start na pozadí, bez okna.
- Nastavení je v `%APPDATA%\StandaHub\jarvis-agent.json`, bez tokenu.

## Vývoj

```bash
cd desktop
cargo test -p agent-core      # jádro (protokol, konfigurace, příkazy, smyčka) – běží i na Linuxu
cargo build -p jarvis-agent   # aplikace; na Linuxu jen překlad (akce vrací chybu), Linux potřebuje webkit2gtk
npm ci && npm run build       # instalátor (na Windows)
```

- `agent-core/` – čistá logika bez Windows a Tauri. Síť (`HubApi`) a systém (`Executor`) jsou vstřiknuté,
  testy používají falešný Hub i systém.
- `src-tauri/` – aplikace: tray, okno (`ui/`, bez bundleru, jen vlastní příkazy přes `invoke`), vlákno agenta
  (heartbeat 30 s, long-poll 15 s, backoff 5–60 s) a vlákno časovače napájení. Windows akce jsou v `system.rs`.
