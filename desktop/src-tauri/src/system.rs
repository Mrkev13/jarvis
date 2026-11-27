//! Systémové akce na Windows: spuštění aplikace z místního seznamu, napájení, stav PC a hledání aplikací.
//! Na jiných OS se aplikace jen přeloží (vývoj) – akce vrací chybu, stav se počítá přes sysinfo.

use std::sync::Mutex;

use agent_core::agent::{Executor, PowerAction};
use agent_core::config::AppEntry;
use agent_core::protocol::{Disk, Status};
use sysinfo::{Disks, ProcessesToUpdate, System};

pub struct SystemExecutor {
    sys: Mutex<System>,
}

impl SystemExecutor {
    pub fn new() -> Self {
        Self {
            sys: Mutex::new(System::new()),
        }
    }
}

const GB: f64 = 1024.0 * 1024.0 * 1024.0;

impl Executor for SystemExecutor {
    fn launch(&self, app: &AppEntry) -> Result<(), String> {
        platform::launch(app)
    }

    fn power(&self, action: PowerAction) -> Result<(), String> {
        platform::power(action)
    }

    fn status(&self, apps: &[AppEntry]) -> Status {
        let mut sys = self.sys.lock().unwrap_or_else(|e| e.into_inner());
        sys.refresh_cpu_usage(); // první měření je 0 – další heartbeat (za 30 s) už ukáže skutečnou hodnotu
        sys.refresh_memory();
        sys.refresh_processes(ProcessesToUpdate::All, true);
        let ram = if sys.total_memory() > 0 {
            Some((sys.used_memory() as f64 / sys.total_memory() as f64 * 100.0) as f32)
        } else {
            None
        };
        let names: Vec<String> = sys
            .processes()
            .values()
            .map(|p| p.name().to_string_lossy().to_lowercase())
            .collect();
        let running = apps
            .iter()
            .filter(|a| {
                a.process
                    .as_deref()
                    .is_some_and(|p| names.iter().any(|n| n == &p.to_lowercase()))
            })
            .map(|a| a.id.clone())
            .collect();
        let disks = Disks::new_with_refreshed_list()
            .list()
            .iter()
            .filter(|d| d.total_space() > 0)
            .take(12)
            .map(|d| Disk {
                name: d
                    .mount_point()
                    .to_string_lossy()
                    .trim_end_matches(['\\', '/'])
                    .chars()
                    .take(10)
                    .collect::<String>(),
                free_gb: (d.available_space() as f64 / GB * 10.0).round() / 10.0,
                total_gb: (d.total_space() as f64 / GB * 10.0).round() / 10.0,
            })
            .filter(|d| !d.name.is_empty())
            .collect();
        Status {
            cpu_percent: Some(sys.global_cpu_usage()),
            ram_percent: ram,
            disks,
            running,
            uptime_minutes: Some(System::uptime() / 60),
        }
    }
}

pub fn detect_apps() -> Vec<AppEntry> {
    platform::detect_apps()
}

#[cfg(windows)]
mod platform {
    use std::os::windows::process::CommandExt;
    use std::path::{Path, PathBuf};
    use std::process::Command;

    use agent_core::agent::PowerAction;
    use agent_core::config::AppEntry;

    const DETACHED_PROCESS: u32 = 0x0000_0008;
    const CREATE_NO_WINDOW: u32 = 0x0800_0000;

    /// Spustí aplikaci z místního seznamu: .exe přímo (s pevnými argumenty z nastavení), cokoli jiného
    /// (zástupce .lnk, steam://…) přes Průzkumníka. Hub nikdy neposílá cestu ani argumenty.
    pub fn launch(app: &AppEntry) -> Result<(), String> {
        let target = app.target.trim();
        let spawned = if target.to_ascii_lowercase().ends_with(".exe") {
            let path = Path::new(target);
            if !path.is_file() {
                return Err(format!("soubor {target} neexistuje"));
            }
            let mut cmd = Command::new(path);
            cmd.args(&app.args).creation_flags(DETACHED_PROCESS);
            if let Some(dir) = path.parent() {
                cmd.current_dir(dir);
            }
            cmd.spawn()
        } else {
            Command::new("explorer.exe").arg(target).spawn()
        };
        spawned.map(|_| ()).map_err(|e| e.to_string())
    }

    fn run_hidden(program: &str, args: &[&str]) -> Result<(), String> {
        let status = Command::new(program)
            .args(args)
            .creation_flags(CREATE_NO_WINDOW)
            .status()
            .map_err(|e| e.to_string())?;
        if status.success() {
            Ok(())
        } else {
            Err(format!("{program} skončil s kódem {:?}", status.code()))
        }
    }

    pub fn power(action: PowerAction) -> Result<(), String> {
        match action {
            PowerAction::Shutdown => run_hidden("shutdown.exe", &["/s", "/t", "0"]),
            // pozn.: se zapnutou hibernací Windows místo uspání hibernuje (docs/computer.md)
            PowerAction::Sleep => {
                run_hidden("rundll32.exe", &["powrprof.dll,SetSuspendState", "0,1,0"])
            }
            PowerAction::Lock => run_hidden("rundll32.exe", &["user32.dll,LockWorkStation"]),
        }
    }

    fn env_path(var: &str) -> Option<PathBuf> {
        std::env::var_os(var).map(PathBuf::from)
    }

    fn entry(id: &str, name: &str, target: &Path, args: &[&str], process: &str) -> AppEntry {
        AppEntry {
            id: id.into(),
            name: name.into(),
            target: target.to_string_lossy().into_owned(),
            args: args.iter().map(|a| a.to_string()).collect(),
            process: Some(process.into()),
            detected: true,
        }
    }

    fn steam_exe() -> Option<PathBuf> {
        let out = Command::new("reg.exe")
            .args(["query", r"HKCU\Software\Valve\Steam", "/v", "SteamExe"])
            .creation_flags(CREATE_NO_WINDOW)
            .output()
            .ok()?;
        let text = String::from_utf8_lossy(&out.stdout);
        let line = text.lines().find(|l| l.contains("SteamExe"))?;
        let path = line.split("REG_SZ").nth(1)?.trim();
        let path = PathBuf::from(path.replace('/', "\\"));
        path.is_file().then_some(path)
    }

    pub fn detect_apps() -> Vec<AppEntry> {
        let mut apps = Vec::new();
        // World of Tanks – běžná umístění klienta; jinak Wargaming Game Center
        let mut wot_dirs: Vec<PathBuf> = Vec::new();
        for drive in ["C:", "D:", "E:"] {
            for dir in [
                "Games\\World_of_Tanks_EU",
                "Games\\World_of_Tanks",
                "Wargaming.net\\Games\\World_of_Tanks_EU",
            ] {
                wot_dirs.push(PathBuf::from(format!("{drive}\\{dir}")));
            }
        }
        if let Some(exe) = wot_dirs
            .iter()
            .map(|d| d.join("WorldOfTanks.exe"))
            .find(|p| p.is_file())
        {
            apps.push(entry(
                "wot",
                "World of Tanks",
                &exe,
                &[],
                "WorldOfTanks.exe",
            ));
        }
        if let Some(wgc) = env_path("ProgramData")
            .map(|p| p.join("Wargaming.net\\GameCenter\\wgc.exe"))
            .filter(|p| p.is_file())
        {
            apps.push(entry("wgc", "Wargaming Game Center", &wgc, &[], "wgc.exe"));
        }
        if let Some(steam) = steam_exe() {
            apps.push(entry("steam", "Steam", &steam, &[], "steam.exe"));
        }
        if let Some(update) = env_path("LOCALAPPDATA")
            .map(|p| p.join("Discord\\Update.exe"))
            .filter(|p| p.is_file())
        {
            apps.push(entry(
                "discord",
                "Discord",
                &update,
                &["--processStart", "Discord.exe"],
                "Discord.exe",
            ));
        }
        apps
    }
}

#[cfg(not(windows))]
mod platform {
    use agent_core::agent::PowerAction;
    use agent_core::config::AppEntry;

    pub fn launch(_app: &AppEntry) -> Result<(), String> {
        Err("spouštění aplikací umí jen Windows".into())
    }

    pub fn power(_action: PowerAction) -> Result<(), String> {
        Err("napájení umí jen Windows".into())
    }

    pub fn detect_apps() -> Vec<AppEntry> {
        Vec::new()
    }
}
