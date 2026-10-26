"""Product action policy, using workspace rules without granting from model text.

This module computes a decision only. Approval persistence and runtime dispatch
must bind it to the existing operation_id; a fingerprint is never that identity.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Literal

from .permissions import Access, Policy, READ_TOOLS, WRITE_TOOLS, normalize, target_path


@dataclass(frozen=True)
class ActionContext:
    tool: str
    args: dict[str, Any]
    cwd: str
    shell: str
    runtime: str
    environment_profile: str
    plan_revision: int
    script: bytes = b""

    def fingerprint(self) -> str:
        # Preserve argument values/order and script bytes. Do not case-fold paths:
        # a Linux sandbox can distinguish files that the Windows host cannot.
        payload = {
            'tool': self.tool, 'args': self.args, 'cwd': self.cwd,
            'shell': self.shell, 'runtime': self.runtime,
            'environment_profile': self.environment_profile,
            'plan_revision': self.plan_revision,
            'script_sha256': hashlib.sha256(self.script).hexdigest(),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')
        return hashlib.sha256(encoded).hexdigest()


def action_access(
    rules: Policy,
    action: ActionContext,
    *,
    mode: Literal['ask', 'grant', 'auto'],
    read_only: bool,
    plan_approved: bool,
    runtime_available: bool,
    grant_matches: bool = False,
    network: bool = False,
    installation: bool = False,
    first_verifier: bool = False,
    human_apply: bool = False,
    check_change: bool = False,
    skill_script: bool = False,
) -> Access:
    """Apply hard boundaries before any task-scoped consent.

    Flags describing an operation come from trusted tool/runtime adapters, never
    from prompt fields. `grant_matches` must be resolved from durable storage by
    task, fingerprint, revision and expiry, not accepted from the renderer.
    """
    if mode not in {'ask', 'grant', 'auto'}:
        raise ValueError('Unknown access mode')
    # Read raw rules: auto mode must not turn a workspace deny into approval.
    base = Policy(mode='ask', file_rules=rules.file_rules, tool_rules=rules.tool_rules).decide(action.tool, action.args)
    if rules.tool_rules.get(action.tool)=='deny':
        return 'deny'
    if base=='allow' and rules.tool_rules.get(action.tool)=='ask':
        base='ask'
    if base == 'deny':
        return 'deny'
    mutating = action.tool in WRITE_TOOLS or action.tool == 'execute' or installation or human_apply
    if read_only and (mutating or network or base == 'ask'):
        return 'deny'
    if mutating and (not plan_approved or not runtime_available):
        return 'deny'
    # Unknown connector tools never inherit implicit allow from a missing rule.
    known_read = action.tool in READ_TOOLS or action.tool in {'write_todos', 'calculate'}
    if known_read and base == 'allow' and not (network or first_verifier):
        return 'allow'
    if human_apply or network or installation or first_verifier or check_change or skill_script:
        return 'ask'
    # The rules file remains explicitly human-controlled in every mode.
    if action.tool in WRITE_TOOLS and target_path(action.tool, action.args).casefold() == normalize('/.harness/rules.yaml'):
        return 'ask'
    if mode == 'auto' and mutating:
        return 'allow'
    if mode == 'grant' and grant_matches:
        return 'allow'
    return 'ask'
