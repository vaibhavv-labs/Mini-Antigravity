pub mod file_ops;
pub mod shell;
pub mod web;

use anyhow::Result;
use async_trait::async_trait;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ToolCall {
    pub id: String,
    pub name: String,
    pub arguments: HashMap<String, serde_json::Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ToolResult {
    pub tool_call_id: String,
    pub content: String,
    pub success: bool,
}

#[async_trait]
pub trait Tool: Send + Sync {
    fn name(&self) -> &str;
    fn description(&self) -> &str;
    fn parameters_schema(&self) -> serde_json::Value;
    async fn execute(&self, args: HashMap<String, serde_json::Value>) -> Result<String>;
}

pub struct ToolRegistry {
    tools: HashMap<String, Box<dyn Tool>>,
}

impl ToolRegistry {
    pub fn new() -> Self {
        let mut registry = Self {
            tools: HashMap::new(),
        };
        registry.register_defaults();
        registry
    }

    fn register_defaults(&mut self) {
        self.register(Box::new(file_ops::ReadFileTool));
        self.register(Box::new(file_ops::WriteFileTool));
        self.register(Box::new(file_ops::ListDirTool));
        self.register(Box::new(file_ops::CreateDirTool));
        self.register(Box::new(file_ops::DeleteFileTool));
        self.register(Box::new(file_ops::SearchFilesTool));
        self.register(Box::new(shell::RunCommandTool));
        self.register(Box::new(web::WebSearchTool));
        self.register(Box::new(web::FetchUrlTool));
    }

    pub fn register(&mut self, tool: Box<dyn Tool>) {
        self.tools.insert(tool.name().to_string(), tool);
    }

    pub fn get(&self, name: &str) -> Option<&dyn Tool> {
        self.tools.get(name).map(|t| t.as_ref())
    }

    pub fn list(&self) -> Vec<(&str, &str)> {
        self.tools
            .iter()
            .map(|(name, tool)| (name.as_str(), tool.description()))
            .collect()
    }

    pub async fn execute(&self, call: &ToolCall) -> Result<ToolResult> {
        let tool = self
            .tools
            .get(&call.name)
            .ok_or_else(|| anyhow::anyhow!("Tool '{}' not found", call.name))?;

        match tool.execute(call.arguments.clone()).await {
            Ok(content) => Ok(ToolResult {
                tool_call_id: call.id.clone(),
                content,
                success: true,
            }),
            Err(e) => Ok(ToolResult {
                tool_call_id: call.id.clone(),
                content: format!("Error: {}", e),
                success: false,
            }),
        }
    }

    pub fn to_function_definitions(&self) -> Vec<serde_json::Value> {
        self.tools
            .iter()
            .map(|(_, tool)| {
                serde_json::json!({
                    "type": "function",
                    "function": {
                        "name": tool.name(),
                        "description": tool.description(),
                        "parameters": tool.parameters_schema()
                    }
                })
            })
            .collect()
    }
}
