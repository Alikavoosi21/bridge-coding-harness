"""Read-only workspace preflight: what project is here, and what could verify it.

Nothing in this module executes a command, installs a package, downloads an
image, or writes into the project. It only reads `package.json` /
`pyproject.toml`, looks at lockfiles, and counts files the snapshot would copy.
The result is a *suggestion* the user can review and explicitly save as a
verification profile. A guessed command is never run, and saving a profile is
not the same as a successful first run.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tomllib
from pathlib import Path
from typing import Any

MAX_FILES = 50_000
MAX_BYTES = 500_000_000

# The same folders the snapshot leaves out. Preflight walks with these skipped so
# a huge `node_modules` cannot make setup slow or memory-hungry.
SKIPPED_FOLDERS = {
    ".git",
    ".hg",
    ".svn",
    ".harness",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".nox",
    ".next",
    ".turbo",
    ".gradle",
    "dist",
    "build",
    "out",
    "target",
    "coverage",
    ".idea",
    ".vscode",
}

_SECRET_NAMES = {
    ".env",
    ".env.local",
    ".env.production",
    ".npmrc",
    ".pypirc",
    "credentials",
    "id_rsa",
    "id_ed25519",
    "auth.json",
}
_SECRET_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".keystore")

NODE_LOCKFILES = {
    "package-lock.json": "npm",
    "npm-shrinkwrap.json": "npm",
    "pnpm-lock.yaml": "pnpm",
    "yarn.lock": "yarn",
    "bun.lockb": "bun",
    "bun.lock": "bun",
}
PYTHON_LOCKFILES = {
    "uv.lock": "uv",
    "poetry.lock": "poetry",
    "pdm.lock": "pdm",
    "Pipfile.lock": "pipenv",
}


def _is_secret(name: str) -> bool:
    lowered = name.lower()
    return lowered in _SECRET_NAMES or lowered.startswith(".env.") or lowered.endswith(_SECRET_SUFFIXES)


def _scan(root: Path) -> dict[str, Any]:
    """Count what a snapshot would copy, without following links or reading secrets."""
    files = 0
    size = 0
    symlinks = 0
    secrets = 0
    truncated = False
    stack: list[Path] = [root]
    while stack:
        folder = stack.pop()
        try:
            entries = list(os.scandir(folder))
        except OSError:
            continue
        for entry in entries:
            path = Path(entry.path)
            relative = path.relative_to(root)
            try:
                if entry.is_symlink():
                    symlinks += 1
                    continue
                if entry.is_dir(follow_symlinks=False):
                    if entry.name in SKIPPED_FOLDERS:
                        continue
                    stack.append(path)
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
                if _is_secret(entry.name):
                    secrets += 1
                    continue
                files += 1
                size += entry.stat(follow_symlinks=False).st_size
            except OSError:
                continue
            if files >= MAX_FILES or size >= MAX_BYTES:
                truncated = True
                break
        if truncated:
            break
    return {"file_count": files, "bytes": size, "symlinks": symlinks, "secret_files": secrets, "truncated": truncated, "skipped_folders": sorted(SKIPPED_FOLDERS)}


def _read_text(path: Path) -> str:
    """Read a manifest as UTF-8, tolerating the BOM many Windows editors add.

    A BOM is not a syntax error to every tool that reads `package.json`, so it
    must not turn a valid project into a "cannot be read" conflict here.
    """
    return path.read_text(encoding="utf-8-sig")


def _read_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    if path.is_symlink() or not path.is_file():
        return None, None
    try:
        data = json.loads(_read_text(path))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        return None, str(error)
    return data if isinstance(data, dict) else None, None


def _read_toml(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    if path.is_symlink() or not path.is_file():
        return None, None
    try:
        data = tomllib.loads(_read_text(path))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        return None, str(error)
    return data, None


def _command(command_id: str, label: str, command: str, source: str, *, required: bool = False, timeout: int = 120) -> dict[str, Any]:
    return {"id": command_id, "label": label, "command": command, "source": source, "required": required, "timeout": timeout}


def _node_commands(manager: str, script_names: set[str]) -> list[dict[str, Any]]:
    def run(script: str) -> str:
        if manager == "npm":
            return f"npm run {script}"
        if manager == "pnpm":
            return f"pnpm run {script}"
        if manager == "yarn":
            return f"yarn run {script}"
        return f"bun run {script}"

    commands: list[dict[str, Any]] = []
    test_script = "test" if "test" in script_names else ("test:unit" if "test:unit" in script_names else None)
    if test_script:
        command = "npm test" if manager == "npm" and test_script == "test" else run(test_script)
        commands.append(_command("test", "آزمون‌ها", command, f"package.json#scripts.{test_script}", required=True))
    typecheck = "typecheck" if "typecheck" in script_names else ("type-check" if "type-check" in script_names else None)
    if typecheck:
        commands.append(_command("typecheck", "بررسی نوع", run(typecheck), f"package.json#scripts.{typecheck}", required=True))
    if "lint" in script_names:
        commands.append(_command("lint", "لینت", run("lint"), "package.json#scripts.lint"))
    if "build" in script_names:
        commands.append(_command("build", "ساخت", run("build"), "package.json#scripts.build", timeout=600))
    return commands


def _node_install(manager: str | None, lockfiles: list[str]) -> dict[str, Any] | None:
    if manager is None:
        return None
    frozen = manager in {"pnpm", "yarn", "bun"} and bool(lockfiles)
    if manager == "npm":
        command = "npm ci" if "package-lock.json" in lockfiles or "npm-shrinkwrap.json" in lockfiles else "npm install"
    elif manager == "pnpm":
        command = "pnpm install" + (" --frozen-lockfile" if frozen else "")
    elif manager == "yarn":
        command = "yarn install" + (" --frozen-lockfile" if frozen else "")
    else:
        command = "bun install" + (" --frozen-lockfile" if frozen else "")
    return {"command": command, "source": "lockfile" if frozen else "package.json", "requires_consent": True}


def _package_manager(package_json: dict[str, Any] | None, lockfiles: list[str]) -> tuple[str | None, list[dict[str, Any]], str | None]:
    declared = None
    if package_json:
        raw = package_json.get("packageManager")
        if isinstance(raw, str) and raw.strip():
            declared = raw.split("@", 1)[0].strip()
    found = sorted({NODE_LOCKFILES[name] for name in lockfiles if name in NODE_LOCKFILES})
    conflicts: list[dict[str, Any]] = []
    note = None
    if len(found) > 1:
        conflicts.append({"code": "lockfile_conflict", "message": "More than one Node package manager lockfile is present.", "files": [name for name in lockfiles if name in NODE_LOCKFILES]})
    if declared and found and declared not in found:
        conflicts.append({"code": "package_manager_conflict", "message": f"package.json declares {declared}, but the lockfile belongs to {found[0]}.", "files": [name for name in lockfiles if name in NODE_LOCKFILES]})
    manager = declared or (found[0] if found else None)
    if manager is None and package_json is not None:
        manager = "npm"
        note = "No Node lockfile was found; npm is suggested, not confirmed."
    return manager, conflicts, note


def _requirement_name(item: Any) -> str:
    return re.split(r"[<>=!~\[; ]", str(item), maxsplit=1)[0].strip().lower()


def _python_commands(manager: str | None, data: dict[str, Any]) -> list[dict[str, Any]]:
    project = data.get("project") if isinstance(data.get("project"), dict) else {}
    poetry = data.get("tool", {}).get("poetry") if isinstance(data.get("tool"), dict) else None
    poetry = poetry if isinstance(poetry, dict) else {}
    groups = project.get("optional-dependencies") if isinstance(project.get("optional-dependencies"), dict) else {}
    dependencies = project.get("dependencies") if isinstance(project.get("dependencies"), list) else []
    dev_groups = data.get("dependency-groups") if isinstance(data.get("dependency-groups"), dict) else {}
    declared = {_requirement_name(item) for item in dependencies}
    for group in list(groups.values()) + [value for value in dev_groups.values() if isinstance(value, list)]:
        if isinstance(group, list):
            declared.update(_requirement_name(item) for item in group)
    declared.update(str(name).lower() for name in (poetry.get("dependencies") or {}))
    declared.update(str(name).lower() for name in (poetry.get("group", {}).get("dev", {}).get("dependencies", {}) if isinstance(poetry.get("group"), dict) else {}))

    tool = data.get("tool") if isinstance(data.get("tool"), dict) else {}
    prefix = {"uv": "uv run ", "poetry": "poetry run ", "pdm": "pdm run ", "pipenv": "pipenv run "}.get(manager or "", "python -m ")
    commands: list[dict[str, Any]] = []
    if "pytest" in declared or "pytest" in tool:
        commands.append(_command("test", "آزمون‌ها", f"{prefix}pytest", "pyproject.toml", required=True))
    if "ruff" in declared or "ruff" in tool:
        commands.append(_command("lint", "لینت", f"{prefix}ruff check .", "pyproject.toml"))
    if "mypy" in declared or "mypy" in tool:
        commands.append(_command("typecheck", "بررسی نوع", f"{prefix}mypy .", "pyproject.toml", required=True))
    return commands


def _python_install(manager: str | None) -> dict[str, Any] | None:
    if manager == "uv":
        return {"command": "uv sync --frozen", "source": "uv.lock", "requires_consent": True}
    if manager == "poetry":
        return {"command": "poetry install --no-root", "source": "poetry.lock", "requires_consent": True}
    if manager == "pdm":
        return {"command": "pdm install --frozen-lockfile", "source": "pdm.lock", "requires_consent": True}
    if manager == "pipenv":
        return {"command": "pipenv sync", "source": "Pipfile.lock", "requires_consent": True}
    return None


def analyze_workspace(root: Path) -> dict[str, Any]:
    """Inspect one folder. Read-only, bounded, and safe with broken config files."""
    root = root.resolve()
    scan = _scan(root)
    names: set[str] = set()
    if root.is_dir():
        with os.scandir(root) as entries:
            names = {entry.name for entry in entries}
    lockfiles = sorted(name for name in names if name in NODE_LOCKFILES or name in PYTHON_LOCKFILES)

    package_json, package_error = _read_json(root / "package.json")
    pyproject, pyproject_error = _read_toml(root / "pyproject.toml")

    conflicts: list[dict[str, Any]] = []
    notes: list[str] = []
    if package_error:
        conflicts.append({"code": "package_json_invalid", "message": f"package.json cannot be read: {package_error}", "files": ["package.json"]})
        package_json = None
    if pyproject_error:
        conflicts.append({"code": "pyproject_invalid", "message": f"pyproject.toml cannot be read: {pyproject_error}", "files": ["pyproject.toml"]})
        pyproject = None

    node_manager, node_conflicts, manager_note = _package_manager(package_json, lockfiles)
    conflicts.extend(node_conflicts)
    if manager_note:
        notes.append(manager_note)

    python_lockfiles = [name for name in lockfiles if name in PYTHON_LOCKFILES]
    python_managers = sorted({PYTHON_LOCKFILES[name] for name in python_lockfiles})
    if len(python_managers) > 1:
        conflicts.append({"code": "lockfile_conflict", "message": "More than one Python lockfile is present.", "files": python_lockfiles})
    python_manager = python_managers[0] if len(python_managers) == 1 else None

    commands: list[dict[str, Any]] = []
    if package_json is not None:
        scripts = package_json.get("scripts")
        script_names = set(scripts) if isinstance(scripts, dict) else set()
        commands.extend(_node_commands(node_manager or "npm", script_names))
    if pyproject is not None:
        commands.extend(_python_commands(python_manager, pyproject))

    # Conflicting lockfiles mean the manager and therefore the command prefix
    # are ambiguous. Do not suggest a profile that would run the wrong one.
    if conflicts:
        commands = []

    kind = "mixed" if package_json is not None and pyproject is not None else "node" if package_json is not None else "python" if pyproject is not None else "generic"
    if kind == "generic":
        manifests_exist = (root / "package.json").is_file() or (root / "pyproject.toml").is_file()
        if manifests_exist:
            # There is a manifest, but it could not be used; the conflict above
            # says why, so do not also claim nothing was found.
            notes.append("A project manifest exists but could not be used. Fix the conflict above before saving commands.")
        else:
            notes.append("No package.json or pyproject.toml was found. This is a generic folder; add a verification profile only after confirming its commands yourself.")
    if not commands and kind != "generic":
        notes.append("No supported test, lint, typecheck or build command was found in the project configuration.")

    install = None
    installs: list[dict[str, Any]] = []
    if not conflicts:
        node_install = _node_install(node_manager, lockfiles) if package_json is not None else None
        python_install = _python_install(python_manager) if pyproject is not None else None
        installs = [item for item in (node_install, python_install) if item]
        install = installs[0] if len(installs) == 1 else None
    if conflicts:
        notes.append("Conflicting configuration was found. No install or verification command was suggested until it is fixed.")

    profile = {
        "commands": commands,
        "install": install,
        "installs": installs,
        "notes": notes,
        "suggested": bool(commands),
        "requires_consent": bool(installs),
        "executed": False,
    }
    detected = {
        "package_json": package_json is not None,
        "pyproject": pyproject is not None,
        "node_lockfiles": [name for name in lockfiles if name in NODE_LOCKFILES],
        "python_lockfiles": python_lockfiles,
        "node_manager": node_manager,
        "python_manager": python_manager,
        "kind": kind,
    }
    return {
        "root_name": root.name,
        "scan": scan,
        "detected": detected,
        "profile": profile,
        "conflicts": conflicts,
        "read_only": True,
    }


def canonical_profile(commands: list[dict[str, Any]], analysis: dict[str, Any], install: dict[str, Any] | None = None) -> dict[str, Any]:
    """Keep only commands the preflight itself suggested, with server-owned flags.

    A client cannot invent a command, turn a command optional, or persist an
    install step that the analysis did not produce.
    """
    suggested = {item["command"]: item for item in analysis["profile"]["commands"]}
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in commands:
        command = str(item.get("command", "")).strip()
        canonical = suggested.get(command)
        if canonical is None or command in seen:
            raise ValueError(f"This command was not suggested for this project: {command}")
        seen.add(command)
        selected.append(dict(canonical))
    install_suggestion = analysis["profile"].get("installs") or []
    chosen_install = None
    if install is not None:
        # Accept only the exact install command the analysis suggested. An
        # install that was not suggested (or that conflicts removed) is refused,
        # not silently dropped, so the UI cannot report a save that did nothing.
        wanted = install.get("command") if isinstance(install, dict) else None
        for suggestion in install_suggestion:
            if suggestion.get("command") == wanted:
                chosen_install = dict(suggestion)
                break
        if chosen_install is None:
            raise ValueError("This install command was not suggested for this project.")
    payload = {"commands": selected, "install": chosen_install}
    payload["profile_hash"] = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    payload["analysis_hash"] = hashlib.sha256(json.dumps(analysis, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    return payload
