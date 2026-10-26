# Security and privacy

Bridge Coding Harness is a local, single-user Windows coding app. It does not include a shared provider key, cloud account, or telemetry service.

## Credentials and repository contents

- Enter provider keys in the app's model settings. Windows Credential Manager stores them under the independent `bridge-coding-harness` service; the API does not return stored keys.
- The Electron shell generates a fresh token for the loopback engine at each launch. The engine binds to `127.0.0.1` and checks authentication, Host and Origin.
- Do not commit `.env`, provider keys, runtime settings, databases, checkpoints, traces, diagnostics or user projects. `.env.example` is credential-free and documents optional developer settings; `.env` is not automatically loaded.
- Prompts and file contents that the agent reads are sent to the model endpoint you choose. Use a provider you trust with the project. Avoid committing or attaching secrets.

## Execution and human control

Commands run in Docker on a separate project working copy, not through a host-shell fallback. The sandbox uses an unprivileged user, a read-only root filesystem, bounded resources, no Docker socket, and no network by default. Network access and package installation require applicable user consent. These controls reduce exposure; Docker and the host OS still need normal security maintenance.

A versioned plan gates mutation. Sensitive actions use exact, durable human approvals; task-scoped grants are revoked when their scope ends or changes. The user reviews and can edit changes before applying them to original files. Stop and recovery preserve uncertain outcomes rather than silently replaying unknown operations.

Skills and repository files are untrusted instructions/data. Enabling a skill does not grant execution permission. Imported scripts use the same sandbox and approval boundary. No prompt can guarantee immunity to prompt injection; review sensitive actions and untrusted code.

## Previews

HTML previews serve a captured copy on a separate loopback port with an unguessable path. Internal previews and separate preview windows have no desktop preload or Node access, and restrict requests to the preview origin. Live web output requires explicit network consent, publishes only on `127.0.0.1`, and is time-limited. External browsers use their normal permissions. Preview sessions do not automatically resume after restart.

## Limits

- Task state and working copies are not encrypted at rest; protect your Windows account and local data directory.
- A passed check covers only its recorded snapshot, commands and runtime, not every possible defect.
- Two unsuccessful automatic repairs require a human decision to extend or stop; the counter survives reconnects.
- Windows installers are currently unsigned. Download from this repository's Releases and compare the published SHA-256.
- Standalone `python -m server --dev` is for local development only; do not expose it to the network.

## Reporting

For a security issue, use GitHub's private vulnerability reporting if enabled. Do not post credentials, private project files or a usable exploit against another user's machine in public issues.
