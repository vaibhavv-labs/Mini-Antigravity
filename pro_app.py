#!/usr/bin/env python3
"""
Orbit PRO - Fixed & Polished
"""

from flask import Flask, render_template, request, jsonify
import os
import json
import glob
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Any
import uuid
from datetime import datetime

try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

app = Flask(__name__)
app.config['SECRET_KEY'] = 'orbit-pro-secret'

# ============== TOOL SYSTEM ==============

class Tool:
    def name(self) -> str: raise NotImplementedError
    def description(self) -> str: raise NotImplementedError
    def execute(self, args: Dict) -> str: raise NotImplementedError

class ReadFileTool(Tool):
    def name(self): return "read_file"
    def description(self): return "Read file contents"
    def execute(self, args):
        path = args.get("path", "")
        if not path:
            return "Error: No path provided"
        try:
            p = Path(path)
            if not p.exists():
                return f"Error: File not found: {path}"
            if not p.is_file():
                return f"Error: Not a file: {path}"
            with open(p, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            if len(content) > 10000:
                content = content[:10000] + "\n... (truncated)"
            return content
        except PermissionError:
            return f"Error: Permission denied: {path}"
        except Exception as e:
            return f"Error: {e}"

class WriteFileTool(Tool):
    def name(self): return "write_file"
    def description(self): return "Write content to a file"
    def execute(self, args):
        path = args.get("path", "")
        content = args.get("content", "")
        if not path:
            return "Error: No path provided"
        try:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, 'w', encoding='utf-8') as f:
                f.write(content)
            return f"OK: Wrote {len(content)} bytes to {path}"
        except PermissionError:
            return f"Error: Permission denied: {path}"
        except Exception as e:
            return f"Error: {e}"

class ListDirTool(Tool):
    def name(self): return "list_dir"
    def description(self): return "List directory contents"
    def execute(self, args):
        path = args.get("path", ".")
        try:
            p = Path(path)
            if not p.exists():
                return f"Error: Directory not found: {path}"
            if not p.is_dir():
                return f"Error: Not a directory: {path}"
            entries = []
            for e in sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
                try:
                    size = e.stat().st_size if e.is_file() else 0
                    entries.append({"name": e.name, "is_dir": e.is_dir(), "size": size, "path": str(e.resolve())})
                except PermissionError:
                    entries.append({"name": e.name, "is_dir": e.is_dir(), "size": 0, "path": str(e)})
            return json.dumps(entries)
        except Exception as e:
            return f"Error: {e}"

class RunCommandTool(Tool):
    def name(self): return "run_command"
    def description(self): return "Execute a shell command"
    def execute(self, args):
        command = args.get("command", "")
        if not command:
            return "Error: No command provided"
        try:
            r = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30)
            output = ""
            if r.stdout:
                output += r.stdout
            if r.stderr:
                output += "\n" + r.stderr if output else r.stderr
            output += f"\n[Exit code: {r.returncode}]"
            return output.strip()
        except subprocess.TimeoutExpired:
            return "Error: Command timed out after 30 seconds"
        except Exception as e:
            return f"Error: {e}"

class SearchFilesTool(Tool):
    def name(self): return "search_files"
    def description(self): return "Search files by glob pattern"
    def execute(self, args):
        pattern = args.get("pattern", "*")
        path = args.get("path", ".")
        try:
            full_pattern = os.path.join(path, pattern)
            matches = sorted(glob.glob(full_pattern, recursive=False))[:30]
            return json.dumps(matches) if matches else "No matches found"
        except Exception as e:
            return f"Error: {e}"

# ============== GEMINI CLIENT ==============

class GeminiClient:
    def __init__(self, api_key: str):
        if not GEMINI_AVAILABLE:
            raise ImportError("google-generativeai not installed. Run: pip install google-generativeai")
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel("gemini-2.0-flash")
        self.tools = [ReadFileTool(), WriteFileTool(), ListDirTool(), RunCommandTool(), SearchFilesTool()]

    def chat(self, messages: List[Dict], system_prompt: str = "") -> str:
        try:
            history = []
            if system_prompt:
                history.append({"role": "user", "parts": [system_prompt]})
                history.append({"role": "model", "parts": ["Understood. I will follow these instructions."]})

            for msg in messages[:-1]:
                role = "user" if msg.get("role") in ["user", "tool"] else "model"
                content = msg.get("content", "")
                if content and isinstance(content, str):
                    history.append({"role": role, "parts": [content]})

            chat = self.model.start_chat(history=history)
            user_msg = messages[-1].get("content", "")

            genai_tools = [{
                "function_declarations": [{
                    "name": t.name(),
                    "description": t.description(),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "File path"},
                            "command": {"type": "string", "description": "Shell command"},
                            "content": {"type": "string", "description": "File content"},
                            "pattern": {"type": "string", "description": "Search pattern"}
                        }
                    }
                } for t in self.tools]
            }]

            response = chat.send_message(user_msg, tools=genai_tools)

            text = ""
            tool_results = []

            if response.candidates:
                candidate = response.candidates[0]
                if candidate.content and candidate.content.parts:
                    for part in candidate.content.parts:
                        if hasattr(part, 'text') and part.text:
                            text += part.text
                        if hasattr(part, 'function_call') and part.function_call:
                            fc = part.function_call
                            for tool in self.tools:
                                if tool.name() == fc.name:
                                    args = dict(fc.args) if fc.args else {}
                                    result = tool.execute(args)
                                    tool_results.append({"tool": fc.name, "result": result})

            if tool_results:
                tool_msg = json.dumps(tool_results, indent=2)
                followup = chat.send_message(f"Here are the tool results:\n{tool_msg}\n\nNow provide your final response to the user.")
                if followup.candidates:
                    for part in followup.candidates[0].content.parts:
                        if hasattr(part, 'text') and part.text:
                            text = part.text

            return text if text else "Task completed."

        except Exception as e:
            error_msg = str(e)
            if "429" in error_msg or "quota" in error_msg.lower():
                return "Error: API quota exceeded. Please wait a moment and try again, or check your billing at aistudio.google.com"
            elif "403" in error_msg or "permission" in error_msg.lower():
                return "Error: API key invalid or permission denied. Please check your API key."
            elif "API_KEY_INVALID" in error_msg:
                return "Error: Invalid API key. Get a new one at aistudio.google.com/apikey"
            else:
                return f"Error: {error_msg[:200]}"

# ============== GLOBAL STATE ==============

tool_registry = {
    "read_file": ReadFileTool(),
    "write_file": WriteFileTool(),
    "list_dir": ListDirTool(),
    "run_command": RunCommandTool(),
    "search_files": SearchFilesTool()
}

gemini_client = None
chat_sessions = {}

# ============== AGENTS ==============

AGENTS = {
    "architect": {
        "name": "architect",
        "icon": "architect",
        "color": "#4285f4",
        "description": "Designs systems and specifications",
        "system": "You are a Technical Architect. Design systems, create specifications, write checklists. Output in clear markdown format with sections, bullet points, and code blocks where appropriate."
    },
    "engineer": {
        "name": "engineer",
        "icon": "engineer",
        "color": "#34a853",
        "description": "Writes production code",
        "system": "You are a Senior Software Engineer. Write clean, production-ready code. Follow best practices. Always include error handling. Output code with brief explanations."
    },
    "coder": {
        "name": "coder",
        "icon": "coder",
        "color": "#fbbc04",
        "description": "General coding assistant",
        "system": "You are a skilled programmer. Write clean, working code in any language. Explain your approach briefly. Include comments in code."
    },
    "researcher": {
        "name": "researcher",
        "icon": "researcher",
        "color": "#ea4335",
        "description": "Researches and analyzes information",
        "system": "You are a Research Analyst. Analyze information, provide insights, summarize findings clearly. Be concise and factual."
    },
    "reviewer": {
        "name": "reviewer",
        "icon": "reviewer",
        "color": "#ff6d01",
        "description": "Reviews code quality",
        "system": "You are a Code Reviewer. Find bugs, suggest improvements, check for security issues. Be constructive and specific."
    },
    "devops": {
        "name": "devops",
        "icon": "devops",
        "color": "#9334e6",
        "description": "DevOps and deployment",
        "system": "You are a DevOps Engineer. Help with deployment, CI/CD, Docker, cloud services, infrastructure. Provide practical commands and configurations."
    }
}

# ============== API ROUTES ==============

@app.route("/")
def index():
    return render_template("premium.html")

@app.route("/api/connect", methods=["POST"])
def connect():
    global gemini_client
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"success": False, "message": "Invalid request body"})
    api_key = data.get("api_key", "").strip()
    if not api_key:
        return jsonify({"success": False, "message": "Please provide an API key"})
    try:
        gemini_client = GeminiClient(api_key)
        return jsonify({"success": True, "message": "Connected to Gemini AI"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

@app.route("/api/agents", methods=["GET"])
def list_agents():
    return jsonify({"agents": list(AGENTS.values())})

@app.route("/api/tools", methods=["GET"])
def list_tools():
    return jsonify({"tools": [{"name": t.name(), "description": t.description()} for t in tool_registry.values()]})

@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid request"}), 400

    agent = data.get("agent", "engineer")
    message = data.get("message", "").strip()
    session_id = data.get("session_id", str(uuid.uuid4()))

    if not message:
        return jsonify({"error": "No message provided"}), 400

    if agent not in AGENTS:
        agent = "engineer"

    agent_config = AGENTS[agent]

    if not gemini_client:
        demo_responses = {
            "architect": "## Architecture Design\n\nBased on your request: **" + message + "**\n\n### Components\n1. **Frontend Layer** - User interface and client-side logic\n2. **API Gateway** - Request routing and authentication\n3. **Service Layer** - Business logic and data processing\n4. **Data Layer** - Database and caching\n\n### Tech Stack\n| Layer | Technology |\n|-------|------------|\n| Frontend | React / Vue.js |\n| Backend | Python / Node.js |\n| Database | PostgreSQL / MongoDB |\n| Cache | Redis |\n\n### Next Steps\n- Set up development environment\n- Create project structure\n- Implement core modules\n- Add tests",
            "engineer": "Here's the implementation for **" + message + "**:\n\n```python\nclass Solution:\n    def __init__(self):\n        self.initialized = True\n    \n    def execute(self, *args, **kwargs):\n        try:\n            result = self._process(*args, **kwargs)\n            return {\"status\": \"success\", \"data\": result}\n        except Exception as e:\n            return {\"status\": \"error\", \"message\": str(e)}\n    \n    def _process(self, *args, **kwargs):\n        return \"Processed successfully\"\n\nsolution = Solution()\nresult = solution.execute()\nprint(result)\n```\n\nThis includes error handling and clean structure.",
            "coder": "Here's the code for **" + message + "**:\n\n```python\ndef main():\n    print(\"Hello from Mini Antigravity!\")\n    data = process_input()\n    result = transform(data)\n    output(result)\n\ndef process_input():\n    return {\"key\": \"value\"}\n\ndef transform(data):\n    return {k: v.upper() if isinstance(v, str) else v for k, v in data.items()}\n\ndef output(result):\n    print(f\"Result: {result}\")\n\nif __name__ == \"__main__\":\n    main()\n```\n\nRun with: `python main.py`",
            "researcher": "## Research: " + message + "\n\n### Key Findings\n1. **Industry Standard** - Well-established pattern\n2. **Best Practice** - Follow SOLID principles\n3. **Performance** - Consider caching\n\n### Recommendations\n- Use proven frameworks\n- Write tests\n- Document decisions",
            "reviewer": "## Code Review: " + message + "\n\n### Issues Found\n| Severity | Issue | Suggestion |\n|----------|-------|------------|\n| High | Missing error handling | Add try/except |\n| Medium | No input validation | Validate inputs |\n| Low | Missing docstrings | Add docs |\n\n### Suggestions\n1. Add error handling\n2. Include unit tests\n3. Use type hints\n4. Add logging",
            "devops": "## Deployment Plan: " + message + "\n\n### Steps\n1. Build: `docker build -t myapp:latest .`\n2. Test: `docker run --rm myapp:latest npm test`\n3. Push: `docker push registry/myapp:latest`\n4. Deploy: `kubectl apply -f deployment.yaml`\n\n### Monitoring\n- Set up health checks\n- Configure alerts"
        }
        response = demo_responses.get(agent, "I'll help with: **" + message + "**")
        return jsonify({"response": response, "session_id": session_id, "agent": agent})

    # Real AI response
    if session_id not in chat_sessions:
        chat_sessions[session_id] = []

    chat_sessions[session_id].append({"role": "user", "content": message})

    response = gemini_client.chat(chat_sessions[session_id], agent_config["system"])

    chat_sessions[session_id].append({"role": "assistant", "content": response})

    # Keep session manageable
    if len(chat_sessions[session_id]) > 50:
        chat_sessions[session_id] = chat_sessions[session_id][-30:]

    return jsonify({"response": response, "session_id": session_id, "agent": agent})

@app.route("/api/orchestrate", methods=["POST"])
def orchestrate():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid request"}), 400

    task = data.get("task", "").strip()
    if not task:
        return jsonify({"error": "No task provided"}), 400

    if not gemini_client:
        return jsonify({
            "phases": [
                {"agent": "architect", "status": "completed", "result": f"## Architecture for: {task}\n\n### Structure\n- Frontend component\n- Backend API\n- Database layer\n\n### Design Pattern\nUse MVC architecture with clean separation of concerns."},
                {"agent": "engineer", "status": "completed", "result": f"## Implementation\n\n```python\nclass App:\n    def __init__(self):\n        self.setup()\n    \n    def setup(self):\n        print('App initialized')\n    \n    def run(self):\n        print('App running')\n\napp = App()\napp.run()\n```"},
                {"agent": "reviewer", "status": "completed", "result": f"## Review Complete\n\n**Status:** Approved with minor suggestions\n\n### Feedback\n- Code structure is clean\n- Add error handling\n- Include unit tests\n- Add logging"}
            ]
        })

    results = []
    session_id = str(uuid.uuid4())

    for phase_agent in ["architect", "engineer", "reviewer"]:
        agent_config = AGENTS[phase_agent]
        if session_id not in chat_sessions:
            chat_sessions[session_id] = []
        chat_sessions[session_id].append({"role": "user", "content": task})
        response = gemini_client.chat(chat_sessions[session_id], agent_config["system"])
        chat_sessions[session_id].append({"role": "assistant", "content": response})
        results.append({"agent": phase_agent, "status": "completed", "result": response})

    return jsonify({"phases": results})

@app.route("/api/files", methods=["GET"])
def list_files():
    path = request.args.get("path", ".")
    try:
        p = Path(path).resolve()
        if not p.exists():
            return jsonify({"error": f"Path not found: {path}", "files": [], "current": path})
        if not p.is_dir():
            return jsonify({"error": f"Not a directory: {path}", "files": [], "current": path})

        entries = []
        try:
            items = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
        except PermissionError:
            return jsonify({"error": "Permission denied", "files": [], "current": str(p)})

        for e in items:
            try:
                stat = e.stat()
                entries.append({
                    "name": e.name,
                    "path": str(e),
                    "is_dir": e.is_dir(),
                    "size": stat.st_size if e.is_file() else 0,
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat()[:19]
                })
            except (PermissionError, OSError):
                entries.append({
                    "name": e.name,
                    "path": str(e),
                    "is_dir": e.is_dir(),
                    "size": 0,
                    "modified": ""
                })

        return jsonify({"files": entries, "current": str(p)})
    except Exception as e:
        return jsonify({"error": str(e), "files": [], "current": path})

@app.route("/api/file", methods=["GET"])
def read_file():
    path = request.args.get("path", "")
    if not path:
        return jsonify({"error": "No path provided"}), 400
    try:
        p = Path(path)
        if not p.exists():
            return jsonify({"error": f"File not found: {path}"}), 404
        if not p.is_file():
            return jsonify({"error": f"Not a file: {path}"}), 400
        with open(p, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        return jsonify({"content": content, "path": str(p.resolve())})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/file", methods=["POST"])
def write_file():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid request"}), 400
    path = data.get("path", "")
    content = data.get("content", "")
    if not path:
        return jsonify({"error": "No path provided"}), 400
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, 'w', encoding='utf-8') as f:
            f.write(content)
        return jsonify({"success": True, "message": f"Wrote {len(content)} bytes to {path}"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/terminal", methods=["POST"])
def terminal():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid request"}), 400
    command = data.get("command", "").strip()
    if not command:
        return jsonify({"error": "No command provided"}), 400
    cwd = data.get("cwd", None)
    if cwd and not Path(cwd).exists():
        cwd = None
    try:
        r = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30, cwd=cwd)
        return jsonify({
            "stdout": r.stdout,
            "stderr": r.stderr,
            "code": r.returncode
        })
    except subprocess.TimeoutExpired:
        return jsonify({"stdout": "", "stderr": "Command timed out after 30 seconds", "code": -1})
    except Exception as e:
        return jsonify({"stdout": "", "stderr": str(e), "code": -1})

# ============== MAIN ==============

if __name__ == "__main__":
    print("=" * 50)
    print("  Mini Antigravity - AI Agent Platform")
    print("  http://localhost:5000")
    print("=" * 50)
    app.run(debug=False, port=5000, host="127.0.0.1")
