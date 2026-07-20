use anyhow::Result;
use clap::{Parser, Subcommand};
use colored::*;
use std::path::PathBuf;

mod agent;
mod config;
mod orchestrator;
mod scheduler;
mod tools;

use config::Config;
use orchestrator::Orchestrator;
use scheduler::{Schedule, ScheduledTask, Scheduler};

#[derive(Parser)]
#[command(name = "mini-antigravity")]
#[command(about = "A mini agent orchestration system inspired by Google Antigravity")]
#[command(version = "0.1.0")]
struct Cli {
    #[command(subcommand)]
    command: Commands,

    /// Path to workspace directory
    #[arg(short, long, global = true)]
    workspace: Option<PathBuf>,

    /// Enable verbose output
    #[arg(short, long, global = true)]
    verbose: bool,
}

#[derive(Subcommand)]
enum Commands {
    /// List available agents
    Agents,

    /// List available tools
    Tools,

    /// Run an agent with a task
    Run {
        /// Agent name to run
        agent: String,

        /// Task description
        task: Vec<String>,

        /// Context file path
        #[arg(short, long)]
        context: Option<PathBuf>,
    },

    /// Run an orchestrated multi-agent workflow
    Orchestrate {
        /// Task description
        task: Vec<String>,
    },

    /// Manage scheduled tasks
    #[command(subcommand)]
    Schedule(ScheduleCommands),

    /// Initialize workspace with default configuration
    Init,

    /// Show current configuration
    Config,

    /// Create a new agent definition
    CreateAgent {
        /// Agent name
        name: String,
    },
}

#[derive(Subcommand)]
enum ScheduleCommands {
    /// List scheduled tasks
    List,

    /// Add a new scheduled task
    Add {
        /// Task name
        name: String,

        /// Agent to run
        agent: String,

        /// Task description
        task: Vec<String>,

        /// Interval in seconds
        #[arg(short, long)]
        interval: Option<u64>,

        /// Run only once
        #[arg(short, long)]
        once: bool,
    },

    /// Remove a scheduled task
    Remove {
        /// Task ID
        id: String,
    },

    /// Start the scheduler
    Start,
}

#[tokio::main]
async fn main() -> Result<()> {
    let cli = Cli::parse();

    let mut config = Config::load()?;
    if let Some(workspace) = cli.workspace {
        config.workspace = workspace;
    }

    match cli.command {
        Commands::Agents => {
            let mut orch = Orchestrator::new(config);
            orch.initialize().await?;

            println!("\n{}", "Available Agents:".blue().bold());
            println!("{}", "═".repeat(50));

            for (name, desc) in orch.list_agents() {
                println!("  {} {}", name.cyan().bold(), desc.dimmed());
            }
            println!();
        }

        Commands::Tools => {
            let orch = Orchestrator::new(config);

            println!("\n{}", "Available Tools:".blue().bold());
            println!("{}", "═".repeat(50));

            for (name, desc) in orch.list_tools() {
                println!("  {} {}", name.green().bold(), desc.dimmed());
            }
            println!();
        }

        Commands::Run { agent, task, context } => {
            let mut orch = Orchestrator::new(config);
            orch.initialize().await?;

            let task_str = task.join(" ");
            let context_str = context.map(|p| {
                std::fs::read_to_string(&p)
                    .unwrap_or_else(|_| format!("Could not read context file: {}", p.display()))
            });

            let result = orch.run_agent(&agent, &task_str, context_str).await?;

            println!("\n{}", "Agent Result:".green().bold());
            println!("{}", "─".repeat(50));
            println!("{}", result);
            println!("{}", "─".repeat(50));
        }

        Commands::Orchestrate { task } => {
            let mut orch = Orchestrator::new(config);
            orch.initialize().await?;

            let task_str = task.join(" ");
            let result = orch.run_orchestrated_workflow(&task_str).await?;

            println!("\n{}", "Orchestration Result:".green().bold());
            println!("{}", "═".repeat(50));
            println!("{}", result);
            println!("{}", "═".repeat(50));
        }

        Commands::Schedule(schedule_cmd) => {
            let mut scheduler = Scheduler::new();

            match schedule_cmd {
                ScheduleCommands::List => {
                    let tasks = scheduler.list_tasks();
                    if tasks.is_empty() {
                        println!("\n{}", "No scheduled tasks.".yellow());
                    } else {
                        println!("\n{}", "Scheduled Tasks:".blue().bold());
                        println!("{}", "═".repeat(50));
                        for task in tasks {
                            let status = if task.enabled {
                                "ENABLED".green()
                            } else {
                                "DISABLED".red()
                            };
                            println!(
                                "  {} [{}] {} -> {}",
                                task.name.cyan().bold(),
                                status,
                                task.agent_name.yellow(),
                                task.task.dimmed()
                            );
                        }
                    }
                    println!();
                }

                ScheduleCommands::Add {
                    name,
                    agent,
                    task,
                    interval,
                    once,
                } => {
                    let schedule = if once {
                        Schedule::Once
                    } else if let Some(secs) = interval {
                        Schedule::Interval { seconds: secs }
                    } else {
                        Schedule::Interval { seconds: 3600 } // Default: hourly
                    };

                    let scheduled_task =
                        ScheduledTask::new(&name, &agent, &task.join(" "), schedule);
                    scheduler.add_task(scheduled_task);

                    println!(
                        "{} Added scheduled task: {}",
                        "[+]".green().bold(),
                        name.cyan()
                    );
                }

                ScheduleCommands::Remove { id } => {
                    scheduler.remove_task(&id)?;
                    println!(
                        "{} Removed scheduled task: {}",
                        "[-]".red().bold(),
                        id
                    );
                }

                ScheduleCommands::Start => {
                    scheduler.start().await?;
                }
            }
        }

        Commands::Init => {
            config.ensure_dirs()?;

            // Create example agent files
            let agents_dir = &config.agents_dir;

            let architect_content = r#"name: architect
description: Technical architect that designs system specifications
tools: read_file, list_dir, search_files
max_iterations: 5

You are a Technical Architect. Your role is to:
1. Analyze requirements and design technical specifications
2. Create detailed implementation plans with checklists
3. Define API signatures and data structures
4. Identify potential risks and mitigation strategies

Output your designs in markdown format with:
- Clear section headers
- Mermaid diagrams where appropriate
- Step-by-step implementation checklists
- API signatures with type information"#;

            let engineer_content = r#"name: engineer
description: Software engineer that implements code
max_iterations: 15

You are a Software Engineer. Your role is to:
1. Implement code based on architectural specifications
2. Write clean, well-structured code following best practices
3. Create and run tests to verify your implementation
4. Document your changes

Always follow the specification exactly. Do not deviate from the architect's design.
After writing code, verify it compiles and passes tests."#;

            let researcher_content = r#"name: researcher
description: Research agent that gathers information
tools: web_search, fetch_url
max_iterations: 8

You are a Research Agent. Your role is to:
1. Search the web for relevant information
2. Analyze and summarize findings
3. Provide accurate, well-sourced information
4. Present results in a clear, organized format

Always cite your sources and provide URLs where possible."#;

            std::fs::write(agents_dir.join("architect.md"), architect_content)?;
            std::fs::write(agents_dir.join("engineer.md"), engineer_content)?;
            std::fs::write(agents_dir.join("researcher.md"), researcher_content)?;

            println!(
                "{} Initialized workspace at {}",
                "[✓]".green().bold(),
                config.workspace.display()
            );
            println!("   Created agents directory with example agents");
        }

        Commands::Config => {
            println!("\n{}", "Current Configuration:".blue().bold());
            println!("{}", "═".repeat(50));
            println!("  Workspace:      {}", config.workspace.display());
            println!("  Agents Dir:     {}", config.agents_dir.display());
            println!("  Model:          {}", config.model);
            println!("  Max Concurrent: {}", config.max_concurrent_agents);
            println!(
                "  API Key:        {}",
                if config.openai_api_key.is_some() {
                    "Set".green()
                } else {
                    "Not set".yellow()
                }
            );
            println!();
        }

        Commands::CreateAgent { name } => {
            let template = format!(
                r#"name: {name}
description: Custom agent description
max_iterations: 10

You are a specialized agent. Define your role and capabilities here.

## Capabilities
- List what this agent can do

## Instructions
- Define how this agent should behave
"#,
                name = name
            );

            let path = config.agents_dir.join(format!("{}.md", name));
            std::fs::create_dir_all(&config.agents_dir)?;
            std::fs::write(&path, template)?;

            println!(
                "{} Created agent definition: {}",
                "[✓]".green().bold(),
                path.display()
            );
            println!("   Edit the file to customize the agent's behavior");
        }
    }

    Ok(())
}
