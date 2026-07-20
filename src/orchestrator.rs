use crate::agent::*;
use crate::config::Config;
use crate::tools::{ToolCall, ToolRegistry, ToolResult};
use anyhow::{Context, Result};
use colored::*;
use futures::stream::{self, StreamExt};
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use tokio::sync::mpsc;
use uuid::Uuid;

pub struct Orchestrator {
    config: Config,
    tool_registry: ToolRegistry,
    agents: HashMap<String, AgentDefinition>,
    states: HashMap<String, AgentState>,
}

impl Orchestrator {
    pub fn new(config: Config) -> Self {
        let tool_registry = ToolRegistry::new();
        let mut agents = HashMap::new();

        // Register built-in agents
        let architect = AgentDefinition::builtin_architect();
        let engineer = AgentDefinition::builtin_engineer();
        let researcher = AgentDefinition::builtin_researcher();

        agents.insert(architect.name.clone(), architect);
        agents.insert(engineer.name.clone(), engineer);
        agents.insert(researcher.name.clone(), researcher);

        Self {
            config,
            tool_registry,
            agents,
            states: HashMap::new(),
        }
    }

    pub async fn initialize(&mut self) -> Result<()> {
        self.config.ensure_dirs()?;
        self.load_custom_agents()?;
        Ok(())
    }

    fn load_custom_agents(&mut self) -> Result<()> {
        if !self.config.agents_dir.exists() {
            return Ok(());
        }

        for entry in std::fs::read_dir(&self.config.agents_dir)? {
            let entry = entry?;
            let path = entry.path();

            if path.extension().and_then(|e| e.to_str()) == Some("md") {
                match AgentDefinition::from_markdown(&path) {
                    Ok(agent) => {
                        println!(
                            "{} Loaded agent: {}",
                            "[+]".green().bold(),
                            agent.name.cyan()
                        );
                        self.agents.insert(agent.name.clone(), agent);
                    }
                    Err(e) => {
                        println!(
                            "{} Failed to load agent from {}: {}",
                            "[!]".yellow().bold(),
                            path.display(),
                            e
                        );
                    }
                }
            }
        }
        Ok(())
    }

    pub fn list_agents(&self) -> Vec<(&str, &str)> {
        self.agents
            .iter()
            .map(|(name, agent)| (name.as_str(), agent.description.as_str()))
            .collect()
    }

    pub fn list_tools(&self) -> Vec<(&str, &str)> {
        self.tool_registry.list()
    }

    pub async fn run_agent(
        &mut self,
        agent_name: &str,
        task: &str,
        context: Option<String>,
    ) -> Result<String> {
        let agent = self
            .agents
            .get(agent_name)
            .ok_or_else(|| anyhow::anyhow!("Agent '{}' not found", agent_name))?
            .clone();

        let state_id = Uuid::new_v4().to_string();
        let mut state = AgentState {
            id: state_id.clone(),
            agent_name: agent_name.to_string(),
            status: AgentStatus::Running,
            messages: Vec::new(),
            result: None,
        };

        // Build initial messages
        state.messages.push(Message {
            role: MessageRole::System,
            content: agent.system_prompt.clone(),
            tool_calls: None,
            tool_results: None,
        });

        let user_message = if let Some(ctx) = context {
            format!("{}\n\nContext:\n{}", task, ctx)
        } else {
            task.to_string()
        };

        state.messages.push(Message {
            role: MessageRole::User,
            content: user_message,
            tool_calls: None,
            tool_results: None,
        });

        self.states.insert(state_id.clone(), state.clone());

        println!(
            "\n{} Starting agent: {}",
            ">>".blue().bold(),
            agent.name.cyan()
        );
        println!("   Task: {}", task.yellow());

        let mut iterations = 0;

        while iterations < agent.max_iterations {
            iterations += 1;
            println!(
                "\n{} Iteration {}/{}",
                "→".dimmed(),
                iterations,
                agent.max_iterations
            );

            // Get available tools for this agent
            let available_tools: Vec<String> = if agent.tools.is_empty() {
                self.tool_registry.list().iter().map(|(n, _)| n.to_string()).collect()
            } else {
                agent.tools.clone()
            };

            // Simulate LLM response (in real implementation, call OpenAI/Anthropic API)
            let response = self.simulate_llm_response(&state, &available_tools).await?;

            if let Some(tool_calls) = response.tool_calls {
                // Execute tool calls
                state.messages.push(Message {
                    role: MessageRole::Assistant,
                    content: response.content.unwrap_or_default(),
                    tool_calls: Some(
                        tool_calls
                            .iter()
                            .map(|tc| ToolCallInfo {
                                id: tc.id.clone(),
                                name: tc.name.clone(),
                                arguments: tc.arguments.clone(),
                            })
                            .collect(),
                    ),
                    tool_results: None,
                });

                let mut tool_results = Vec::new();
                for tool_call in &tool_calls {
                    println!("   {} Executing: {}", "⚡".yellow(), tool_call.name);
                    match self.tool_registry.execute(tool_call).await {
                        Ok(result) => {
                            println!(
                                "   {} {}",
                                if result.success { "✓".green() } else { "✗".red() },
                                &result.content[..result.content.len().min(100)]
                            );
                            tool_results.push(ToolResultInfo {
                                tool_call_id: result.tool_call_id,
                                content: result.content,
                                success: result.success,
                            });
                        }
                        Err(e) => {
                            println!("   {} Error: {}", "✗".red(), e);
                            tool_results.push(ToolResultInfo {
                                tool_call_id: tool_call.id.clone(),
                                content: format!("Error: {}", e),
                                success: false,
                            });
                        }
                    }
                }

                state.messages.push(Message {
                    role: MessageRole::Tool,
                    content: tool_results
                        .iter()
                        .map(|r| format!("Tool {} result: {}", r.tool_call_id, r.content))
                        .collect::<Vec<_>>()
                        .join("\n"),
                    tool_calls: None,
                    tool_results: Some(tool_results),
                });
            } else {
                // No tool calls - agent is done
                let final_response = response.content.unwrap_or_default();
                state.messages.push(Message {
                    role: MessageRole::Assistant,
                    content: final_response.clone(),
                    tool_calls: None,
                    tool_results: None,
                });

                state.status = AgentStatus::Completed;
                state.result = Some(final_response.clone());
                self.states.insert(state_id.clone(), state);

                println!(
                    "\n{} Agent {} completed",
                    "✓".green().bold(),
                    agent.name.cyan()
                );

                return Ok(final_response);
            }

            self.states.insert(state_id.clone(), state.clone());
        }

        // Max iterations reached
        state.status = AgentStatus::Completed;
        state.result = Some("Max iterations reached".to_string());
        self.states.insert(state_id.clone(), state);

        Ok("Max iterations reached without completion".to_string())
    }

    async fn simulate_llm_response(
        &self,
        state: &AgentState,
        available_tools: &[String],
    ) -> Result<SimulatedResponse> {
        // This is a simulation - in real implementation, call LLM API
        // For now, return a simple response that demonstrates the tool system
        let last_message = state.messages.last().unwrap();

        if last_message.role == MessageRole::User {
            // First iteration - suggest using tools
            Ok(SimulatedResponse {
                content: Some(format!(
                    "I'll help with this task. Let me start by exploring the workspace."
                )),
                tool_calls: Some(vec![ToolCall {
                    id: Uuid::new_v4().to_string(),
                    name: "list_dir".to_string(),
                    arguments: HashMap::from([("path".to_string(), serde_json::json!("."))]),
                }]),
            })
        } else if last_message.role == MessageRole::Tool {
            // After tool execution, provide summary
            Ok(SimulatedResponse {
                content: Some(format!(
                    "I've completed the task. The workspace has been explored successfully."
                )),
                tool_calls: None,
            })
        } else {
            Ok(SimulatedResponse {
                content: Some("Task completed.".to_string()),
                tool_calls: None,
            })
        }
    }

    pub async fn run_orchestrated_workflow(
        &mut self,
        task: &str,
    ) -> Result<String> {
        println!(
            "\n{} Starting orchestrated workflow",
            "═══════════════════════════════════════".blue()
        );
        println!("   Task: {}", task.cyan());

        // Phase 1: Architect designs the solution
        println!("\n{} Phase 1: Design", "1.".blue().bold());
        let design = self.run_agent("architect", task, None).await?;

        // Phase 2: Engineer implements the solution
        println!("\n{} Phase 2: Implementation", "2.".blue().bold());
        let implementation = self
            .run_agent("engineer", "Implement the following design", Some(design))
            .await?;

        // Phase 3: Research any unknowns
        println!("\n{} Phase 3: Research & Verification", "3.".blue().bold());
        let verification = self
            .run_agent(
                "researcher",
                "Verify the implementation approach and find best practices",
                Some(implementation.clone()),
            )
            .await?;

        let final_result = format!(
            "# Workflow Complete\n\n## Design\n{}\n\n## Implementation\n{}\n\n## Verification\n{}",
            design, implementation, verification
        );

        println!(
            "\n{} Workflow completed successfully!",
            "✓".green().bold()
        );

        Ok(final_result)
    }

    pub async fn spawn_subagent(
        &self,
        parent_id: &str,
        agent_name: &str,
        task: String,
    ) -> Result<mpsc::Receiver<String>> {
        let (tx, rx) = mpsc::channel(100);
        let agent = self.agents.get(agent_name).cloned();
        let tools = self.tool_registry.list().iter().map(|(n, _)| n.to_string()).collect();

        if let Some(agent_def) = agent {
            tokio::spawn(async move {
                let result = format!(
                    "Subagent {} completed task: {}",
                    agent_def.name, task
                );
                let _ = tx.send(result).await;
            });
        }

        Ok(rx)
    }

    pub fn get_state(&self, id: &str) -> Option<&AgentState> {
        self.states.get(id)
    }

    pub fn list_states(&self) -> Vec<&AgentState> {
        self.states.values().collect()
    }
}

struct SimulatedResponse {
    content: Option<String>,
    tool_calls: Option<Vec<ToolCall>>,
}
