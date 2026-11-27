//! Jarvis pro PC (MRK-156) – ikona v oznamovací oblasti, okno nastavení a agent na pozadí.
//!
//! Vlákna: `agent` (heartbeat + long-poll příkazů z Hubu, backoff po chybě) a `power` (každou sekundu časovač
//! napájení + popisek ikony). Token zařízení je jen ve Správci pověření Windows, nastavení v %APPDATA%.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod system;

use std::path::PathBuf;
use std::sync::{Arc, Mutex, MutexGuard};
use std::thread;
use std::time::{Duration, Instant};

use agent_core::agent::{
    backoff, run_due_power, Agent, AgentState, PowerTimer, TickOutcome, POLL_WAIT_SECONDS,
};
use agent_core::client::{self, HttpHub};
use agent_core::config::{clean_apps, slugify, AgentConfig, AppEntry};
use agent_core::protocol::PairRequest;
use serde::Serialize;
use tauri::menu::{Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Manager, State, WindowEvent};
use tauri_plugin_autostart::{MacosLauncher, ManagerExt};

const VERSION: &str = env!("CARGO_PKG_VERSION");
const KEYRING_SERVICE: &str = "StandaHub Jarvis";
const KEYRING_USER: &str = "device-token";
const TRAY_ID: &str = "main";

struct Shared {
    config: Mutex<AgentConfig>,
    state: Mutex<AgentState>,
    timer: Arc<Mutex<PowerTimer>>,
    config_path: PathBuf,
}

fn lock<T>(m: &Mutex<T>) -> MutexGuard<'_, T> {
    m.lock().unwrap_or_else(|e| e.into_inner())
}

// ---------- token (Správce pověření Windows) ----------

fn token_entry() -> Option<keyring::Entry> {
    keyring::Entry::new(KEYRING_SERVICE, KEYRING_USER).ok()
}

fn load_token() -> Option<String> {
    token_entry()?.get_password().ok().filter(|t| !t.is_empty())
}

fn save_token(token: &str) -> Result<(), String> {
    token_entry()
        .ok_or("Správce pověření není dostupný.")?
        .set_password(token)
        .map_err(|e| format!("Token se nepodařilo uložit: {e}"))
}

fn delete_token() {
    if let Some(e) = token_entry() {
        let _ = e.delete_credential();
    }
}

impl Shared {
    fn save_config(&self, cfg: &AgentConfig) -> Result<(), String> {
        cfg.save(&self.config_path)
            .map_err(|e| format!("Nastavení se nepodařilo uložit: {e}"))
    }

    fn update_config(&self, f: impl FnOnce(&mut AgentConfig)) -> Result<AgentConfig, String> {
        let mut cfg = lock(&self.config);
        f(&mut cfg);
        self.save_config(&cfg)?;
        Ok(cfg.clone())
    }
}

// ---------- vlákna ----------

fn agent_loop(shared: Arc<Shared>) {
    let exec = system::SystemExecutor::new();
    let mut agent = Agent::new(VERSION);
    agent.timer = shared.timer.clone();
    let mut failures = 0u32;
    loop {
        let cfg = lock(&shared.config).clone();
        let token = load_token();
        let blocked = lock(&shared.state).unauthorized;
        let (Some(token), false, false) = (token, cfg.paused || cfg.hub_url.is_empty(), blocked)
        else {
            lock(&shared.state).connected = false;
            thread::sleep(Duration::from_secs(1));
            continue;
        };
        let hub = HttpHub::new(&cfg.hub_url, &token);
        match agent.tick(
            &hub,
            &exec,
            &cfg,
            &shared.state,
            &Instant::now,
            POLL_WAIT_SECONDS,
        ) {
            TickOutcome::Ok => failures = 0,
            // odvoláno v Hubu: agent stojí, dokud se znovu nespáruje (okno to ukáže)
            TickOutcome::Unauthorized => failures = 0,
            TickOutcome::Retry => {
                thread::sleep(backoff(failures));
                failures = failures.saturating_add(1);
            }
        }
    }
}

fn tray_tooltip(shared: &Shared, paired: bool) -> String {
    let cfg = lock(&shared.config);
    let st = lock(&shared.state);
    let status = if !paired || st.unauthorized {
        "nespárováno"
    } else if cfg.paused {
        "pozastaveno"
    } else if st.connected {
        "připojeno"
    } else {
        "nepřipojeno"
    };
    match st.pending_power {
        Some((action, secs)) => format!(
            "Jarvis pro PC – {status} · {} za {} min",
            action.label(),
            secs.div_ceil(60)
        ),
        None => format!("Jarvis pro PC – {status}"),
    }
}

fn power_loop(shared: Arc<Shared>, app: AppHandle) {
    let exec = system::SystemExecutor::new();
    let mut last_tip = String::new();
    loop {
        run_due_power(&shared.timer, &exec, &shared.state, Instant::now());
        let tip = tray_tooltip(&shared, load_token().is_some());
        if tip != last_tip {
            if let Some(tray) = app.tray_by_id(TRAY_ID) {
                let _ = tray.set_tooltip(Some(&tip));
            }
            last_tip = tip;
        }
        thread::sleep(Duration::from_secs(1));
    }
}

// ---------- příkazy okna ----------

#[derive(Serialize)]
struct View {
    hub_url: String,
    device_name: String,
    device_id: Option<i64>,
    paused: bool,
    paired: bool,
    autostart: bool,
    apps: Vec<AppEntry>,
    state: AgentState,
    version: &'static str,
}

#[tauri::command]
fn get_state(app: AppHandle, shared: State<'_, Arc<Shared>>) -> View {
    let cfg = lock(&shared.config).clone();
    View {
        hub_url: cfg.hub_url,
        device_name: cfg.device_name,
        device_id: cfg.device_id,
        paused: cfg.paused,
        paired: load_token().is_some(),
        autostart: app.autolaunch().is_enabled().unwrap_or(false),
        apps: cfg.apps,
        state: lock(&shared.state).clone(),
        version: VERSION,
    }
}

#[tauri::command]
async fn pair(
    shared: State<'_, Arc<Shared>>,
    hub_url: String,
    code: String,
    name: String,
) -> Result<String, String> {
    let url = client::normalize_hub_url(&hub_url)?;
    let name = name.trim().chars().take(80).collect::<String>();
    let body = PairRequest {
        code,
        name: name.clone(),
        platform: "windows".into(),
        agent_version: VERSION.into(),
    };
    let request_url = url.clone();
    let resp = tauri::async_runtime::spawn_blocking(move || client::pair(&request_url, &body))
        .await
        .map_err(|e| e.to_string())?
        .map_err(|e| e.to_string())?;
    save_token(&resp.token)?;
    shared.update_config(|c| {
        c.hub_url = url;
        c.device_name = resp.name.clone();
        c.device_id = Some(resp.device_id);
        c.paused = false;
    })?;
    let mut st = lock(&shared.state);
    st.unauthorized = false;
    st.last_error = None;
    Ok(format!("Spárováno jako „{}“.", resp.name))
}

#[tauri::command]
fn unpair(shared: State<'_, Arc<Shared>>) -> Result<(), String> {
    delete_token();
    lock(&shared.timer).cancel();
    shared.update_config(|c| c.device_id = None)?;
    let mut st = lock(&shared.state);
    st.connected = false;
    st.unauthorized = false;
    Ok(())
}

#[tauri::command]
fn set_paused(shared: State<'_, Arc<Shared>>, paused: bool) -> Result<(), String> {
    shared.update_config(|c| c.paused = paused).map(|_| ())
}

#[tauri::command]
fn set_autostart(app: AppHandle, enabled: bool) -> Result<(), String> {
    let launcher = app.autolaunch();
    let res = if enabled {
        launcher.enable()
    } else {
        launcher.disable()
    };
    res.map_err(|e| e.to_string())
}

#[tauri::command]
fn cancel_power(shared: State<'_, Arc<Shared>>) -> bool {
    let cancelled = lock(&shared.timer).cancel();
    lock(&shared.state).pending_power = None;
    cancelled
}

#[tauri::command]
fn detect_apps(shared: State<'_, Arc<Shared>>) -> Result<usize, String> {
    let found = system::detect_apps();
    let n = found.len();
    shared.update_config(|c| c.merge_detected(found))?;
    Ok(n)
}

#[tauri::command]
fn add_app(
    shared: State<'_, Arc<Shared>>,
    name: String,
    target: String,
    args: String,
    process: String,
) -> Result<(), String> {
    let name = name.trim().to_string();
    let target = target.trim().trim_matches('"').to_string();
    if name.is_empty() || target.is_empty() {
        return Err("Vyplň název i cestu (nebo odkaz).".into());
    }
    let mut cfg = lock(&shared.config);
    let base = slugify(&name);
    let mut id = base.clone();
    let mut n = 2;
    while cfg.app(&id).is_some() {
        let suffix = format!("-{n}");
        id = format!("{}{suffix}", &base[..base.len().min(40 - suffix.len())]);
        n += 1;
    }
    let process = process.trim();
    let process = if process.is_empty() {
        std::path::Path::new(&target)
            .file_name()
            .map(|f| f.to_string_lossy().into_owned())
            .filter(|f| f.to_ascii_lowercase().ends_with(".exe"))
    } else {
        Some(process.to_string())
    };
    let mut apps = cfg.apps.clone();
    apps.push(AppEntry {
        id,
        name,
        target,
        args: args.split_whitespace().map(str::to_string).collect(),
        process,
        detected: false,
    });
    let before = apps.len();
    cfg.apps = clean_apps(apps);
    if cfg.apps.len() < before {
        return Err("Aplikaci se nepodařilo přidat (neplatná položka nebo plný seznam).".into());
    }
    shared.save_config(&cfg)
}

#[tauri::command]
fn remove_app(shared: State<'_, Arc<Shared>>, id: String) -> Result<(), String> {
    shared
        .update_config(|c| c.apps.retain(|a| a.id != id))
        .map(|_| ())
}

// ---------- okno a ikona ----------

fn show_window(app: &AppHandle) {
    if let Some(w) = app.get_webview_window("main") {
        let _ = w.unminimize();
        let _ = w.show();
        let _ = w.set_focus();
    }
}

fn build_tray(app: &AppHandle) -> tauri::Result<()> {
    let open = MenuItem::with_id(app, "open", "Otevřít Jarvise", true, None::<&str>)?;
    let pause = MenuItem::with_id(app, "pause", "Pozastavit / obnovit", true, None::<&str>)?;
    let cancel = MenuItem::with_id(app, "cancel", "Zrušit časovač napájení", true, None::<&str>)?;
    let quit = MenuItem::with_id(app, "quit", "Ukončit", true, None::<&str>)?;
    let sep = PredefinedMenuItem::separator(app)?;
    let menu = Menu::with_items(app, &[&open, &pause, &cancel, &sep, &quit])?;
    let mut builder = TrayIconBuilder::with_id(TRAY_ID)
        .tooltip("Jarvis pro PC")
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_menu_event(|app, event| {
            let shared = app.state::<Arc<Shared>>();
            match event.id().as_ref() {
                "open" => show_window(app),
                "pause" => {
                    let _ = shared.update_config(|c| c.paused = !c.paused);
                }
                "cancel" => {
                    lock(&shared.timer).cancel();
                    lock(&shared.state).pending_power = None;
                }
                "quit" => app.exit(0),
                _ => {}
            }
        })
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                show_window(tray.app_handle());
            }
        });
    if let Some(icon) = app.default_window_icon() {
        builder = builder.icon(icon.clone());
    }
    builder.build(app)?;
    Ok(())
}

fn config_path() -> PathBuf {
    dirs::config_dir()
        .unwrap_or_else(std::env::temp_dir)
        .join("StandaHub")
        .join("jarvis-agent.json")
}

fn main() {
    let path = config_path();
    let mut cfg = AgentConfig::load(&path);
    if cfg.apps.iter().all(|a| !a.detected) {
        cfg.merge_detected(system::detect_apps()); // první spuštění: najít WoT, Steam, Discord…
        let _ = cfg.save(&path);
    }
    let shared = Arc::new(Shared {
        config: Mutex::new(cfg),
        state: Mutex::new(AgentState::default()),
        timer: Arc::new(Mutex::new(PowerTimer::default())),
        config_path: path,
    });

    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            show_window(app)
        }))
        .plugin(tauri_plugin_autostart::init(
            MacosLauncher::LaunchAgent,
            Some(vec!["--hidden"]),
        ))
        .manage(shared.clone())
        .invoke_handler(tauri::generate_handler![
            get_state,
            pair,
            unpair,
            set_paused,
            set_autostart,
            cancel_power,
            detect_apps,
            add_app,
            remove_app
        ])
        .setup(move |app| {
            build_tray(app.handle())?;
            let hidden = std::env::args().any(|a| a == "--hidden");
            if !hidden || load_token().is_none() {
                show_window(app.handle());
            }
            let s1 = shared.clone();
            thread::Builder::new()
                .name("agent".into())
                .spawn(move || agent_loop(s1))?;
            let (s2, handle) = (shared.clone(), app.handle().clone());
            thread::Builder::new()
                .name("power".into())
                .spawn(move || power_loop(s2, handle))?;
            Ok(())
        })
        .on_window_event(|window, event| {
            // zavření okna jen skryje – agent běží dál v oznamovací oblasti
            if let WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
            }
        })
        .run(tauri::generate_context!())
        .expect("Jarvis pro PC se nepodařilo spustit");
}
