"""The workspace: one folder on disk that holds everything.

Like a repository, a workspace *is* its folder. The user's documents live at the
top; everything the harness keeps for itself lives under `.harness/`:

    <workspace>/
      ...user files (Word, Excel, images, reports)
      .harness/
        agents/        one YAML per agent profile
        skills/        one folder per skill, each with a SKILL.md
        memory/        AGENTS.md (always loaded) and other notes
        rules.yaml     permissions: allow / ask / deny
        runs/          one folder per task: trace, plan, summary
        artifacts/     large tool results moved out of the conversation
        state.db       checkpoints (lets a task resume after a restart)

Agents see the workspace as a virtual root: `/` is the workspace folder and
they cannot reach above it through the file tools.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

HARNESS_DIR = ".harness"

# A task's id is also its folder name under `runs/`, so it may only be a plain name.
THREAD_ID = r"^[A-Za-z0-9_-]{1,64}$"

DEFAULT_RULES = """\
# What agents may do in this workspace.
# access: allow (just do it) | ask (pause for approval) | deny (never)
# The first matching rule wins.
files:
  - paths: ["/.harness/runs/**", "/.harness/artifacts/**"]
    operations: [write]
    access: allow
  - paths: ["/.harness/**"]
    operations: [write]
    access: ask
  - paths: ["/**"]
    operations: [write]
    access: ask
tools:
  execute: ask
  browse_page: ask
"""

_DEFAULT_MEMORY = """\
# Project memory

- Preserve unrelated user changes.
- Record approved project commands and conventions here; verify they remain current.
"""

_DEFAULT_AGENT = """\
name: code-reviewer
title: بازبین کد
description: Reviews source code and test results for concrete defects.
prompt: |
  Review the requested source and actual test receipts. Cite paths and concrete
  defects, preserve scope, and never claim checks passed without execution.
tools: []
"""

_DEFAULT_SKILL = """\
---
name: coding-checks
description: Inspect a coding project, reproduce a failure and verify a focused fix.
---

# Coding checks

1. Read repository instructions and manifests; identify the real test scripts.
2. Present the plan and required commands for human approval.
3. Run approved baseline checks in the isolated runtime; retain their receipts.
4. Read the relevant source before editing. Make a focused change.
5. Run the approved checks again, inspect failures and correct the cause.
6. Respect the two-repair budget; request a decision before extending it.
7. Report changed paths and actual results. Leave applying changes to the user.
"""


@dataclass(frozen=True)
class Workspace:
    root: Path

    @classmethod
    def at(cls, path: str | Path) -> "Workspace":
        return cls(Path(path).expanduser().resolve())

    # ── locations ──
    @property
    def harness(self) -> Path:
        return self.root / HARNESS_DIR

    @property
    def agents_dir(self) -> Path:
        return self.harness / "agents"

    @property
    def skills_dir(self) -> Path:
        return self.harness / "skills"

    @property
    def memory_dir(self) -> Path:
        return self.harness / "memory"

    @property
    def rules_file(self) -> Path:
        return self.harness / "rules.yaml"

    @property
    def runs_dir(self) -> Path:
        return self.harness / "runs"

    @property
    def state_db(self) -> Path:
        return self.harness / "state.db"

    def run_dir(self, thread_id: str) -> Path:
        if not re.fullmatch(THREAD_ID, thread_id):
            raise ValueError(f"not a valid task id: {thread_id!r}")
        return self.runs_dir / thread_id

    def virtual(self, path: Path) -> str:
        """The path an agent uses for a real file: `/` is the workspace root."""
        return "/" + path.resolve().relative_to(self.root).as_posix()

    def contains(self, path: Path) -> bool:
        try:
            path.resolve().relative_to(self.root)
        except ValueError:
            return False
        return True

    # ── creation ──
    def scaffold(self) -> "Workspace":
        """Create `.harness/` with working defaults. Existing files are never overwritten."""
        for folder in (self.agents_dir, self.skills_dir, self.memory_dir, self.runs_dir, self.harness / "artifacts"):
            folder.mkdir(parents=True, exist_ok=True)
        defaults = {
            self.rules_file: DEFAULT_RULES,
            self.memory_dir / "AGENTS.md": _DEFAULT_MEMORY,
            self.agents_dir / "code-reviewer.yaml": _DEFAULT_AGENT,
            self.skills_dir / "coding-checks" / "SKILL.md": _DEFAULT_SKILL,
        }
        for file, content in defaults.items():
            if not file.exists():
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_text(content, encoding="utf-8")
        return self
