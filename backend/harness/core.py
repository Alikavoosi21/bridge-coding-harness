"""The core: one function that assembles the agent.

Everything the harness can do is decided here, in one call to deepagents'
`create_deep_agent`. Each argument comes from the module that owns that
concern, so this file reads as the table of contents of the whole harness:

    model         models.py        which model answers (the user's choice per task)
    system_prompt prompts.py       the fixed instructions
    tools         tools/           the few custom tools
    backend       sandbox.py       the workspace files and the guarded shell
    interrupt_on  permissions.py   allow / ask / deny from rules.yaml; "ask" pauses for a human
    skills        skills.py        how-to knowledge, loaded on demand
    memory        memory.py        what is remembered between tasks
    subagents     subagents.py     other agent profiles, for independent work
    checkpointer  durability.py    saved state: pause, resume, survive restarts
    middleware    hooks/ + durability.py   planning, retries, limits, audit, verification

What deepagents adds by itself, with no code here: the agent loop, the file
tools, moving large tool results into files, summarising a long conversation,
and prompt caching for providers that support it.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from deepagents import RubricMiddleware, create_deep_agent
from langchain.agents.middleware import TodoListMiddleware
from langchain_core.tools import BaseTool
from langgraph.checkpoint.base import BaseCheckpointSaver

from .config import RunRequest
from .durability import build_resilience
from .hooks import build_hooks, build_subagent_hooks
from .memory import memory_sources
from .models import build_chat_model
from .permissions import WRITE_TOOLS, build_policy, load_rules
from .prompts import PLANNING_PROMPT, PLANNING_TOOL_DESCRIPTION, SYSTEM_PROMPT
from .sandbox import build_backend, can_execute
from .skills import skill_sources
from .subagents import build_subagents, list_agents
from .tools import build_tools
from .tracker import RunTracker
from .workspace import Workspace


def available_tools(workspace: Workspace, backend: Any, extra_tools: Sequence[BaseTool] = ()) -> dict[str, BaseTool]:
    """The custom tools this backend can honour.

    Without a real sandbox the write tools are not registered at all. They
    write straight to the workspace (Word/Excel/archives), so leaving them in
    while only the backend is read-only would be a hole, not a safeguard.
    """
    tools = build_tools(workspace, allow_writes=can_execute(backend)) | {tool.name: tool for tool in extra_tools}
    if not can_execute(backend):
        return {name: tool for name, tool in tools.items() if name not in WRITE_TOOLS}
    return tools


def build_agent(workspace: Workspace, request: RunRequest, tracker: RunTracker, checkpointer: BaseCheckpointSaver, extra_tools: Sequence[BaseTool] = (), plan_gate: Any = None) -> Any:
    """Assemble the agent for one run. Cheap enough to do on every run, so settings never go stale."""
    model = build_chat_model(request.model)
    if plan_gate is not None and getattr(model,'product_demo',False):
        from .demo_model import task_demo_model
        model=task_demo_model(request.phase)
    fallback = build_chat_model(request.fallback_model) if request.fallback_model else None
    policy = build_policy(load_rules(workspace.rules_file), request.mode)

    backend = build_backend(workspace, allow_shell=policy.allow_shell, on_stop=tracker.on_stop)
    data_workspace=workspace
    runtime_id='read-only'
    gateway = None
    if plan_gate is not None:
        from .gateway import ToolGateway
        from .sandbox import can_execute
        from .task_runtime import open_task_runtime
        assembly=open_task_runtime(workspace,plan_gate.store,plan_gate.task_id,read_only=request.mode=='read_only',max_seconds=request.limits.max_seconds)
        tracker.on_finish.append(assembly.close)
        backend,data_workspace,runtime_id=assembly.backend,assembly.workspace,assembly.runtime_id
        target=getattr(backend,'default',backend)
        if can_execute(backend):tracker.on_stop.append(target.kill_all)
        gateway = ToolGateway(plan_gate.store, plan_gate.task_id, workspace.rules_file,
            runtime_available=can_execute(backend), runtime_id=runtime_id, read_only=request.mode=='read_only',backend=target)
    # Tools the embedding app registered (connectors, MCP) join the built-in ones and obey the same rules.
    all_tools = available_tools(data_workspace, backend, extra_tools)
    profiles = list_agents(workspace)
    lead = next((profile for profile in profiles if profile.id == request.agent_id), None)
    # The lead uses its own tool list; without a lead the coordinator may use every tool.
    tool_names = lead.tools if lead else list(all_tools)
    tools = [all_tools[name] for name in tool_names if name in all_tools]
    skills = skill_sources(workspace)

    middleware = [
        # planning: the `write_todos` tool and the plan in state, with our own wording of when to plan
        TodoListMiddleware(system_prompt=PLANNING_PROMPT, tool_description=PLANNING_TOOL_DESCRIPTION),
        *build_resilience(fallback),  # retry and fallback
        *build_hooks(tracker, policy, data_workspace, plan_gate, gateway, planning=request.phase=='plan'),  # limits, cost, plan gate, permission, breaker, audit, file freshness, verification
    ]
    if request.rubric:
        middleware.append(RubricMiddleware(model=model))  # grade the answer before finishing

    local_note='\nExecution runs locally on Windows with cmd.exe in this task copy. File tools use virtual / paths. Use Windows-compatible commands; no bash, sh, /bin or Unix-only shell syntax. Commands have the user Windows permissions and networking; do not describe this as an OS sandbox. Use python and node/npm supplied by Bridge. For self-contained UI requests prefer index.html with inline CSS/JS so Preview works immediately without package installation. Write requested files using write_file/edit_file; do not ask the user to copy code elsewhere. Web servers must listen on HOST (default 127.0.0.1) and PORT from the environment; do not hardcode a port.\n' if gateway and getattr(getattr(getattr(backend,'default',backend),'_runtime',None),'local',False) else ''
    return create_deep_agent(
        name="harness",
        model=model,
        system_prompt=SYSTEM_PROMPT + local_note + (f"\n## Your role in this task\n{lead.prompt}" if lead else ""),
        tools=tools,
        backend=backend,
        interrupt_on=gateway.interrupt_on(set(all_tools) | {'read_file','write_file','edit_file','ls','glob','grep','execute','task','write_todos'}) if gateway else policy.interrupt_on(),
        skills=skills,
        memory=memory_sources(workspace),
        subagents=build_subagents(profiles, all_tools, skills, lead_id=lead.id if lead else None, hooks_for=lambda name: build_subagent_hooks(tracker, policy, data_workspace, name, plan_gate, gateway)),
        checkpointer=checkpointer,
        middleware=middleware,
    )
