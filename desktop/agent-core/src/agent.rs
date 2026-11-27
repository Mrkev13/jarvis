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

/// Jedna obrátka smyčky agenta. Čas dalšího heartbeatu drží sám; časovač napájení a stav jsou sdílené (zámky se
/// drží jen krátce – nikdy přes long-poll), ať okno může časovač zrušit hned. Síť a systém jsou vstřiknuté.
pub struct Agent {
    pub timer: Arc<Mutex<PowerTimer>>,
    next_heartbeat: Option<Instant>,
    pub version: String,
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

#[derive(Debug, PartialEq)]
pub enum TickOutcome {
    /// vše v pořádku
    Ok,
    /// Hub nedostupný / chyba – volající počká (backoff)
    Retry,
    /// token neplatí – agent se zastaví, dokud se znovu nespáruje
    Unauthorized,
}

impl Agent {
    pub fn new(version: &str) -> Self {
        Self {
            timer: Arc::new(Mutex::new(PowerTimer::default())),
            next_heartbeat: None,
            version: version.into(),
        }
    }

    /// `clock` = aktuální čas (po long-pollu se čte znovu, ať časovač napájení neběží o dobu čekání kratší).
    pub fn tick(
        &mut self,
        hub: &dyn HubApi,
        exec: &dyn Executor,
        cfg: &AgentConfig,
        state: &Mutex<AgentState>,
        clock: &dyn Fn() -> Instant,
        poll_wait: u32,
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
        let commands = match hub.poll(poll_wait) {
            Ok(c) => c,
            Err(e) => return self.fail(state, e),
        };
        {
            let mut st = lock(state);
            st.connected = true;
            st.last_error = None;
            st.unauthorized = false;
        }
        for cmd in commands {
            let (ok, message) = handle_command(&cmd, cfg, exec, &mut lock(&self.timer), clock());
            // výsledek se hlásí dřív, než proběhne okamžité vypnutí (IMMEDIATE_GRACE)
            let reported = hub.report(
                cmd.id,
                &CommandResult {
                    ok,
                    message: Some(message.clone()),
                },
            );
            push_recent(
                &mut lock(state),
                RecentCommand {
                    label: command_label(&cmd, cfg),
                    ok,
                    message,
                    at_unix: unix_now(),
                },
            );
            if let Err(e) = reported {
                return self.fail(state, e);
            }
        }
        TickOutcome::Ok
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

    #[derive(Default)]
    struct FakeHub {
        heartbeats: RefCell<usize>,
        queue: RefCell<Vec<Command>>,
        reports: RefCell<Vec<(i64, bool, String)>>,
        events: RefCell<Vec<String>>,
        unauthorized: bool,
        offline: bool,
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
            Ok(std::mem::take(&mut *self.queue.borrow_mut()))
        }
        fn report(&self, id: i64, r: &CommandResult) -> Result<(), ApiError> {
            self.events.borrow_mut().push(format!("report {id}"));
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
            agent.tick(&hub, &exec, &cfg(), &state, &|| now, 0),
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
        agent.tick(&hub, &exec, &cfg(), &state, &|| now, 0);
        agent.tick(
            &hub,
            &exec,
            &cfg(),
            &state,
            &|| now + Duration::from_secs(10),
            0,
        );
        assert_eq!(*hub.heartbeats.borrow(), 1);
        agent.tick(&hub, &exec, &cfg(), &state, &|| now + HEARTBEAT_EVERY, 0);
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
        );
        assert_eq!(
            *hub.heartbeats.borrow(),
            3,
            "po výpadku se stav ohlásí hned"
        );
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
            agent.tick(&hub, &exec, &cfg(), &state, &Instant::now, 0),
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
