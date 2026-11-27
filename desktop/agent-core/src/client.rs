//! HTTP klient pro Hub. Trait `HubApi` odděluje síť od logiky agenta (testy používají falešný Hub).

use std::time::Duration;

use crate::protocol::{
    Command, CommandResult, CommandsResponse, Heartbeat, PairRequest, PairResponse,
};

#[derive(Debug, Clone, PartialEq)]
pub enum ApiError {
    /// Token neplatí (zařízení odvoláno) nebo neplatný párovací kód.
    Unauthorized(String),
    /// Hub odpověděl chybou (4xx/5xx) – `detail` z odpovědi.
    Http(u16, String),
    /// Síť / Hub nedostupný.
    Network(String),
}

impl std::fmt::Display for ApiError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ApiError::Unauthorized(m) => write!(f, "{m}"),
            ApiError::Http(code, m) => write!(f, "Hub vrátil {code}: {m}"),
            ApiError::Network(m) => write!(f, "Hub není dostupný: {m}"),
        }
    }
}

pub trait HubApi {
    fn heartbeat(&self, body: &Heartbeat) -> Result<(), ApiError>;
    fn poll(&self, wait_seconds: u32) -> Result<Vec<Command>, ApiError>;
    fn report(&self, command_id: i64, result: &CommandResult) -> Result<(), ApiError>;
}

/// Adresa Hubu: jen https (Tailscale), http pouze pro localhost při vývoji. Vrací normalizovanou adresu bez `/`.
pub fn normalize_hub_url(raw: &str) -> Result<String, String> {
    let url = raw.trim().trim_end_matches('/').to_string();
    let lower = url.to_ascii_lowercase();
    let local = ["http://localhost", "http://127.0.0.1"]
        .iter()
        .any(|p| lower == *p || lower.starts_with(&format!("{p}:")) || lower.starts_with(&format!("{p}/")));
    if !(lower.starts_with("https://") || local) {
        return Err("Adresa Hubu musí začínat https:// (stejná jako adresa API v prohlížeči).".into());
    }
    if url.len() < 12 || url.contains(char::is_whitespace) || url.contains('?') || url.contains('#') {
        return Err("Neplatná adresa Hubu.".into());
    }
    Ok(url)
}

fn agent() -> ureq::Agent {
    ureq::AgentBuilder::new()
        .timeout_connect(Duration::from_secs(10))
        // long-poll čeká až 25 s na straně Hubu
        .timeout_read(Duration::from_secs(45))
        .timeout_write(Duration::from_secs(15))
        .build()
}

fn detail(resp: ureq::Response) -> String {
    let text = resp.into_string().unwrap_or_default();
    serde_json::from_str::<serde_json::Value>(&text)
        .ok()
        .and_then(|v| v.get("detail").and_then(|d| d.as_str()).map(str::to_string))
        .unwrap_or_else(|| text.chars().take(200).collect())
}

fn map_err(err: ureq::Error) -> ApiError {
    match err {
        ureq::Error::Status(401, resp) => ApiError::Unauthorized(detail(resp)),
        ureq::Error::Status(code, resp) => ApiError::Http(code, detail(resp)),
        ureq::Error::Transport(t) => ApiError::Network(t.kind().to_string()),
    }
}

/// Spárování (bez tokenu) – vrací token zařízení, který se uloží do Správce pověření Windows.
pub fn pair(hub_url: &str, body: &PairRequest) -> Result<PairResponse, ApiError> {
    let url = format!("{hub_url}/device/agent/pair");
    let resp = agent().post(&url).send_json(body).map_err(map_err)?;
    resp.into_json::<PairResponse>().map_err(|e| ApiError::Network(e.to_string()))
}

pub struct HttpHub {
    base: String,
    token: String,
    agent: ureq::Agent,
}

impl HttpHub {
    pub fn new(base: &str, token: &str) -> Self {
        Self { base: base.to_string(), token: token.to_string(), agent: agent() }
    }

    fn auth(&self) -> String {
        format!("Bearer {}", self.token)
    }
}

impl HubApi for HttpHub {
    fn heartbeat(&self, body: &Heartbeat) -> Result<(), ApiError> {
        self.agent
            .post(&format!("{}/device/agent/heartbeat", self.base))
            .set("Authorization", &self.auth())
            .send_json(body)
            .map(|_| ())
            .map_err(map_err)
    }

    fn poll(&self, wait_seconds: u32) -> Result<Vec<Command>, ApiError> {
        let resp = self
            .agent
            .get(&format!("{}/device/agent/commands", self.base))
            .query("wait", &wait_seconds.min(25).to_string())
            .set("Authorization", &self.auth())
            .call()
            .map_err(map_err)?;
        resp.into_json::<CommandsResponse>()
            .map(|r| r.commands)
            .map_err(|e| ApiError::Network(e.to_string()))
    }

    fn report(&self, command_id: i64, result: &CommandResult) -> Result<(), ApiError> {
        self.agent
            .post(&format!("{}/device/agent/commands/{command_id}/result", self.base))
            .set("Authorization", &self.auth())
            .send_json(result)
            .map(|_| ())
            .map_err(map_err)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn hub_url_must_be_https_except_localhost() {
        assert_eq!(normalize_hub_url(" https://hub.example.ts.net:8443/ ").unwrap(), "https://hub.example.ts.net:8443");
        assert!(normalize_hub_url("http://hub.example.ts.net:8443").is_err());
        assert!(normalize_hub_url("http://localhost.evil.com").is_err());
        assert_eq!(normalize_hub_url("http://localhost:8000").unwrap(), "http://localhost:8000");
        assert_eq!(normalize_hub_url("http://127.0.0.1:8000").unwrap(), "http://127.0.0.1:8000");
        assert!(normalize_hub_url("https://a b").is_err());
        assert!(normalize_hub_url("https://hub?x=1").is_err());
        assert!(normalize_hub_url("ftp://hub").is_err());
    }
}
