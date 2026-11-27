//! Konfigurace agenta (JSON v %APPDATA%). Token zařízení sem NIKDY nepatří – je ve Správci pověření Windows.

use serde::{Deserialize, Serialize};
use std::path::Path;

use crate::protocol::AppRef;

pub const MAX_APPS: usize = 50;

/// Aplikace, kterou agent smí spustit. Hub posílá jen `id`; cíl a argumenty jsou jen tady na PC.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct AppEntry {
    pub id: String,
    pub name: String,
    /// cesta k .exe / zástupci nebo URI (steam://…)
    pub target: String,
    #[serde(default)]
    pub args: Vec<String>,
    /// název procesu pro „běží“ (např. WorldOfTanks.exe)
    #[serde(default)]
    pub process: Option<String>,
    /// nalezeno automaticky (při novém hledání se obnoví), jinak přidal uživatel
    #[serde(default)]
    pub detected: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Default)]
pub struct AgentConfig {
    #[serde(default)]
    pub hub_url: String,
    #[serde(default)]
    pub device_name: String,
    #[serde(default)]
    pub device_id: Option<i64>,
    #[serde(default)]
    pub apps: Vec<AppEntry>,
    #[serde(default)]
    pub paused: bool,
}

/// Stejné pravidlo jako backend (`APP_ID_RE`): `[a-z0-9][a-z0-9_-]{0,39}`.
pub fn valid_app_id(id: &str) -> bool {
    let b = id.as_bytes();
    !b.is_empty()
        && b.len() <= 40
        && (b[0].is_ascii_lowercase() || b[0].is_ascii_digit())
        && b.iter().all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || *c == b'_' || *c == b'-')
}

/// Id z názvu („Counter-Strike 2“ → „counter-strike-2“), bez diakritiky; prázdné → „app“.
pub fn slugify(name: &str) -> String {
    let mut out = String::new();
    for ch in name.chars() {
        let c = match ch {
            'á' | 'Á' | 'ä' | 'Ä' => 'a', 'č' | 'Č' => 'c', 'ď' | 'Ď' => 'd', 'é' | 'É' | 'ě' | 'Ě' => 'e',
            'í' | 'Í' => 'i', 'ň' | 'Ň' => 'n', 'ó' | 'Ó' | 'ö' | 'Ö' => 'o', 'ř' | 'Ř' => 'r',
            'š' | 'Š' => 's', 'ť' | 'Ť' => 't', 'ú' | 'Ú' | 'ů' | 'Ů' | 'ü' | 'Ü' => 'u', 'ý' | 'Ý' => 'y',
            'ž' | 'Ž' => 'z',
            c => c.to_ascii_lowercase(),
        };
        if c.is_ascii_alphanumeric() {
            out.push(c);
        } else if !out.ends_with('-') && !out.is_empty() {
            out.push('-');
        }
    }
    let out: String = out.trim_matches('-').chars().take(40).collect();
    let out = out.trim_end_matches('-').to_string();
    if out.is_empty() { "app".into() } else { out }
}

impl AgentConfig {
    pub fn load(path: &Path) -> AgentConfig {
        std::fs::read_to_string(path)
            .ok()
            .and_then(|s| serde_json::from_str::<AgentConfig>(&s).ok())
            .map(|mut c| {
                c.apps = clean_apps(c.apps);
                c
            })
            .unwrap_or_default()
    }

    /// Atomický zápis (dočasný soubor + přejmenování) – po pádu nezůstane rozbitý JSON.
    pub fn save(&self, path: &Path) -> std::io::Result<()> {
        if let Some(dir) = path.parent() {
            std::fs::create_dir_all(dir)?;
        }
        let tmp = path.with_extension("json.tmp");
        std::fs::write(&tmp, serde_json::to_vec_pretty(self).expect("config serializes"))?;
        std::fs::rename(tmp, path)
    }

    pub fn app(&self, id: &str) -> Option<&AppEntry> {
        self.apps.iter().find(|a| a.id == id)
    }

    pub fn app_refs(&self) -> Vec<AppRef> {
        self.apps.iter().map(|a| AppRef { id: a.id.clone(), name: a.name.clone() }).collect()
    }

    /// Sloučí nově nalezené aplikace: ručně přidané zůstávají, automaticky nalezené se nahradí aktuálními.
    pub fn merge_detected(&mut self, detected: Vec<AppEntry>) {
        let mut apps: Vec<AppEntry> = self.apps.iter().filter(|a| !a.detected).cloned().collect();
        for mut d in detected {
            d.detected = true;
            if !apps.iter().any(|a| a.id == d.id) {
                apps.push(d);
            }
        }
        self.apps = clean_apps(apps);
    }
}

/// Jen platné a unikátní položky s neprázdným cílem, nejvýš `MAX_APPS`.
pub fn clean_apps(apps: Vec<AppEntry>) -> Vec<AppEntry> {
    let mut out: Vec<AppEntry> = Vec::new();
    for mut a in apps {
        a.name = a.name.trim().chars().take(80).collect();
        a.target = a.target.trim().to_string();
        if valid_app_id(&a.id) && !a.name.is_empty() && !a.target.is_empty() && !out.iter().any(|x| x.id == a.id) {
            out.push(a);
        }
        if out.len() >= MAX_APPS {
            break;
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    fn app(id: &str, detected: bool) -> AppEntry {
        AppEntry { id: id.into(), name: id.to_uppercase(), target: format!("C:\\{id}.exe"), args: vec![], process: None, detected }
    }

    #[test]
    fn app_ids_match_backend_rule() {
        assert!(valid_app_id("wot"));
        assert!(valid_app_id("counter-strike_2"));
        assert!(!valid_app_id(""));
        assert!(!valid_app_id("-x"));
        assert!(!valid_app_id("Wot"));
        assert!(!valid_app_id(&"a".repeat(41)));
        assert_eq!(slugify("Counter-Strike 2"), "counter-strike-2");
        assert_eq!(slugify("Žluťoučký kůň"), "zlutoucky-kun");
        assert_eq!(slugify("!!!"), "app");
        assert!(valid_app_id(&slugify(&"Dlouhý název ".repeat(10))));
    }

    #[test]
    fn merge_keeps_manual_apps_and_refreshes_detected() {
        let mut cfg = AgentConfig { apps: vec![app("wot", true), app("moje", false), app("steam", true)], ..Default::default() };
        cfg.merge_detected(vec![app("wot", false), app("discord", false), app("moje", false)]);
        let ids: Vec<_> = cfg.apps.iter().map(|a| (a.id.as_str(), a.detected)).collect();
        assert_eq!(ids, vec![("moje", false), ("wot", true), ("discord", true)]);
    }

    #[test]
    fn clean_drops_invalid_and_duplicates() {
        let mut bad = app("x", false);
        bad.target = " ".into();
        let apps = clean_apps(vec![app("a", false), app("a", false), app("Bad Id", false), bad]);
        assert_eq!(apps.len(), 1);
    }

    #[test]
    fn save_and_load_roundtrip() {
        let dir = std::env::temp_dir().join(format!("jarvis-agent-test-{}", std::process::id()));
        let path = dir.join("config.json");
        let cfg = AgentConfig { hub_url: "https://hub".into(), device_name: "PC".into(), device_id: Some(3), apps: vec![app("wot", true)], paused: true };
        cfg.save(&path).unwrap();
        assert_eq!(AgentConfig::load(&path), cfg);
        std::fs::write(&path, "{broken").unwrap();
        assert_eq!(AgentConfig::load(&path), AgentConfig::default(), "rozbitý soubor = výchozí nastavení");
        let _ = std::fs::remove_dir_all(dir);
    }
}
