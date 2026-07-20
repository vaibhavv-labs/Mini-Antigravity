# Mini Antigravity

A premium AI agent orchestration system inspired by Google Antigravity.

![Mini Antigravity UI](screenshot.png)

![UI Screenshot](screenshot.png)

## Features

- **6 AI Agents** - Architect, Engineer, Coder, Researcher, Reviewer, DevOps
- **Multi-Agent Orchestration** - Run workflows across multiple agents
- **File Explorer** - Browse and manage project files
- **Terminal** - Execute commands directly
- **Gemini AI Integration** - Real AI-powered responses
- **Premium UI** - Modern dark theme with glassmorphism

## Quick Start

### 1. Install Dependencies

```bash
pip install flask google-generativeai
```

### 2. Run the App

```bash
python pro_app.py
```

### 3. Open Browser

Go to `http://localhost:5000`

### 4. Connect AI (Optional)

- Get a free API key at [aistudio.google.com](https://aistudio.google.com)
- Paste it in the app, or click "Demo Mode" to try without AI

## CLI Version

```bash
python mini_antigravity.py init
python mini_antigravity.py agents
python mini_antigravity.py run engineer "write hello world"
python mini_antigravity.py orchestrate "build a todo app"
```

## Project Structure

```
mini-antigravity/
├── pro_app.py              # Web app backend
├── mini_antigravity.py     # CLI version
├── templates/
│   └── premium.html        # Web UI
├── agents/                 # Agent definitions
│   ├── architect.md
│   ├── engineer.md
│   ├── coder.md
│   ├── researcher.md
│   ├── reviewer.md
│   └── devops.md
└── README.md
```

## Agents

| Agent | Description |
|-------|-------------|
| Architect | Designs systems and specifications |
| Engineer | Writes production code |
| Coder | General coding assistant |
| Researcher | Researches and analyzes |
| Reviewer | Reviews code quality |
| DevOps | Deployment and infrastructure |

## Tools

| Tool | Description |
|------|-------------|
| read_file | Read file contents |
| write_file | Write to files |
| list_dir | List directory contents |
| run_command | Execute shell commands |
| search_files | Search files by pattern |

## Tech Stack

- Python 3.8+
- Flask
- Google Gemini AI
- Vanilla JS (no framework)

## License

MIT
