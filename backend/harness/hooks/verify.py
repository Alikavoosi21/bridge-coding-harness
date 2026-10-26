"""Verification: do not let the agent say "done" when it is not.

Three layers, from cheapest to most thorough:

- Guides   : instructions that prevent mistakes up front (the system prompt and skills).
- Sensors  : small deterministic checks in code, below. No model involved.
- Stop hook: this middleware. When the agent is about to give its final answer,
             the sensors run; if one objects, the agent is sent back with the
             objection, a limited number of times.

For judging the *quality* of an answer against written criteria there is also
deepagents' `RubricMiddleware`, which `core.py` adds when a run has a rubric.

Numbers are a fourth, separate guarantee: they come from the calculation tools
(`tools/`), never from the model's own arithmetic.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware, hook_config
from langchain_core.messages import AIMessage, HumanMessage

from ..tracker import RunTracker

# A sensor looks at the run's state and returns a complaint, or None when satisfied.
Sensor = Callable[[dict[str, Any]], str | None]


def unfinished_plan(state: dict[str, Any]) -> str | None:
    open_steps = [todo["content"] for todo in state.get("todos") or [] if todo.get("status") != "completed"]
    if open_steps:
        return "The plan still has unfinished steps: " + "; ".join(open_steps) + ". Finish them, or mark them completed if they are done."
    return None


def empty_answer(state: dict[str, Any]) -> str | None:
    last = state["messages"][-1]
    text = last.content if isinstance(last.content, str) else "".join(block.get("text", "") for block in last.content if isinstance(block, dict))
    return None if text.strip() else "You stopped without telling the user anything. Give a short answer."


DEFAULT_SENSORS: list[Sensor] = [unfinished_plan, empty_answer]


class VerifyHook(AgentMiddleware):
    def __init__(self, tracker: RunTracker, sensors: list[Sensor] | None = None, max_rounds: int = 2, gateway=None) -> None:
        self.tracker = tracker
        self.sensors = DEFAULT_SENSORS if sensors is None else sensors
        self.max_rounds = max_rounds
        self.rounds = 0
        self.gateway=gateway

    @hook_config(can_jump_to=["model"])
    def after_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:  # noqa: ARG002
        last = state["messages"][-1]
        finishing = isinstance(last, AIMessage) and not last.tool_calls
        # A run that is being stopped by a limit must be allowed to stop.
        if not finishing or self.tracker.stop_reason or getattr(self.tracker,'stop_requested',False):
            return None

        if self.gateway is not None:
            if getattr(self.gateway,'permission_blocked',False):
                self.tracker.stop_reason='permission_required'
                return None
            # Missing authority is a human decision, never a code repair.
            plan=self.gateway.store.plan(self.gateway.task_id)
            if plan and plan['approved_revision']!=plan['revision']:
                return None

        if self.gateway is not None and not self.gateway.read_only:
            response=self._product_quality(last)
            if response is not None:return response
            if self.tracker.stop_reason:return None
        if self.rounds >= self.max_rounds:return None

        complaints = [complaint for sensor in self.sensors if not (self.gateway is not None and self.gateway.read_only and sensor is unfinished_plan) and (complaint := sensor(state))]
        if not complaints:
            return None

        self.rounds += 1
        self.tracker.emit("verification", round=self.rounds, problems=complaints)
        note = "<verification>\n" + "\n".join(f"- {c}" for c in complaints) + "\n</verification>"
        return {"jump_to": "model", "messages": [HumanMessage(content=note)]}

    def _product_quality(self,last):
        from ..verification.observe import current_quality
        from ..verification.budget import RepairBudget
        from server.errors import ApiError
        gateway=self.gateway
        quality=current_quality(gateway.store,gateway.task_id,gateway.script_root,gateway.runtime_id)
        if quality is None or quality['quality_status']=='verified_snapshot':return None
        if quality['quality_status']=='failed':
            budgets=RepairBudget(gateway.store);budget=budgets.read(gateway.task_id)
            run_id=gateway.store.latest_run_id(gateway.task_id) or 'run'
            identity=last.id or f'{run_id}:{self.tracker.model_calls}'
            key=f'final:{identity}'
            reason='Required current check failed.'
            replay=budgets.replay_claim(gateway.task_id,key=key,reason=reason)
            if (replay and budget['total_attempts']>replay['total_attempts']) or (not replay and budget['total_attempts']>=budget['allowed']):
                self.tracker.stop_reason='quality_decision'
                return None
            gateway.store.set_task_status(gateway.task_id,'verifying',reason='required_check_failed')
            try:
                if not replay:budgets.claim(gateway.task_id,key=key,expected_revision=budget['revision'],reason=reason)
            except ApiError as error:
                if error.code not in {'budget_exhausted','budget_revision_mismatch'}:raise
                self.tracker.stop_reason='quality_decision'
                return None
            gateway.store.set_task_status(gateway.task_id,'repairing',reason='repair_started')
            note='Required checks failed. Repair the approved task, then rerun all required checks. Do not delete tests or weaken the approved checks.'
        else:
            # Missing/stale evidence requests verification, not another repair.
            if self.rounds>=self.max_rounds:
                self.tracker.stop_reason='quality_decision'
                return None
            self.rounds+=1
            note='Completion is not verified. Run all configured checks on the current files using execute; obtain required human consent. Commands: '+str(quality['commands'])
        return {'jump_to':'model','messages':[HumanMessage(content='<verification>\n'+note+'\n</verification>')]}
