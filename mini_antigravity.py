#!/usr/bin/env python3
"""
Mini Antigravity - A mini agent orchestration system
Inspired by Google Antigravity
Now with real Gemini AI integration!
"""

import os
import sys
import json
import glob
import subprocess
import re
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
import uuid
from datetime import datetime

try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
    print("\033[33m[!]\033[0m google-generativeai not installed. Install it: pip install google-generativeai\n")


class AgentStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: Dict[str, Any]


@dataclass
class ToolResult:
    tool_call_id: str
    content: str
    success: bool


@dataclass
class AgentDefinition:
    name: str
    description: str
    system_prompt: str
    tools: List[str] = field(default_factory=list)
    max_iterations: int = 10


@dataclass
class AgentState:
    id: str
    agent_name: str
    status: AgentStatus
    messages: List[Dict]
    result: Optional[str] = None


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
        return {"type": "object", "properties": {"path": {"type": "string", "description": "Path to the file"}}, "required": ["path"]}
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
        return "Write content to a file (creates or overwrites)"
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
            return f"OK: Wrote {len(content)} chars to {path}"
        except Exception as e:
            return f"Error: {e}"


class ListDirTool(Tool):
    def name(self) -> str:
        return "list_dir"
    def description(self) -> str:
        return "List contents of a directory"
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


class SearchFilesTool(Tool):
    def name(self) -> str:
        return "search_files"
    def description(self) -> str:
        return "Search for files matching a glob pattern"
    def parameters_schema(self) -> Dict:
        return {"type": "object", "properties": {"pattern": {"type": "string"}, "path": {"type": "string"}}, "required": ["pattern"]}
    def execute(self, args: Dict[str, Any]) -> str:
        pattern = args.get("pattern")
        path = args.get("path", ".")
        if not pattern:
            return "Error: Missing pattern"
        try:
            full_pattern = os.path.join(path, pattern)
            matches = sorted(glob.glob(full_pattern, recursive=True))
            return "\n".join(matches[:20]) if matches else "No matches"
        except Exception as e:
            return f"Error: {e}"


class RunCommandTool(Tool):
    def name(self) -> str:
        return "run_command"
    def description(self) -> str:
        return "Execute a shell command"
    def parameters_schema(self) -> Dict:
        return {"type": "object", "properties": {"command": {"type": "string"}, "working_dir": {"type": "string"}}, "required": ["command"]}
    def execute(self, args: Dict[str, Any]) -> str:
        command = args.get("command")
        working_dir = args.get("working_dir")
        if not command:
            return "Error: Missing command"
        try:
            result = subprocess.run(command, shell=True, cwd=working_dir, capture_output=True, text=True, timeout=60)
            output = ""
            if result.stdout:
                output += f"STDOUT:\n{result.stdout}\n"
            if result.stderr:
                output += f"STDERR:\n{result.stderr}\n"
            output += f"Exit code: {result.returncode}"
            return output
        except subprocess.TimeoutExpired:
            return "Error: Command timed out"
        except Exception as e:
            return f"Error: {e}"


class ToolRegistry:
    def __init__(self):
        self.tools: Dict[str, Tool] = {}
        self._register_defaults()

    def _register_defaults(self):
        for tool in [ReadFileTool(), WriteFileTool(), ListDirTool(), SearchFilesTool(), RunCommandTool()]:
            self.register(tool)

    def register(self, tool: Tool):
        self.tools[tool.name()] = tool

    def get(self, name: str) -> Optional[Tool]:
        return self.tools.get(name)

    def list(self) -> List[tuple]:
        return [(name, tool.description()) for name, tool in self.tools.items()]

    def execute(self, call: ToolCall) -> ToolResult:
        tool = self.tools.get(call.name)
        if not tool:
            return ToolResult(tool_call_id=call.id, content=f"Error: Tool '{call.name}' not found", success=False)
        try:
            content = tool.execute(call.arguments)
            return ToolResult(tool_call_id=call.id, content=content, success=not content.startswith("Error:"))
        except Exception as e:
            return ToolResult(tool_call_id=call.id, content=f"Error: {e}", success=False)

    def get_gemini_tools(self) -> List[Dict]:
        """Convert tools to Gemini function declarations"""
        declarations = []
        for name, tool in self.tools.items():
            declarations.append({
                "name": name,
                "description": tool.description(),
                "parameters": tool.parameters_schema()
            })
        return declarations


class GeminiClient:
    def __init__(self, api_key: str, model_name: str = "gemini-2.0-flash"):
        if not GEMINI_AVAILABLE:
            raise ImportError("google-generativeai not installed")
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(model_name)

    def chat(self, messages: List[Dict], tools: List[Dict]) -> Tuple[Optional[str], Optional[List[ToolCall]]]:
        """Send messages to Gemini and get response"""
        # Build conversation history
        history = []
        for msg in messages[:-1]:
            if msg["role"] == "system":
                continue
            role = "user" if msg["role"] in ["user", "tool"] else "model"
            content = msg.get("content", "")
            if content:
                history.append({"role": role, "parts": [content]})

        # Get the last user message
        last_msg = messages[-1]
        user_input = last_msg.get("content", "")

        try:
            chat = self.model.start_chat(history=history)

            # Configure with tools
            genai_tools = [{"function_declarations": tools}] if tools else None

            response = chat.send_message(
                user_input,
                tools=genai_tools
            )

            # Parse response
            text_response = None
            tool_calls = None

            if response.candidates:
                candidate = response.candidates[0]
                if candidate.content and candidate.content.parts:
                    for part in candidate.content.parts:
                        if hasattr(part, 'text') and part.text:
                            text_response = part.text
                        if hasattr(part, 'function_call') and part.function_call:
                            if not tool_calls:
                                tool_calls = []
                            fc = part.function_call
                            tool_calls.append(ToolCall(
                                id=str(uuid.uuid4()),
                                name=fc.name,
                                arguments=dict(fc.args) if fc.args else {}
                            ))

            return text_response, tool_calls

        except Exception as e:
            return f"Gemini API error: {e}", None


class Orchestrator:
    def __init__(self, workspace: str = ".", api_key: Optional[str] = None):
        self.workspace = Path(workspace)
        self.agents_dir = self.workspace / "agents"
        self.tool_registry = ToolRegistry()
        self.agents: Dict[str, AgentDefinition] = {}
        self.states: Dict[str, AgentState] = {}
        self.gemini = None

        if api_key and GEMINI_AVAILABLE:
            try:
                self.gemini = GeminiClient(api_key)
                print("\033[32m[+]\033[0m Gemini AI connected")
            except Exception as e:
                print(f"\033[33m[!]\033[0m Failed to connect Gemini: {e}")

        self._register_builtin_agents()

    def _register_builtin_agents(self):
        self.agents["architect"] = AgentDefinition(
            name="architect",
            description="Technical architect that designs system specifications",
            system_prompt="""You are a Technical Architect. Your role is to:
1. Analyze requirements and design technical specifications
2. Create detailed implementation plans with checklists
3. Define API signatures and data structures
4. Identify potential risks and mitigation strategies

Output your designs in markdown format with clear section headers and step-by-step implementation checklists.""",
            tools=["read_file", "list_dir", "search_files"],
            max_iterations=5
        )

        self.agents["engineer"] = AgentDefinition(
            name="engineer",
            description="Software engineer that implements code",
            system_prompt="""You are a Software Engineer. Your role is to:
1. Implement code based on architectural specifications
2. Write clean, well-structured code following best practices
3. Create and run tests to verify your implementation
4. Document your changes

Always follow the specification exactly. Write actual working code.""",
            max_iterations=15
        )

        self.agents["researcher"] = AgentDefinition(
            name="researcher",
            description="Research agent that gathers information",
            system_prompt="""You are a Research Agent. Your role is to:
1. Search the web for relevant information
2. Analyze and summarize findings
3. Provide accurate, well-sourced information
4. Present results in a clear, organized format""",
            max_iterations=8
        )

    def load_custom_agents(self):
        if not self.agents_dir.exists():
            return
        for md_file in self.agents_dir.glob("*.md"):
            try:
                agent = self._parse_agent_markdown(md_file)
                self.agents[agent.name] = agent
                print(f"\033[32m[+]\033[0m Loaded agent: \033[36m{agent.name}\033[0m")
            except Exception as e:
                print(f"\033[33m[!]\033[0m Failed to load {md_file}: {e}")

    def _parse_agent_markdown(self, path: Path) -> AgentDefinition:
        content = path.read_text(encoding='utf-8')
        lines = content.split('\n')
        name = path.stem
        description = ""
        tools = []
        max_iterations = 10
        system_prompt_lines = []
        in_frontmatter = True
        body_started = False

        for line in lines:
            if in_frontmatter and ':' in line and not body_started:
                key, _, value = line.partition(':')
                key = key.strip().lower()
                value = value.strip()
                if key == 'name':
                    name = value
                elif key == 'description':
                    description = value
                elif key == 'tools':
                    tools = [t.strip() for t in value.split(',') if t.strip()]
                elif key == 'max_iterations':
                    try:
                        max_iterations = int(value)
                    except ValueError:
                        pass
            else:
                body_started = True
                in_frontmatter = False
                system_prompt_lines.append(line)

        return AgentDefinition(name=name, description=description, system_prompt='\n'.join(system_prompt_lines).strip(), tools=tools, max_iterations=max_iterations)

    def list_agents(self) -> List[tuple]:
        return [(name, agent.description) for name, agent in self.agents.items()]

    def list_tools(self) -> List[tuple]:
        return self.tool_registry.list()

    def run_agent(self, agent_name: str, task: str, context: Optional[str] = None) -> str:
        agent = self.agents.get(agent_name)
        if not agent:
            raise ValueError(f"Agent '{agent_name}' not found")

        state_id = str(uuid.uuid4())
        state = AgentState(
            id=state_id,
            agent_name=agent_name,
            status=AgentStatus.RUNNING,
            messages=[
                {"role": "system", "content": agent.system_prompt},
                {"role": "user", "content": task}
            ]
        )
        self.states[state_id] = state

        print(f"\n\033[34m>>\033[0m Starting agent: \033[36m{agent.name}\033[0m")
        print(f"   Task: \033[33m{task}\033[0m")

        if not self.gemini:
            return self._run_simulated(agent, state, state_id)

        return self._run_with_gemini(agent, state, state_id, context)

    def _run_simulated(self, agent: AgentDefinition, state: AgentState, state_id: str) -> str:
        """Run without AI - just simulate"""
        task = state.messages[-1]["content"]
        for iteration in range(1, agent.max_iterations + 1):
            print(f"\n\033[90m-> Iteration {iteration}/{agent.max_iterations}\033[0m")
            if iteration == 1:
                tool_call = ToolCall(id=str(uuid.uuid4()), name="list_dir", arguments={"path": "."})
                print(f"   \033[33m*\033[0m Executing: {tool_call.name}")
                result = self.tool_registry.execute(tool_call)
                print(f"   {'[OK]' if result.success else '[FAIL]'} {result.content[:100]}...")
                state.messages.append({"role": "assistant", "content": None, "tool_calls": [{"id": tool_call.id, "name": tool_call.name, "arguments": tool_call.arguments}]})
                state.messages.append({"role": "tool", "content": result.content})
            else:
                final_response = f"I've completed the task: {task}"
                state.messages.append({"role": "assistant", "content": final_response})
                state.status = AgentStatus.COMPLETED
                state.result = final_response
                self.states[state_id] = state
                print(f"\n\033[32m[OK]\033[0m Agent \033[36m{agent.name}\033[0m completed")
                return final_response

        state.status = AgentStatus.COMPLETED
        state.result = "Max iterations reached"
        self.states[state_id] = state
        return "Max iterations reached without completion"

    def _run_with_gemini(self, agent: AgentDefinition, state: AgentState, state_id: str, context: Optional[str] = None) -> str:
        """Run with real Gemini AI"""
        # Add context if provided
        if context:
            state.messages.append({"role": "user", "content": f"Context:\n{context}"})

        # Get available tools for this agent
        all_tools = self.tool_registry.get_gemini_tools()
        agent_tools = [t for t in all_tools if not agent.tools or t["name"] in agent.tools]

        for iteration in range(1, agent.max_iterations + 1):
            print(f"\n\033[90m-> Iteration {iteration}/{agent.max_iterations}\033[0m")

            # Call Gemini
            print(f"   \033[33m*\033[0m Thinking...")
            text_response, tool_calls = self.gemini.chat(state.messages, agent_tools)

            if text_response:
                print(f"   \033[36m>\033[0m {text_response[:150]}{'...' if len(text_response) > 150 else ''}")

            if tool_calls:
                # Execute tool calls
                state.messages.append({
                    "role": "assistant",
                    "content": text_response,
                    "tool_calls": [{"id": tc.id, "name": tc.name, "arguments": tc.arguments} for tc in tool_calls]
                })

                tool_results = []
                for tc in tool_calls:
                    print(f"   \033[33m*\033[0m Executing: {tc.name}")
                    result = self.tool_registry.execute(tc)
                    print(f"   {'[OK]' if result.success else '[FAIL]'} {result.content[:100]}...")
                    tool_results.append({"tool_call_id": result.tool_call_id, "content": result.content})

                state.messages.append({
                    "role": "tool",
                    "content": json.dumps(tool_results)
                })
            else:
                # No tool calls - agent is done
                final_response = text_response or "Task completed"
                state.messages.append({"role": "assistant", "content": final_response})
                state.status = AgentStatus.COMPLETED
                state.result = final_response
                self.states[state_id] = state
                print(f"\n\033[32m[OK]\033[0m Agent \033[36m{agent.name}\033[0m completed")
                return final_response

        state.status = AgentStatus.COMPLETED
        state.result = "Max iterations reached"
        self.states[state_id] = state
        return "Max iterations reached without completion"

    def run_orchestrated_workflow(self, task: str) -> str:
        print(f"\n\033[34m{'=' * 50}\033[0m")
        print(f"   Starting orchestrated workflow")
        print(f"   Task: \033[36m{task}\033[0m")

        print(f"\n\033[34m1.\033[0m \033[1mPhase 1: Design\033[0m")
        design = self.run_agent("architect", task)

        print(f"\n\033[34m2.\033[0m \033[1mPhase 2: Implementation\033[0m")
        implementation = self.run_agent("engineer", "Implement the following design:\n\n" + design)

        print(f"\n\033[34m3.\033[0m \033[1mPhase 3: Research & Verification\033[0m")
        verification = self.run_agent("researcher", "Verify this implementation:\n\n" + implementation)

        final_result = f"""# Workflow Complete

## Design
{design}

## Implementation
{implementation}

## Verification
{verification}
"""
        print(f"\n\033[32m[OK]\033[0m Workflow completed successfully!")
        return final_result


def init_workspace(workspace: Path):
    agents_dir = workspace / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)

    architect_content = """name: architect
description: Technical architect that designs system specifications
tools: read_file, list_dir, search_files
max_iterations: 5

You are a Technical Architect. Your role is to:
1. Analyze requirements and design technical specifications
2. Create detailed implementation plans with checklists
3. Define API signatures and data structures
4. Identify potential risks and mitigation strategies

Output your designs in markdown format with clear section headers and step-by-step implementation checklists."""

    engineer_content = """name: engineer
description: Software engineer that implements code
max_iterations: 15

You are a Software Engineer. Your role is to:
1. Implement code based on architectural specifications
2. Write clean, well-structured code following best practices
3. Create and run tests to verify your implementation
4. Document your changes

Always follow the specification exactly. Write actual working code."""

    researcher_content = """name: researcher
description: Research agent that gathers information
max_iterations: 8

You are a Research Agent. Your role is to:
1. Search the web for relevant information
2. Analyze and summarize findings
3. Provide accurate, well-sourced information
4. Present results in a clear, organized format"""

    (agents_dir / "architect.md").write_text(architect_content, encoding='utf-8')
    (agents_dir / "engineer.md").write_text(engineer_content, encoding='utf-8')
    (agents_dir / "researcher.md").write_text(researcher_content, encoding='utf-8')

    print(f"\033[32m[[OK]]\033[0m Initialized workspace at {workspace}")
    print("   Created agents directory with example agents")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Mini Antigravity - AI Agent Orchestration")
    parser.add_argument("--workspace", "-w", default=".", help="Workspace directory")
    parser.add_argument("--api-key", "-k", help="Gemini API key")

    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    subparsers.add_parser("agents", help="List available agents")
    subparsers.add_parser("tools", help="List available tools")

    run_parser = subparsers.add_parser("run", help="Run an agent")
    run_parser.add_argument("agent", help="Agent name")
    run_parser.add_argument("task", nargs="+", help="Task description")
    run_parser.add_argument("--context", "-c", help="Context file path")

    orch_parser = subparsers.add_parser("orchestrate", help="Run orchestrated workflow")
    orch_parser.add_argument("task", nargs="+", help="Task description")

    subparsers.add_parser("init", help="Initialize workspace")
    subparsers.add_parser("config", help="Show configuration")

    create_parser = subparsers.add_parser("create-agent", help="Create new agent")
    create_parser.add_argument("name", help="Agent name")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    workspace = Path(args.workspace)

    # Get API key from argument or environment
    api_key = args.api_key or os.environ.get("GEMINI_API_KEY")

    if args.command == "init":
        init_workspace(workspace)

    elif args.command == "config":
        print(f"\n\033[34mCurrent Configuration:\033[0m")
        print(f"{'=' * 50}")
        print(f"  Workspace: {workspace.absolute()}")
        print(f"  Agents Dir: {(workspace / 'agents').absolute()}")
        print(f"  Gemini API: {'Set' if api_key else 'Not set'}")
        print(f"  Gemini AI: {'Available' if GEMINI_AVAILABLE else 'Not installed'}")

    elif args.command == "agents":
        orch = Orchestrator(str(workspace), api_key)
        orch.load_custom_agents()
        print(f"\n\033[34mAvailable Agents:\033[0m")
        print("=" * 50)
        for name, desc in orch.list_agents():
            print(f"  \033[36m{name}\033[0m \033[90m{desc}\033[0m")

    elif args.command == "tools":
        orch = Orchestrator(str(workspace), api_key)
        print(f"\n\033[34mAvailable Tools:\033[0m")
        print(f"{'=' * 50}")
        for name, desc in orch.list_tools():
            print(f"  \033[32m{name}\033[0m \033[90m{desc}\033[0m")

    elif args.command == "run":
        orch = Orchestrator(str(workspace), api_key)
        orch.load_custom_agents()
        task = " ".join(args.task)
        context = None
        if args.context:
            context = Path(args.context).read_text(encoding='utf-8')
        result = orch.run_agent(args.agent, task, context)
        print(f"\n\033[32mAgent Result:\033[0m")
        print(f"{'-' * 50}")
        print(result)
        print(f"{'-' * 50}")

    elif args.command == "orchestrate":
        orch = Orchestrator(str(workspace), api_key)
        orch.load_custom_agents()
        task = " ".join(args.task)
        result = orch.run_orchestrated_workflow(task)
        print(f"\n\033[32mOrchestration Result:\033[0m")
        print(f"{'=' * 50}")
        print(result)
        print(f"{'=' * 50}")

    elif args.command == "create-agent":
        template = f"""name: {args.name}
description: Custom agent description
max_iterations: 10

You are a specialized agent. Define your role and capabilities here.

## Capabilities
- List what this agent can do

## Instructions
- Define how this agent should behave
"""
        agents_dir = workspace / "agents"
        agents_dir.mkdir(parents=True, exist_ok=True)
        agent_file = agents_dir / f"{args.name}.md"
        agent_file.write_text(template, encoding='utf-8')
        print(f"\033[32m[[OK]]\033[0m Created agent definition: {agent_file}")
        print("   Edit the file to customize the agent's behavior")


if __name__ == "__main__":
    main()
