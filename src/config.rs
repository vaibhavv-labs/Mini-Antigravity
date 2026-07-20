use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Config {
    pub workspace: PathBuf,
    pub agents_dir: PathBuf,
    pub openai_api_key: Option<String>,
    pub model: String,
    pub max_concurrent_agents: usize,
    pub scheduler_enabled: bool,
}

impl Default for Config {
    fn default() -> Self {
        let workspace = dirs::home_dir()
            .unwrap_or_else(|| PathBuf::from("."))
            .join(".mini-antigravity");

        Self {
            workspace: workspace.clone(),
            agents_dir: workspace.join("agents"),
            openai_api_key: std::env::var("OPENAI_API_KEY").ok(),
            model: "gpt-4".to_string(),
            max_concurrent_agents: 3,
            scheduler_enabled: false,
        }
    }
}

impl Config {
    pub fn load() -> Result<Self> {
        let config_path = Self::config_path();
        if config_path.exists() {
            let content = std::fs::read_to_string(&config_path)
                .context("Failed to read config file")?;
            let config: Config = toml::from_str(&content)
                .context("Failed to parse config file")?;
            Ok(config)
        } else {
            let config = Self::default();
            config.save()?;
            Ok(config)
        }
    }

    pub fn save(&self) -> Result<()> {
        let config_path = Self::config_path();
        if let Some(parent) = config_path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        let content = toml::to_string_pretty(self)
            .context("Failed to serialize config")?;
        std::fs::write(&config_path, content)?;
        Ok(())
    }

    fn config_path() -> PathBuf {
        dirs::config_dir()
            .unwrap_or_else(|| PathBuf::from("."))
            .join("mini-antigravity")
            .join("config.toml")
    }

    pub fn ensure_dirs(&self) -> Result<()> {
        std::fs::create_dir_all(&self.workspace)?;
        std::fs::create_dir_all(&self.agents_dir)?;
        Ok(())
    }
}
