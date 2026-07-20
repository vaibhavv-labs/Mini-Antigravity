use anyhow::{Context, Result};
use regex::Regex;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::{Path, PathBuf};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentDefinition {
    pub name: String,
    pub description: String,
    pub system_prompt: String,
    pub tools: Vec<String>,
    pub max_iterations: usize,
    pub model: Option<String>,
}

impl AgentDefinition {
    pub fn from_markdown(path: &Path) -> Result<Self> {
        let content = std::fs::read_to_string(path)
            .context(format!("Failed to read agent file: {}", path.display()))?;

        let name = extract_frontmatter_field(&content, "name")
            .unwrap_or_else(|| {
                path.file_stem()
                    .unwrap_or_default()
                    .to_string_lossy()
                    .to_string()
            });

        let description = extract_frontmatter_field(&content, "description")
            .unwrap_or_default();

        let tools_str = extract_frontmatter_field(&content, "tools").unwrap_or_default();
        let tools: Vec<String> = if tools_str.is_empty() {
            vec![] // Empty means all tools
        } else {
            tools_str.split(',').map(|s| s.trim().to_string()).collect()
        };

        let max_iterations = extract_frontmatter_field(&content, "max_iterations")
            .and_then(|s| s.parse().ok())
            .unwrap_or(10);

        let model = extract_frontmatter_field(&content, "model");

        let system_prompt = extract_body(&content);

        Ok(Self {
            name,
            description,
            system_prompt,
            tools,
            max_iterations,
            model,
        })
    }

    pub fn builtin_architect() -> Self {
        Self {
            name: "architect".to_string(),
            description: "Technical architect that designs system specifications".to_string(),
            system_prompt: r#"You are a Technical Architect. Your role is to:
1. Analyze requirements and design technical specifications
2. Create detailed implementation plans with checklists
3. Define API signatures and data structures
4. Identify potential risks and mitigation strategies

Output your designs in markdown format with:
- Clear section headers
- Mermaid diagrams where appropriate
- Step-by-step implementation checklists
- API signatures with type information"#.to_string(),
            tools: vec!["read_file".to_string(), "list_dir".to_string(), "search_files".to_string()],
            max_iterations: 5,
            model: None,
        }
    }

    pub fn builtin_engineer() -> Self {
        Self {
            name: "engineer".to_string(),
            description: "Software engineer that implements code".to_string(),
            system_prompt: r#"You are a Software Engineer. Your role is to:
1. Implement code based on architectural specifications
2. Write clean, well-structured code following best practices
3. Create and run tests to verify your implementation
4. Document your changes

Always follow the specification exactly. Do not deviate from the architect's design.
After writing code, verify it compiles and passes tests."#.to_string(),
            tools: vec![], // All tools available
            max_iterations: 15,
            model: None,
        }
    }

    pub fn builtin_researcher() -> Self {
        Self {
            name: "researcher".to_string(),
            description: "Research agent that gathers information".to_string(),
            system_prompt: r#"You are a Research Agent. Your role is to:
1. Search the web for relevant information
2. Analyze and summarize findings
3. Provide accurate, well-sourced information
4. Present results in a clear, organized format

Always cite your sources and provide URLs where possible."#.to_string(),
            tools: vec!["web_search".to_string(), "fetch_url".to_string()],
            max_iterations: 8,
            model: None,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentState {
    pub id: String,
    pub agent_name: String,
    pub status: AgentStatus,
    pub messages: Vec<Message>,
    pub result: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub enum AgentStatus {
    Pending,
    Running,
    Completed,
    Failed,
    Cancelled,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Message {
    pub role: MessageRole,
    pub content: String,
    pub tool_calls: Option<Vec<ToolCallInfo>>,
    pub tool_results: Option<Vec<ToolResultInfo>>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum MessageRole {
    System,
    User,
    Assistant,
    Tool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ToolCallInfo {
    pub id: String,
    pub name: String,
    pub arguments: HashMap<String, serde_json::Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ToolResultInfo {
    pub tool_call_id: String,
    pub content: String,
    pub success: bool,
}

fn extract_frontmatter_field(content: &str, field: &str) -> Option<String> {
    let re = Regex::new(&format!(r"(?m)^{}:\s*(.+)$", field)).ok()?;
    re.captures(content)
        .and_then(|caps| caps.get(1))
        .map(|m| m.as_str().trim().to_string())
}

fn extract_body(content: &str) -> String {
    let lines: Vec<&str> = content.lines().collect();
    let mut body_start = 0;

    // Skip frontmatter (lines starting with key: value)
    for (i, line) in lines.iter().enumerate() {
        if line.trim().is_empty() && i > 0 {
            body_start = i + 1;
            break;
        }
        if !line.contains(':') && !line.trim().is_empty() {
            body_start = i;
            break;
        }
    }

    lines[body_start..].join("\n").trim().to_string()
}
