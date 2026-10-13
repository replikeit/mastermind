# Codex integration

Install portable skills and connect the local graph through user-scope MCP.

## Install

```bash
npm install -g @xcraftmind/mastermind
cd your-project
mastermind init --client codex
mastermind status
mastermind doctor --workflow --client codex
```

| Setting | Behavior |
|---|---|
| Fresh install | `core` skills |
| `mastermind update --workflow-only --client codex --profile frontend` | Select frontend skills. Other profiles are `security` and `full` |
| Update without `--profile` | Keep the selected profile |
| Agent runtime | Codex uses portable skills, not Claude-native subagent files |

First init indexes the project, enables profile delivery and configures task
mining in the current Codex agent. Restart Codex, trust the project and inspect
`/hooks`. On Windows use `--mining off`, since native hooks require Unix.
See [onboarding](../getting-started.md) for mode choices.

## Register MCP only

```bash
mastermind setup codex --scope user
mastermind setup codex --scope user --write
```

Setup previews first, uses `codex mcp` to apply, then checks the enabled `mmcg`
entry. Project-scope setup is unsupported. Restart Codex afterward.

## Use the task workflow

| Step | Owner |
|---|---|
| Approve spec and run preflight | Planner and controller |
| Implement and write executor report | Codex |
| Run declared checks and postflight | Runner and controller |
| Assess evidence and resolve history | Reviewer |
| Complete | Controller |

See [Workflow](../workflow.md) for commands.
`run-task --exec` and `review-task run` launch Claude Code, even when the
implementation was done in Codex.

## Route reasoning effort

The core workflow includes `mastermind-agent-handoff`. Planning, research and
delegated execution use it before each new agent:

1. Declare the receiving agent's duty, family, source scope and risk to `mmcg_effort_route` or `mastermind effort-route`.
2. Merge returned `codex_spawn_args` into the ordinary `spawn_agent` call; carry the bounded role/task packet into the fresh child.
3. Retain the decision and child ID, then check that child's own `turn_context.effort`.

See [effort routing](../guides/effort-routing.md) for inputs, launch commands,
fallbacks and evidence. Preserve the selected model and permissions. A
full-history fork retains parent effort and is recorded as `not_applied`.

### Resolve a competing dispatcher

TokenX assignment routing rejects explicit `reasoning_effort` fields. When it
is active, stop the handoff before spawn and let the user select one effort
authority.

To select Mastermind globally while keeping TokenX installed:

1. Open `/hooks` in the Codex CLI and locate the TokenX hooks.
2. Disable its non-managed `PreToolUse`, `SessionStart`, `SessionEnd` and `UserPromptSubmit` hooks. Preserve other hooks and their trust records.
3. Start a new session. Verify those hooks are disabled and no TokenX assignment instruction is active before applying a route.

| Configuration | Verification or recovery |
|---|---|
| Non-managed TokenX hooks | Must be disabled in the native hook inventory |
| Managed hook | Cannot be disabled in user controls; resolve with its administrator |
| Local `plugins.enabled = false` | Remote registries can retain enabled catalog state; the written setting alone is insufficient |
| Restore TokenX routing | Select it as effort authority and re-enable only its hooks, preserving previous trust hashes |

See [Codex hook controls](https://developers.openai.com/codex/hooks#review-and-trust-hooks).

## Verify or remove

```bash
mastermind doctor
mastermind setup codex --scope user --remove
mastermind setup codex --scope user --remove --write
```

| Condition | Behavior |
|---|---|
| Matching enabled entry | No change |
| Customized or disabled entry | Requires `--force` and `--write` |
| Native registration changed | Setup checks the resulting entry |
| Doctor | Reads `[mcp_servers.mmcg]` in `~/.codex/config.toml` |

Registration checks and server handshake are distinct.
Init configures capture and profile read grants for this client and project.
[Persona hooks](../guides/persona-hooks.md) covers source inspection and review.
