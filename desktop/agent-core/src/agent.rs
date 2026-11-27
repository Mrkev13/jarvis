//! Smyčka agenta: heartbeat, vyzvednutí příkazů, provedení přes `Executor`, hlášení výsledku, časovač napájení.
//!
//! Bezpečnost: Hub posílá jen id aplikace a akci napájení; co přesně se spustí, určuje výhradně místní seznam
//! aplikací (`AgentConfig.apps`). Neznámý druh příkazu se odmítne a nahlásí jako chyba.

use std::collections::VecDeque;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use serde::Serialize;

use crate::client::{ApiError, HubApi};
use crate::config::{AgentConfig, AppEntry};
use crate::protocol::{Command, CommandResult, Heartbeat, Status};

pub const HEARTBEAT_EVERY: Duration = Duration::from_secs(30);
pub const POLL_WAIT_SECONDS: u32 = 15;
pub const MAX_DELAY_SECONDS: u64 = 4 * 3600;
/// Okamžitá akce napájení počká chvilku, aby agent stihl Hubu nahlásit výsledek (po vypnutí už nic nepošle).
pub const IMMEDIATE_GRACE: Duration = Duration::from_secs(3);
const RECENT_MAX: usize = 10;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum PowerAction {
    Shutdown,
    Sleep,
    Lock,
}

impl PowerAction {
    pub fn parse(s: &str) -> Option<Self> {
        match s {
            "shutdown" => Some(Self::Shutdown),
            "sleep" => Some(Self::Sleep),
            "lock" => Some(Self::Lock),
            _ => None,
        }
    }

    pub fn label(self) -> &'static str {
        match self {
            Self::Shutdown => "Vypnutí",
            Self::Sleep => "Uspání",
            Self::Lock => "Zamknutí",
        }
    }
}

/// Systémové akce – na Windows skutečné (src-tauri), v testech falešné.
pub trait Executor {
    fn launch(&self, app: &AppEntry) -> Result<(), String>;
    fn power(&self, action: PowerAction) -> Result<(), String>;
    fn status(&self, apps: &[AppEntry]) -> Status;
}

#[derive(Debug, Default)]
pub struct PowerTimer {
    pending: Option<(PowerAction, Instant)>,
}

impl PowerTimer {
    pub fn set(&mut self, action: PowerAction, at: Instant) {
        self.pending = Some((action, at));
    }

    pub fn cancel(&mut self) -> bool {
        self.pending.take().is_some()
    }

    pub fn pending(&self) -> Option<(PowerAction, Instant)> {
        self.pending
    }

    /// Akce, jejíž čas nastal (a zároveň ji zruší, ať se neprovede dvakrát).
    pub fn take_due(&mut self, now: Instant) -> Option<PowerAction> {
        match self.pending {
            Some((action, at)) if now >= at => {
                self.pending = None;
                Some(action)
            }
            _ => None,
        }
    }
}

/// Provede jeden příkaz z Hubu. Vrací (ok, zpráva pro Hub a historii).
pub fn handle_command(
    cmd: &Command,
    cfg: &AgentConfig,
    exec: &dyn Executor,
    timer: &mut PowerTimer,
    now: Instant,
) -> (bool, String) {
    match cmd.kind.as_str() {
        "launch_app" => {
            let id = cmd
                .payload
                .get("app_id")
                .and_then(|v| v.as_str())
                .unwrap_or("");
            match cfg.app(id) {
                None => (false, "Aplikace není v seznamu tohoto PC.".into()),
                Some(app) => match exec.launch(app) {
                    Ok(()) => (true, format!("Spuštěno: {}", app.name)),
                    Err(e) => (false, format!("Nepodařilo se spustit {}: {e}", app.name)),
                },
            }
        }
        "power" => {
            let action = cmd
                .payload
                .get("action")
                .and_then(|v| v.as_str())
                .and_then(PowerAction::parse);
            let delay = cmd.payload.get("delay_seconds").map(|v| v.as_u64());
            match (action, delay) {
                (None, _) => (false, "Neznámá akce napájení.".into()),
                (Some(_), Some(None)) => (false, "Neplatný časovač.".into()),
                (Some(_), Some(Some(d))) if d > MAX_DELAY_SECONDS => {
                    (false, "Časovač může být nejvýš 4 hodiny.".into())
                }
                (Some(action), delay) => {
                    let secs = delay.flatten().unwrap_or(0);
                    let wait = if secs == 0 {
                        IMMEDIATE_GRACE
                    } else {
                        Duration::from_secs(secs)
                    };
                    let replaced = timer.pending().is_some();
                    timer.set(action, now + wait);
                    let when = if secs == 0 {
                        "hned".to_string()
                    } else if secs >= 60 {
                        format!("za {} min", secs / 60)
                    } else {
                        format!("za {secs} s")
                    };
                    let note = if replaced {
                        " (nahradilo předchozí časovač)"
                    } else {
                        ""
                    };
                    (true, format!("{} {when}{note}", action.label()))
                }
            }
        }
        "power_cancel" => {
            if timer.cancel() {
                (true, "Časovač zrušen.".into())
            } else {
                (true, "Žádný časovač nečekal.".into())
            }
        }
        _ => (false, "Neznámý příkaz – agent ho neumí.".into()),
    }
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct RecentCommand {
    pub label: String,
    pub ok: bool,
    pub message: String,
    pub at_unix: u64,
}

/// Stav pro okno nastavení a tray.
#[derive(Debug, Clone, Default, Serialize)]
pub struct AgentState {
    pub connected: bool,
    pub last_error: Option<String>,
    /// token odmítnut (zařízení odvoláno v Hubu) → je potřeba znovu spárovat
    pub unauthorized: bool,
    pub recent: VecDeque<RecentCommand>,
    pub pending_power: Option<(PowerAction, u64)>,
}

pub fn command_label(cmd: &Command, cfg: &AgentConfig) -> String {
    match cmd.kind.as_str() {
        "launch_app" => {
            let id = cmd
                .payload
                .get("app_id")
                .and_then(|v| v.as_str())
                .unwrap_or("?");
            format!(
                "Spustit {}",
                cfg.app(id).map(|a| a.name.as_str()).unwrap_or(id)
            )
        }
        "power" => {
            let a = cmd
                .payload
                .get("action")
                .and_then(|v| v.as_str())
                .and_then(PowerAction::parse);
            a.map(|a| a.label().to_string())
                .unwrap_or_else(|| "Napájení".into())
        }
        "power_cancel" => "Zrušit časovač".into(),
        other => other.to_string(),
    }
}

fn unix_now() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0)
}

/// Vyzvednutý příkaz čekající na provedení (Hub ho už označil `delivered` – nesmí se ztratit).
struct Pending {
    cmd: Command,
    received: Instant,
}

/// Jedna obrátka smyčky agenta. Čas dalšího heartbeatu drží sám; časovač napájení a stav jsou sdílené (zámky se
/// drží jen krátce – nikdy přes long-poll), ať okno může časovač zrušit hned. Síť a systém jsou vstřiknuté.
///
/// Review #139:
/// - vyzvednutá dávka (`inbox`) a neodeslané výsledky (`outbox`) přežijí chybu sítě – další obrátka nejdřív
///   dohlásí výsledky, pak dokončí dávku a teprve potom znovu vyzvedává; provedený příkaz se nikdy neopakuje;
/// - `session` = generace párování/pauzy (mění ji okno). Každý příkaz se provádí pod jejím zámkem a jen když
///   generace sedí – rozpracovaný poll staré relace po odpárování / pozastavení nic nespustí ani nenastaví.
pub struct Agent {
    pub timer: Arc<Mutex<PowerTimer>>,
    next_heartbeat: Option<Instant>,
    pub version: String,
    inbox: VecDeque<Pending>,
    outbox: VecDeque<(i64, CommandResult)>,
}

fn lock<T>(m: &Mutex<T>) -> std::sync::MutexGuard<'_, T> {
    m.lock().unwrap_or_else(|e| e.into_inner())
}

/// Provede časovač napájení, pokud nastal (volá se každou sekundu ze samostatného vlákna, nezávisle na long-pollu),
/// a obnoví `pending_power` pro okno.
pub fn run_due_power(
    timer: &Mutex<PowerTimer>,
    exec: &dyn Executor,
    state: &Mutex<AgentState>,
    now: Instant,
) {
    let (due, pending) = {
        let mut t = lock(timer);
        (t.take_due(now), t.pending())
    };
    if let Some(action) = due {
        let res = exec.power(action);
        push_recent(
            &mut lock(state),
            RecentCommand {
                label: action.label().into(),
                ok: res.is_ok(),
                message: res.err().unwrap_or_else(|| "Provedeno.".into()),
                at_unix: unix_now(),
            },
        );
    }
    lock(state).pending_power =
        pending.map(|(a, at)| (a, at.saturating_duration_since(now).as_secs()));
}

/// Příkaz, který agent nestihl provést do té doby (např. dlouhý výpadek po vyzvednutí), se už neprovede –
/// Hub ho tou dobou stejně bere jako propadlý (platnost 2 min).
pub const LOCAL_COMMAND_TTL: Duration = Duration::from_secs(120);

#[derive(Debug, PartialEq)]
pub enum TickOutcome {
    /// vše v pořádku
    Ok,
    /// Hub nedostupný / chyba – volající počká (backoff)
    Retry,
    /// token neplatí – agent se zastaví, dokud se znovu nespáruje
    Unauthorized,
    /// relace se mezitím změnila (odpárování / pauza / nové párování) – zbytek dávky se zahodil bez provedení
    Stale,
}

impl Agent {
    pub fn new(version: &str) -> Self {
        Self {
            timer: Arc::new(Mutex::new(PowerTimer::default())),
            next_heartbeat: None,
            version: version.into(),
            inbox: VecDeque::new(),
            outbox: VecDeque::new(),
        }
    }

    /// Nová relace (jiný token / pauza): rozpracovaná dávka i neodeslané výsledky staré relace se zahodí.
    pub fn reset(&mut self) {
        self.inbox.clear();
        self.outbox.clear();
        self.next_heartbeat = None;
    }

    /// Kolik vyzvednutých příkazů a výsledků ještě čeká (pro testy a diagnostiku).
    pub fn backlog(&self) -> (usize, usize) {
        (self.inbox.len(), self.outbox.len())
    }

    /// `clock` = aktuální čas (po long-pollu se čte znovu, ať časovač napájení neběží o dobu čekání kratší).
    /// `session` / `expected` = generace relace, pro kterou tahle obrátka běží (viz typ `Agent`).
    #[allow(clippy::too_many_arguments)]
    pub fn tick(
        &mut self,
        hub: &dyn HubApi,
        exec: &dyn Executor,
        cfg: &AgentConfig,
        state: &Mutex<AgentState>,
        clock: &dyn Fn() -> Instant,
        poll_wait: u32,
        session: &Mutex<u64>,
        expected: u64,
    ) -> TickOutcome {
        let now = clock();
        if self.next_heartbeat.is_none_or(|t| now >= t) {
            let hb = Heartbeat {
                status: exec.status(&cfg.apps),
                apps: cfg.app_refs(),
                agent_version: self.version.clone(),
            };
            match hub.heartbeat(&hb) {
                Ok(()) => self.next_heartbeat = Some(now + HEARTBEAT_EVERY),
                Err(e) => return self.fail(state, e),
            }
        }
        // 1) nejdřív dohlásit výsledky, které minule neprošly (příkazy se znovu neprovádí)
        if let Err(outcome) = self.flush(hub, state) {
            return outcome;
        }
        // 2) nové příkazy jen tehdy, když z minulé dávky nic nezbylo
        if self.inbox.is_empty() {
            match hub.poll(poll_wait) {
                Ok(commands) => {
                    let received = clock();
                    self.inbox
                        .extend(commands.into_iter().map(|cmd| Pending { cmd, received }));
                }
                Err(e) => return self.fail(state, e),
            }
        }
        {
            let mut st = lock(state);
            st.connected = true;
            st.last_error = None;
            st.unauthorized = false;
        }
        // 3) provést dávku; každý výsledek hned hlásit (před okamžitým vypnutím – IMMEDIATE_GRACE)
        while let Some(p) = self.inbox.pop_front() {
            let (ok, message) = {
                let current = lock(session);
                if *current != expected {
                    self.inbox.clear();
                    return TickOutcome::Stale;
                }
                let now = clock();
                if now.saturating_duration_since(p.received) > LOCAL_COMMAND_TTL {
                    (
                        false,
                        "Příkaz propadl – agent ho nestihl provést včas.".to_string(),
                    )
                } else {
                    handle_command(&p.cmd, cfg, exec, &mut lock(&self.timer), now)
                }
            };
            push_recent(
                &mut lock(state),
                RecentCommand {
                    label: command_label(&p.cmd, cfg),
                    ok,
                    message: message.clone(),
                    at_unix: unix_now(),
                },
            );
            self.outbox.push_back((
                p.cmd.id,
                CommandResult {
                    ok,
                    message: Some(message),
                },
            ));
            if let Err(outcome) = self.flush(hub, state) {
                return outcome;
            }
        }
        TickOutcome::Ok
    }

    /// Odešle čekající výsledky popořadě. 404/409 = Hub příkaz už uzavřel (propadl) → výsledek se zahodí.
    fn flush(&mut self, hub: &dyn HubApi, state: &Mutex<AgentState>) -> Result<(), TickOutcome> {
        while let Some((id, result)) = self.outbox.front() {
            match hub.report(*id, result) {
                Ok(()) | Err(ApiError::Http(404 | 409, _)) => {
                    self.outbox.pop_front();
                }
                Err(e) => return Err(self.fail(state, e)),
            }
        }
        Ok(())
    }

    fn fail(&mut self, state: &Mutex<AgentState>, err: ApiError) -> TickOutcome {
        let mut state = lock(state);
        state.connected = false;
        state.last_error = Some(err.to_string());
        self.next_heartbeat = None; // po výpadku hned znovu ohlásit stav
        if matches!(err, ApiError::Unauthorized(_)) {
            state.unauthorized = true;
            TickOutcome::Unauthorized
        } else {
            TickOutcome::Retry
        }
    }
}

fn push_recent(state: &mut AgentState, item: RecentCommand) {
    state.recent.push_front(item);
    state.recent.truncate(RECENT_MAX);
}

/// Prodleva po chybě: 5, 10, 20, 40, 60, 60 … s.
pub fn backoff(failures: u32) -> Duration {
    Duration::from_secs((5u64 << failures.min(4)).min(60))
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use std::cell::RefCell;

    #[derive(Default)]
    struct FakeExec {
        launched: RefCell<Vec<String>>,
        power: RefCell<Vec<PowerAction>>,
        fail_launch: bool,
    }

    impl Executor for FakeExec {
        fn launch(&self, app: &AppEntry) -> Result<(), String> {
            if self.fail_launch {
                return Err("soubor nenalezen".into());
            }
            self.launched.borrow_mut().push(app.id.clone());
            Ok(())
        }
        fn power(&self, action: PowerAction) -> Result<(), String> {
            self.power.borrow_mut().push(action);
            Ok(())
        }
        fn status(&self, _apps: &[AppEntry]) -> Status {
            Status {
                cpu_percent: Some(10.0),
                ..Default::default()
            }
        }
    }

    static SESSION: Mutex<u64> = Mutex::new(0);

    #[derive(Default)]
    struct FakeHub {
        heartbeats: RefCell<usize>,
        polls: RefCell<usize>,
        queue: RefCell<Vec<Command>>,
        reports: RefCell<Vec<(i64, bool, String)>>,
        events: RefCell<Vec<String>>,
        unauthorized: bool,
        offline: bool,
        /// kolik dalších reportů selže síťovou chybou
        failing_reports: RefCell<u32>,
        /// odpověď Hubu na report (např. 409 = příkaz už propadl)
        report_status: Option<u16>,
        /// spustí se během long-pollu (simulace odpárování / pauzy v okně)
        during_poll: Option<Box<dyn Fn()>>,
    }

    impl HubApi for FakeHub {
        fn heartbeat(&self, _b: &Heartbeat) -> Result<(), ApiError> {
            if self.unauthorized {
                return Err(ApiError::Unauthorized("Neplatný token".into()));
            }
            if self.offline {
                return Err(ApiError::Network("connection refused".into()));
            }
            *self.heartbeats.borrow_mut() += 1;
            Ok(())
        }
        fn poll(&self, _w: u32) -> Result<Vec<Command>, ApiError> {
            if self.offline {
                return Err(ApiError::Network("connection refused".into()));
            }
            *self.polls.borrow_mut() += 1;
            if let Some(f) = &self.during_poll {
                f();
            }
            Ok(std::mem::take(&mut *self.queue.borrow_mut()))
        }
        fn report(&self, id: i64, r: &CommandResult) -> Result<(), ApiError> {
            self.events.borrow_mut().push(format!("report {id}"));
            if *self.failing_reports.borrow() > 0 {
                *self.failing_reports.borrow_mut() -= 1;
                return Err(ApiError::Network("connection reset".into()));
            }
            if let Some(code) = self.report_status {
                return Err(ApiError::Http(code, "Příkaz už je uzavřený.".into()));
            }
            self.reports
                .borrow_mut()
                .push((id, r.ok, r.message.clone().unwrap_or_default()));
            Ok(())
        }
    }

    fn cfg() -> AgentConfig {
        AgentConfig {
            apps: vec![AppEntry {
                id: "wot".into(),
                name: "World of Tanks".into(),
                target: "C:\\WoT.exe".into(),
                args: vec![],
                process: None,
                detected: true,
            }],
            ..Default::default()
        }
    }

    fn cmd(id: i64, kind: &str, payload: serde_json::Value) -> Command {
        Command {
            id,
            kind: kind.into(),
            payload,
        }
    }

    #[test]
    fn launch_only_apps_from_local_list() {
        let (exec, mut timer, now) = (FakeExec::default(), PowerTimer::default(), Instant::now());
        assert_eq!(
            handle_command(
                &cmd(1, "launch_app", json!({"app_id": "wot"})),
                &cfg(),
                &exec,
                &mut timer,
                now
            ),
            (true, "Spuštěno: World of Tanks".into())
        );
        let (ok, _) = handle_command(
            &cmd(
                2,
                "launch_app",
                json!({"app_id": "cmd", "target": "C:\\evil.exe"}),
            ),
            &cfg(),
            &exec,
            &mut timer,
            now,
        );
        assert!(!ok);
        assert_eq!(*exec.launched.borrow(), vec!["wot".to_string()]);
        let failing = FakeExec {
            fail_launch: true,
            ..Default::default()
        };
        let (ok, msg) = handle_command(
            &cmd(3, "launch_app", json!({"app_id": "wot"})),
            &cfg(),
            &failing,
            &mut timer,
            now,
        );
        assert!(!ok && msg.contains("soubor nenalezen"));
    }

    #[test]
    fn unknown_kinds_are_rejected() {
        let (exec, mut timer) = (FakeExec::default(), PowerTimer::default());
        let (ok, _) = handle_command(
            &cmd(1, "shell", json!({"cmd": "format c:"})),
            &cfg(),
            &exec,
            &mut timer,
            Instant::now(),
        );
        assert!(!ok);
        assert!(exec.launched.borrow().is_empty() && exec.power.borrow().is_empty());
    }

    #[test]
    fn power_uses_timer_and_can_be_cancelled() {
        let (exec, mut timer, now) = (FakeExec::default(), PowerTimer::default(), Instant::now());
        let (ok, msg) = handle_command(
            &cmd(
                1,
                "power",
                json!({"action": "shutdown", "delay_seconds": 3600}),
            ),
            &cfg(),
            &exec,
            &mut timer,
            now,
        );
        assert!(ok);
        assert_eq!(msg, "Vypnutí za 60 min");
        assert!(exec.power.borrow().is_empty(), "nic se neprovede hned");
        assert_eq!(timer.take_due(now + Duration::from_secs(3599)), None);
        assert_eq!(
            handle_command(
                &cmd(2, "power_cancel", json!({})),
                &cfg(),
                &exec,
                &mut timer,
                now
            )
            .1,
            "Časovač zrušen."
        );
        assert_eq!(timer.take_due(now + Duration::from_secs(4000)), None);
        // neplatné
        for bad in [
            json!({"action": "format"}),
            json!({"action": "sleep", "delay_seconds": 99999}),
            json!({"action": "sleep", "delay_seconds": "x"}),
        ] {
            assert!(!handle_command(&cmd(3, "power", bad), &cfg(), &exec, &mut timer, now).0);
        }
        assert!(timer.pending().is_none());
    }

    #[test]
    fn immediate_power_is_reported_before_it_runs() {
        let (hub, exec, state) = (
            FakeHub::default(),
            FakeExec::default(),
            Mutex::new(AgentState::default()),
        );
        hub.queue.borrow_mut().push(cmd(
            7,
            "power",
            json!({"action": "shutdown", "delay_seconds": 0}),
        ));
        let mut agent = Agent::new("0.1.0");
        let now = Instant::now();
        assert_eq!(
            agent.tick(&hub, &exec, &cfg(), &state, &|| now, 0, &SESSION, 0),
            TickOutcome::Ok
        );
        assert_eq!(
            *hub.reports.borrow(),
            vec![(7, true, "Vypnutí hned".to_string())]
        );
        run_due_power(&agent.timer, &exec, &state, now);
        assert!(
            exec.power.borrow().is_empty(),
            "ještě běží lhůta na nahlášení"
        );
        assert_eq!(
            state.lock().unwrap().pending_power,
            Some((PowerAction::Shutdown, 3))
        );
        run_due_power(&agent.timer, &exec, &state, now + IMMEDIATE_GRACE);
        assert_eq!(*exec.power.borrow(), vec![PowerAction::Shutdown]);
        assert_eq!(state.lock().unwrap().recent[0].label, "Vypnutí");
        assert_eq!(state.lock().unwrap().pending_power, None);
        run_due_power(&agent.timer, &exec, &state, now + IMMEDIATE_GRACE * 2);
        assert_eq!(exec.power.borrow().len(), 1, "jen jednou");
    }

    #[test]
    fn heartbeat_every_30s_and_after_failure() {
        let (hub, exec, state) = (
            FakeHub::default(),
            FakeExec::default(),
            Mutex::new(AgentState::default()),
        );
        let mut agent = Agent::new("0.1.0");
        let now = Instant::now();
        agent.tick(&hub, &exec, &cfg(), &state, &|| now, 0, &SESSION, 0);
        agent.tick(
            &hub,
            &exec,
            &cfg(),
            &state,
            &|| now + Duration::from_secs(10),
            0,
            &SESSION,
            0,
        );
        assert_eq!(*hub.heartbeats.borrow(), 1);
        agent.tick(
            &hub,
            &exec,
            &cfg(),
            &state,
            &|| now + HEARTBEAT_EVERY,
            0,
            &SESSION,
            0,
        );
        assert_eq!(*hub.heartbeats.borrow(), 2);
        assert!(state.lock().unwrap().connected);
        let offline = FakeHub {
            offline: true,
            ..Default::default()
        };
        assert_eq!(
            agent.tick(
                &offline,
                &exec,
                &cfg(),
                &state,
                &|| now + Duration::from_secs(31),
                0,
                &SESSION,
                0
            ),
            TickOutcome::Retry
        );
        {
            let st = state.lock().unwrap();
            assert!(!st.connected && st.last_error.as_deref().unwrap().contains("není dostupný"));
        }
        agent.tick(
            &hub,
            &exec,
            &cfg(),
            &state,
            &|| now + Duration::from_secs(32),
            0,
            &SESSION,
            0,
        );
        assert_eq!(
            *hub.heartbeats.borrow(),
            3,
            "po výpadku se stav ohlásí hned"
        );
    }

    fn launch(id: i64) -> Command {
        cmd(id, "launch_app", json!({"app_id": "wot"}))
    }

    #[test]
    fn failed_report_keeps_rest_of_batch_and_never_reruns() {
        // review #139: Hub už označil [A, B] delivered – výpadek při hlášení A nesmí ztratit B ani zopakovat A
        let (hub, exec, state) = (
            FakeHub::default(),
            FakeExec::default(),
            Mutex::new(AgentState::default()),
        );
        hub.queue.borrow_mut().extend([
            launch(1),
            cmd(2, "power", json!({"action": "lock", "delay_seconds": 600})),
        ]);
        *hub.failing_reports.borrow_mut() = 1;
        let mut agent = Agent::new("0.1.0");
        let now = Instant::now();
        assert_eq!(
            agent.tick(&hub, &exec, &cfg(), &state, &|| now, 0, &SESSION, 0),
            TickOutcome::Retry
        );
        assert_eq!(exec.launched.borrow().len(), 1, "A provedeno");
        assert!(lock(&agent.timer).pending().is_none(), "B ještě ne");
        assert_eq!(
            agent.backlog(),
            (1, 1),
            "B čeká, výsledek A čeká na odeslání"
        );
        let later = now + Duration::from_secs(5);
        assert_eq!(
            agent.tick(&hub, &exec, &cfg(), &state, &|| later, 0, &SESSION, 0),
            TickOutcome::Ok
        );
        assert_eq!(exec.launched.borrow().len(), 1, "A se neopakuje");
        assert!(lock(&agent.timer).pending().is_some(), "B provedeno");
        let reported: Vec<i64> = hub.reports.borrow().iter().map(|r| r.0).collect();
        assert_eq!(reported, vec![1, 2]);
        assert_eq!(
            *hub.polls.borrow(),
            1,
            "dokud dávka nedoběhla, nový poll se nedělá"
        );
        assert_eq!(agent.backlog(), (0, 0));
    }

    #[test]
    fn report_for_already_closed_command_is_dropped() {
        let hub = FakeHub {
            report_status: Some(409),
            ..Default::default()
        };
        let (exec, state) = (FakeExec::default(), Mutex::new(AgentState::default()));
        hub.queue.borrow_mut().extend([launch(1), launch(2)]);
        let mut agent = Agent::new("0.1.0");
        assert_eq!(
            agent.tick(&hub, &exec, &cfg(), &state, &Instant::now, 0, &SESSION, 0),
            TickOutcome::Ok
        );
        assert_eq!(
            agent.backlog(),
            (0, 0),
            "409 = Hub příkaz uzavřel, výsledek se zahodí"
        );
        assert_eq!(exec.launched.borrow().len(), 2);
    }

    #[test]
    fn stale_batch_is_not_executed() {
        let (exec, state) = (FakeExec::default(), Mutex::new(AgentState::default()));
        let mut agent = Agent::new("0.1.0");
        let now = Instant::now();
        // odložený příkaz po dlouhém výpadku se neprovede
        let hub = FakeHub::default();
        hub.queue.borrow_mut().extend([launch(1), launch(2)]);
        *hub.failing_reports.borrow_mut() = 1;
        agent.tick(&hub, &exec, &cfg(), &state, &|| now, 0, &SESSION, 0);
        let late = now + LOCAL_COMMAND_TTL + Duration::from_secs(1);
        assert_eq!(
            agent.tick(&hub, &exec, &cfg(), &state, &|| late, 0, &SESSION, 0),
            TickOutcome::Ok
        );
        assert_eq!(exec.launched.borrow().len(), 1, "druhé spuštění propadlo");
        assert!(
            !hub.reports.borrow().last().unwrap().1,
            "nahlášeno jako chyba"
        );
    }

    #[test]
    fn unpair_or_pause_during_poll_cancels_the_batch() {
        // review #139: okno během long-pollu změní relaci (odpárování / pauza) → odpověď staré relace nic neprovede
        let session = std::rc::Rc::new(Mutex::new(5u64));
        let (exec, state) = (FakeExec::default(), Mutex::new(AgentState::default()));
        let s2 = session.clone();
        let hub = FakeHub {
            during_poll: Some(Box::new(move || *s2.lock().unwrap() += 1)),
            ..Default::default()
        };
        hub.queue.borrow_mut().extend([
            launch(1),
            cmd(
                2,
                "power",
                json!({"action": "shutdown", "delay_seconds": 60}),
            ),
        ]);
        let mut agent = Agent::new("0.1.0");
        assert_eq!(
            agent.tick(&hub, &exec, &cfg(), &state, &Instant::now, 0, &session, 5),
            TickOutcome::Stale
        );
        assert!(exec.launched.borrow().is_empty(), "nic nespuštěno");
        assert!(
            lock(&agent.timer).pending().is_none(),
            "časovač se znovu nenastavil"
        );
        assert!(hub.reports.borrow().is_empty());
        assert_eq!(agent.backlog(), (0, 0));
    }

    #[test]
    fn revoked_token_stops_agent() {
        let (hub, exec, state) = (
            FakeHub {
                unauthorized: true,
                ..Default::default()
            },
            FakeExec::default(),
            Mutex::new(AgentState::default()),
        );
        let mut agent = Agent::new("0.1.0");
        assert_eq!(
            agent.tick(&hub, &exec, &cfg(), &state, &Instant::now, 0, &SESSION, 0),
            TickOutcome::Unauthorized
        );
        assert!(state.lock().unwrap().unauthorized);
    }

    #[test]
    fn backoff_grows_and_caps() {
        assert_eq!(backoff(0), Duration::from_secs(5));
        assert_eq!(backoff(2), Duration::from_secs(20));
        assert_eq!(backoff(9), Duration::from_secs(60));
    }
}
