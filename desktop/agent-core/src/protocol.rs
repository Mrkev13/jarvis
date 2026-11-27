//! Tvary požadavků a odpovědí `/device/agent/*` (backend: `backend/modules/computer/router.py`).

use serde::{Deserialize, Serialize};
use serde_json::Value;

#[derive(Debug, Clone, Serialize)]
pub struct PairRequest {
    pub code: String,
    pub name: String,
    pub platform: String,
    pub agent_version: String,
}

#[derive(Debug, Clone, Deserialize)]
pub struct PairResponse {
    pub device_id: i64,
    pub name: String,
    pub token: String,
}

#[derive(Debug, Clone, Default, Serialize, PartialEq)]
pub struct Disk {
    pub name: String,
    pub free_gb: f64,
    pub total_gb: f64,
}

/// Stav PC pro heartbeat – backend si z něj bere jen tahle pole (sanitize_status).
#[derive(Debug, Clone, Default, Serialize, PartialEq)]
pub struct Status {
    pub cpu_percent: Option<f32>,
    pub ram_percent: Option<f32>,
    pub disks: Vec<Disk>,
    /// id aplikací ze seznamu agenta, které právě běží
    pub running: Vec<String>,
    pub uptime_minutes: Option<u64>,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct AppRef {
    pub id: String,
    pub name: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct Heartbeat {
    pub status: Status,
    pub apps: Vec<AppRef>,
    pub agent_version: String,
}

#[derive(Debug, Clone, Deserialize, PartialEq)]
pub struct Command {
    pub id: i64,
    pub kind: String,
    #[serde(default)]
    pub payload: Value,
}

#[derive(Debug, Clone, Deserialize)]
pub struct CommandsResponse {
    pub commands: Vec<Command>,
}

#[derive(Debug, Clone, Serialize)]
pub struct CommandResult {
    pub ok: bool,
    pub message: Option<String>,
}
