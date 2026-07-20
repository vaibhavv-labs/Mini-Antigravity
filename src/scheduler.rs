use anyhow::Result;
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use tokio::sync::mpsc;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ScheduledTask {
    pub id: String,
    pub name: String,
    pub agent_name: String,
    pub task: String,
    pub schedule: Schedule,
    pub enabled: bool,
    pub last_run: Option<DateTime<Utc>>,
    pub next_run: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum Schedule {
    Once,
    Interval { seconds: u64 },
    Cron { expression: String },
}

pub struct Scheduler {
    tasks: HashMap<String, ScheduledTask>,
    shutdown_tx: Option<mpsc::Sender<()>>,
}

impl Scheduler {
    pub fn new() -> Self {
        Self {
            tasks: HashMap::new(),
            shutdown_tx: None,
        }
    }

    pub fn add_task(&mut self, task: ScheduledTask) {
        self.tasks.insert(task.id.clone(), task);
    }

    pub fn remove_task(&mut self, id: &str) -> Result<()> {
        self.tasks
            .remove(id)
            .ok_or_else(|| anyhow::anyhow!("Task '{}' not found", id))?;
        Ok(())
    }

    pub fn list_tasks(&self) -> Vec<&ScheduledTask> {
        self.tasks.values().collect()
    }

    pub async fn start(&mut self) -> Result<()> {
        let (shutdown_tx, mut shutdown_rx) = mpsc::channel(1);
        self.shutdown_tx = Some(shutdown_tx);

        println!(
            "{} Scheduler started with {} tasks",
            "[Scheduler]".cyan(),
            self.tasks.len()
        );

        loop {
            tokio::select! {
                _ = shutdown_rx.recv() => {
                    println!("{} Scheduler shutting down", "[Scheduler]".yellow());
                    break;
                }
                _ = tokio::time::sleep(std::time::Duration::from_secs(1)) => {
                    // Check for due tasks
                    let now = Utc::now();
                    for task in self.tasks.values_mut() {
                        if task.enabled {
                            if let Some(next_run) = task.next_run {
                                if now >= next_run {
                                    println!(
                                        "{} Running scheduled task: {}",
                                        "[Scheduler]".green(),
                                        task.name
                                    );
                                    // In real implementation, trigger agent execution
                                    task.last_run = Some(now);
                                    task.next_run = Self::calculate_next_run(&task.schedule);
                                }
                            }
                        }
                    }
                }
            }
        }

        Ok(())
    }

    pub fn stop(&self) -> Result<()> {
        if let Some(tx) = &self.shutdown_tx {
            tx.try_send(())?;
        }
        Ok(())
    }

    fn calculate_next_run(schedule: &Schedule) -> Option<DateTime<Utc>> {
        match schedule {
            Schedule::Once => None,
            Schedule::Interval { seconds } => {
                let now = Utc::now();
                Some(now + chrono::Duration::seconds(*seconds as i64))
            }
            Schedule::Cron { .. } => {
                // Simplified - in real implementation use cron crate
                let now = Utc::now();
                Some(now + chrono::Duration::hours(1))
            }
        }
    }
}

impl ScheduledTask {
    pub fn new(name: &str, agent_name: &str, task: &str, schedule: Schedule) -> Self {
        Self {
            id: uuid::Uuid::new_v4().to_string(),
            name: name.to_string(),
            agent_name: agent_name.to_string(),
            task: task.to_string(),
            schedule,
            enabled: true,
            last_run: None,
            next_run: Some(Utc::now()),
        }
    }
}
