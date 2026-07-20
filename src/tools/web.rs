use super::Tool;
use anyhow::Result;
use async_trait::async_trait;
use reqwest::Client;
use std::collections::HashMap;

pub struct WebSearchTool;

#[async_trait]
impl Tool for WebSearchTool {
    fn name(&self) -> &str {
        "web_search"
    }

    fn description(&self) -> &str {
        "Search the web using a search engine"
    }

    fn parameters_schema(&self) -> serde_json::Value {
        serde_json::json!({
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query"
                },
                "num_results": {
                    "type": "integer",
                    "description": "Number of results to return (default: 5)"
                }
            },
            "required": ["query"]
        })
    }

    async fn execute(&self, args: HashMap<String, serde_json::Value>) -> Result<String> {
        let query = args
            .get("query")
            .and_then(|v| v.as_str())
            .ok_or_else(|| anyhow::anyhow!("Missing 'query' argument"))?;

        let _num_results = args
            .get("num_results")
            .and_then(|v| v.as_i64())
            .unwrap_or(5);

        // Use DuckDuckGo Lite as a simple search backend
        let client = Client::new();
        let url = format!("https://lite.duckduckgo.com/lite/?q={}", urlencoding::encode(query));

        let response = client
            .get(&url)
            .header("User-Agent", "MiniAntigravity/1.0")
            .send()
            .await?
            .text()
            .await?;

        // Parse the response (simplified extraction)
        let results = extract_search_results(&response);
        if results.is_empty() {
            Ok(format!("No results found for: {}", query))
        } else {
            Ok(results.join("\n\n"))
        }
    }
}

fn extract_search_results(html: &str) -> Vec<String> {
    let mut results = Vec::new();
    let lines: Vec<&str> = html.lines().collect();

    for (i, line) in lines.iter().enumerate() {
        if line.contains("<a") && line.contains("href=") {
            if let Some(start) = line.find("href=\"") {
                let url_start = start + 6;
                if let Some(end) = line[url_start..].find("\"") {
                    let url = &line[url_start..url_start + end];
                    // Get the next line as title
                    if i + 1 < lines.len() {
                        let title = strip_html_tags(lines[i + 1]);
                        if !title.is_empty() && url.starts_with("http") {
                            results.push(format!("{}\nURL: {}", title.trim(), url));
                        }
                    }
                }
            }
        }
        if results.len() >= 5 {
            break;
        }
    }
    results
}

fn strip_html_tags(s: &str) -> String {
    let mut result = String::new();
    let mut in_tag = false;
    for c in s.chars() {
        match c {
            '<' => in_tag = true,
            '>' => in_tag = false,
            _ if !in_tag => result.push(c),
            _ => {}
        }
    }
    result
}

pub struct FetchUrlTool;

#[async_trait]
impl Tool for FetchUrlTool {
    fn name(&self) -> &str {
        "fetch_url"
    }

    fn description(&self) -> &str {
        "Fetch content from a URL"
    }

    fn parameters_schema(&self) -> serde_json::Value {
        serde_json::json!({
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL to fetch"
                },
                "max_length": {
                    "type": "integer",
                    "description": "Maximum content length (default: 10000)"
                }
            },
            "required": ["url"]
        })
    }

    async fn execute(&self, args: HashMap<String, serde_json::Value>) -> Result<String> {
        let url = args
            .get("url")
            .and_then(|v| v.as_str())
            .ok_or_else(|| anyhow::anyhow!("Missing 'url' argument"))?;

        let max_length = args
            .get("max_length")
            .and_then(|v| v.as_i64())
            .unwrap_or(10000) as usize;

        let client = Client::new();
        let response = client
            .get(url)
            .header("User-Agent", "MiniAntigravity/1.0")
            .send()
            .await?
            .text()
            .await?;

        let content = if response.len() > max_length {
            format!("{}... [truncated]", &response[..max_length])
        } else {
            response
        };

        Ok(content)
    }
}
