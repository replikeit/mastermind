# Task and agent effort routing

Choose effort once before a new agent invocation. The Rust policy is shared by
CLI and MCP, with no model call or index requirement. It uses declared duties
and scope, rather than a keyword guess or a hidden difficulty score.

## Choose a route

| Context | Automatic choice |
|---|---|
| Researcher, `callees_trace`, `source_read_reuse` or `task_phase_trace`; all conditions below met | `low` pilot |
| Unknown/other duty or family, incomplete context, high/unknown risk | `high` |
| Explicit human `user_effort` for this invocation | The requested override |

The low route requires source-only research, a bounded source scope, stable
inputs, a lexical repo-map with a 1600-byte budget and the frozen
direct-read/uncovered-range instruction, and inspected low risk.
Execution, review, security, function-removal proofs and normalization-boundary
questions use high. A phase trace explains the saved/current input contract
under stated assumptions; changing or approving workflow state is a different
duty. Unknown roles and families are accepted and conservatively retain high.

The controller owns these declarations. They are not verified by the router.
Keep current source evidence, precise citations and unresolved obligations.
When a research request grows into a different duty, end the low handoff and
carry its facts and gaps into the new role instead of repeating every read.

## Request and apply

The model, tool permissions and budgets stay under the existing controller.
For an eligible read-only source-reuse request, create `route.json`:

```json
{
  "agent": "researcher",
  "task_family": "source_read_reuse",
  "read_only": true,
  "bounded_scope": true,
  "stable_inputs": true,
  "lexical_repo_map": true,
  "risk": "low"
}
```

```bash
mastermind effort-route --request route.json
```

Or send the same object as arguments to `mmcg_effort_route`. Omitted booleans
are false; omitted risk is unknown. `user_effort`, when explicitly selected by
the human for this invocation, accepts low, medium, high, xhigh or max.
Unknown fields, invalid types and unrecognized effort/risk values are errors.
CLI requests are limited to 16 KiB; agent and family names to 80 UTF-8 bytes.

The response includes `requested_effort`, a reason and fixed argument arrays:

| Client | Low invocation override |
|---|---|
| Codex CLI | `-c 'model_reasoning_effort="low"'` |
| Claude Code CLI | `--effort low` |
| Another host | Map `requested_effort` to its supported per-agent control |

The controller must apply those arguments/settings to the next invocation and
retain the decision alongside its runtime record. Do not join an argument array
into an executable shell string. Keep the selected model and authentication;
the router does not grant permissions or change its caller's configuration.
Its response has `applied: false` because selecting an effort is distinct from
submitting that setting or observing the served effort. Reject unsupported
settings at the host boundary; do not silently pretend that routing took effect.
If no per-invocation control exists, retain the current setting and record the
limitation. Global client configuration remains a user choice.

## Native client launch

The CLI can select and submit the override in one step. Execution requires a
request file so the native client keeps stdin for its prompt. Arguments after
`--` are passed directly, without shell expansion:

```bash
mastermind effort-route --request route.json --exec codex -- exec --sandbox read-only - < task.txt
mastermind effort-route --request route.json --exec claude -- --print --tools Read,Grep,Glob < task.txt
```

Keep the model, tools, source scope and budgets of the invocation you intended
within those native arguments/configuration. The launcher adds only the effort
arguments. It resolves the named client from PATH and inherits its configuration,
authentication and working directory. stdout is the client's output; stderr
includes a JSON route record after spawn, with `override_submitted: true` and
`served_effort: null`. Child exit codes 0–255 are preserved; signal exits and wider codes return 1.
Capture stderr alongside the runtime result. Selection, submission and observed
provider behavior remain separate.

Put explicit effort in `user_effort`. Conflicting native effort flags or a
visible conflicting `CLAUDE_CODE_EFFORT_LEVEL` stop before spawn. Invalid inputs,
a missing client or a nonzero client exit fail the command; there is no retry
with a silently different effort. The launcher's flags affect the main native
session. In Claude, agent/frontmatter effort and settings/environment precedence
can override it; do not treat `--exec claude -- --agent ...` as proof of the
agent's effort. See [Claude effort precedence](https://code.claude.com/docs/en/model-config#adjust-effort-level),
[environment precedence](https://code.claude.com/docs/en/env-vars#precedence)
and [Codex configuration](https://developers.openai.com/codex/config-reference).

## In-session agents and other hosts

For a non-fork Claude subagent on Claude Code 2.1.292 or later, the controller
passes `requested_effort` as the Agent tool's per-invocation `effort` value. It
overrides that agent's definition, unless `CLAUDE_CODE_EFFORT_LEVEL` overrides
both. Older clients and forks keep their defaults when no supported control
exists. Do not force one environment effort across unrelated agent duties.
See [Claude subagent effort](https://code.claude.com/docs/en/sub-agents#choose-an-effort-level).

For Codex subagents or another SDK/client, apply the same decision through the
host's supported per-agent field and retain the request in its runtime record.
The MCP tool stays read-only and cannot launch or reconfigure the host. If the
host exposes no control, record `not_applied` and preserve its existing setting.

## Evidence and rollback

This is a selective pilot, not a general difficulty classifier. The route's
`quality_qualified: false` separates a configuration decision from measured
answer quality. Before expanding the allowed families or applying low to a new
model, use matched task inputs and tools, preserve failed/unknown outcomes, and
review complete answers independently. Deterministic routing and transport tests
do not establish semantic quality.

Disable automatic low by removing the controller's routing step, or retain
high with an explicit per-invocation override. Preserve existing results and
failure records. Changing a router cannot repair or relabel historical grades.
