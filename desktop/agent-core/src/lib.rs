//! Jádro agenta Jarvise pro PC (MRK-156): protokol `/device/agent/*`, konfigurace, zpracování příkazů a smyčka.
//! Bez závislosti na Windows ani Tauri – testuje se `cargo test -p agent-core` i na Linuxu.

pub mod agent;
pub mod client;
pub mod config;
pub mod protocol;
