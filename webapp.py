#!/usr/bin/env python3
"""
Mini Antigravity - Web App
A web-based agent orchestration system
"""

from flask import Flask, render_template, request, jsonify
import os
import json
import glob
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
import uuid

try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

app = Flask(__name__)

# ============== AGENT SYSTEM ==============

class Tool:
    def name(self) -> str:
        raise NotImplementedError
    def description(self) -> str:
        raise NotImplementedError
    def parameters_schema(self) -> Dict:
        raise NotImplementedError
    def execute(self, args: Dict[str, Any]) -> str:
        raise NotImplementedError


class ReadFileTool(Tool):
    def name(self) -> str:
        return "read_file"
    def description(self) -> str:
        return "Read the contents of a file"
    def parameters_schema(self) -> Dict:
        return {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}
    def execute(self, args: Dict[str, Any]) -> str:
        path = args.get("path")
        if not path:
            return "Error: Missing path"
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            return f"Error: {e}"


class WriteFileTool(Tool):
    def name(self) -> str:
        return "write_file"
    def description(self) -> str:
        return "Write content to a file"
    def parameters_schema(self) -> Dict:
        return {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}
    def execute(self, args: Dict[str, Any]) -> str:
        path = args.get("path")
        content = args.get("content")
        if not path or content is None:
            return "Error: Missing path or content"
        try:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            return f"OK: Wrote to {path}"
        except Exception as e:
            return f"Error: {e}"


class ListDirTool(Tool):
    def name(self) -> str:
        return "list_dir"
    def description(self) -> str:
        return "List directory contents"
    def parameters_schema(self) -> Dict:
        return {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}
    def execute(self, args: Dict[str, Any]) -> str:
        path = args.get("path", ".")
        try:
            entries = []
            for entry in sorted(Path(path).iterdir()):
                prefix = "[DIR] " if entry.is_dir() else "[FILE] "
                entries.append(f"{prefix}{entry.name}")
            return "\n".join(entries) if entries else "Empty directory"
        except Exception as e:
            return f"Error: {e}"


class RunCommandTool(Tool):
    def name(self) -> str:
        return "run_command"
    def description(self) -> str:
        return "Execute a shell command"
    def parameters_schema(self) -> Dict:
        return {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}
    def execute(self, args: Dict[str, Any]) -> str:
        command = args.get("command")
        if not command:
            return "Error: Missing command"
        try:
            result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30)
            output = ""
            if result.stdout:
                output += result.stdout
            if result.stderr:
                output += result.stderr
            output += f"\nExit code: {result.returncode}"
            return output
        except subprocess.TimeoutExpired:
            return "Error: Command timed out"
        except Exception as e:
            return f"Error: {e}"


class ToolRegistry:
    def __init__(self):
        self.tools: Dict[str, Tool] = {}
        for tool in [ReadFileTool(), WriteFileTool(), ListDirTool(), RunCommandTool()]:
            self.tools[tool.name()] = tool

    def execute(self, name: str, args: Dict[str, Any]) -> str:
        tool = self.tools.get(name)
        if not tool:
            return f"Error: Tool '{name}' not found"
        try:
            return tool.execute(args)
        except Exception as e:
            return f"Error: {e}"

    def get_gemini_tools(self) -> List[Dict]:
        return [{"name": t.name(), "description": t.description(), "parameters": t.parameters_schema()} for t in self.tools.values()]


# ============== GLOBALS ==============

tool_registry = ToolRegistry()
chat_history = []
gemini_model = None
current_api_key = None


def init_gemini(api_key: str):
    global gemini_model, current_api_key
    if not GEMINI_AVAILABLE:
        return False, "google-generativeai not installed"
    try:
        genai.configure(api_key=api_key)
        gemini_model = genai.GenerativeModel("gemini-2.0-flash")
        current_api_key = api_key
        return True, "Gemini connected"
    except Exception as e:
        return False, str(e)


def chat_with_agent(agent_type: str, message: str) -> str:
    global gemini_model

    if not gemini_model:
        return "[Error] No AI connected. Add your Gemini API key first."

    system_prompts = {
        "architect": "You are a Technical Architect. Design systems, create specs, write checklists. Output in markdown.",
        "engineer": "You are a Software Engineer. Write actual working code. Follow specs exactly. Output code.",
        "researcher": "You are a Research Agent. Analyze and summarize information clearly.",
        "coder": "You are a Coder. Write clean, working code in any language.",
        "reviewer": "You are a Code Reviewer. Find bugs, suggest improvements."
    }

    system_prompt = system_prompts.get(agent_type, "You are a helpful AI assistant.")

    try:
        tools = tool_registry.get_gemini_tools()
        genai_tools = [{"function_declarations": tools}] if tools else None

        chat = gemini_model.start_chat(history=[
            {"role": "user", "parts": [system_prompt]},
            {"role": "model", "parts": ["I understand. I will follow these instructions."]}
        ])

        response = chat.send_message(message, tools=genai_tools)

        # Parse response
        text = ""
        tool_calls = []

        if response.candidates:
            for part in response.candidates[0].content.parts:
                if hasattr(part, 'text') and part.text:
                    text = part.text
                if hasattr(part, 'function_call') and part.function_call:
                    fc = part.function_call
                    tool_calls.append({"name": fc.name, "arguments": dict(fc.args) if fc.args else {}})

        # Execute tool calls if any
        results = []
        for tc in tool_calls:
            tool_result = tool_registry.execute(tc["name"], tc["arguments"])
            results.append(f"Tool: {tc['name']}\nResult: {tool_result}")

        if tool_calls:
            # Send tool results back
            tool_response = chat.send_message(json.dumps(results))
            if tool_response.candidates:
                for part in tool_response.candidates[0].content.parts:
                    if hasattr(part, 'text') and part.text:
                        text = part.text

        return text or "Task completed."

    except Exception as e:
        return f"[Error] {e}"


# ============== WEB ROUTES ==============

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/connect", methods=["POST"])
def connect_api():
    data = request.json
    api_key = data.get("api_key", "")
    success, message = init_gemini(api_key)
    return jsonify({"success": success, "message": message})


@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.json
    agent_type = data.get("agent", "engineer")
    message = data.get("message", "")

    if not message:
        return jsonify({"error": "No message provided"}), 400

    response = chat_with_agent(agent_type, message)

    chat_history.append({
        "agent": agent_type,
        "message": message,
        "response": response
    })

    return jsonify({"response": response, "agent": agent_type})


@app.route("/api/agents", methods=["GET"])
def list_agents():
    agents = [
        {"name": "architect", "description": "Designs systems and specs"},
        {"name": "engineer", "description": "Writes code"},
        {"name": "coder", "description": "General coding agent"},
        {"name": "researcher", "description": "Analyzes information"},
        {"name": "reviewer", "description": "Reviews code for bugs"}
    ]
    return jsonify({"agents": agents})


@app.route("/api/tools", methods=["GET"])
def list_tools():
    tools = [{"name": t.name(), "description": t.description()} for t in tool_registry.tools.values()]
    return jsonify({"tools": tools})


@app.route("/api/history", methods=["GET"])
def get_history():
    return jsonify({"history": chat_history[-20:]})  # Last 20 messages


if __name__ == "__main__":
    print("=" * 50)
    print("  Mini Antigravity - Web App")
    print("  Open http://localhost:5000 in your browser")
    print("=" * 50)
    app.run(debug=True, port=5000)
