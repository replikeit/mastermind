# Generic MCP integration

Install Mastermind and index the repository. The client must launch a stdio
MCP server.

## Configure the server

For JSON `mcpServers` configuration, use the client's actual configuration path:

```bash
mastermind setup generic --scope project --config ./mcp.json
mastermind setup generic --scope project --config ./mcp.json --write
```

The first command previews a merge that preserves unrelated settings.
Equivalent manual configuration:

```json
{
  "mcpServers": {
    "mmcg": {
      "command": "mastermind",
      "args": ["serve"]
    }
  }
}
```

| Setting | Value |
|---|---|
| Working directory | Repository root |
| npm command | `mastermind` or `mmcg` |
| Cargo command | `mmcg` |
| Apply registration | Restart the client |

To select a specific index, place `--index` before `serve`:

```json
{
  "mcpServers": {
    "mmcg": {
      "command": "mastermind",
      "args": ["--index", "/absolute/path/project/.mastermind/mmcg.db", "serve"]
    }
  }
}
```

## Choose a tool

| Need | Start with |
|---|---|
| Role briefing | `mmcg_brief` |
| Task/agent effort decision | `mmcg_effort_route` |
| Name or concept | `mmcg_search`, `mmcg_concept` |
| Operation relevance | `mmcg_concept_prepare`, source reads, `mmcg_concept_finish` |
| Structure or change impact | `mmcg_map`, `mmcg_change_impact` |
| Project documentation | `mmcg_docs`, `mmcg_project_profile` |
| Combined context | `mmcg_context` |
| Task records | `mmcg_tasks`, `mmcg_history` |
| Granted personal preferences | `mmcg_profile` |

`tools/list` defines names and schemas.
For concept review, follow the returned `operation-roles-v3` rubric. Before
retrieval, freeze a query-only `request_contract` with the requested `operation`
and `constraints`: unique `id`, exact original-query `text`, and `kind` of
`input`, `state`, `scope` or `result`. Pass it to `mmcg_concept_prepare`.
Omitting it preserves the original query as the operation with an empty parsed
ledger; it does not waive any original constraint.

After inspecting source, every relevant judgment needs own citations, a role
and `witness`: own observable `behavior`, a typed `relation`, and one
`constraint_checks` entry per declared constraint. Each entry must be `matched`
with exact source-bound evidence. Contradictions make the candidate irrelevant;
uninspected constraints remain unknown, including for context. Retain those
limits if the ledger itself is incomplete or mistaken.

Choose roles from the candidate's own contribution. A concrete branch in a
module or entrypoint may implement or expose the operation through delegation.
A mandatory generic prerequisite contributes context unless its own behavior
performs a defining domain step or enforces a requested constraint. Context
still needs an inspected link to an existing requested operation satisfying
every explicit constraint. An omitted selector does not establish absent runtime
binding; rendered instructions do not perform the requested action. Nearby,
opposite or missing behavior is insufficient. Validation checks source bindings,
completeness and declared consistency, not semantic truth. Reprepare after a
role-contract change.
The [MCP reference](../reference/mmcg.md#mcp-tools) defines arguments and limits.
Graph queries may refresh the derived index. Scratchpad append is an additive
local write.

The effort tool returns a requested level and client argument arrays. Apply it
through a supported per-agent control before the next invocation; without that
control, keep the existing setting. It does not change this chat or launch a
model. See [effort routing](../guides/effort-routing.md).

## Enable personal context separately

```bash
mastermind miner access grant . --client my-client
```

| Requirement | Value |
|---|---|
| Read grant | This repository and client ID |
| Server environment | `MMCG_PROFILE_CLIENT=my-client` |
| Profile behavior | Advisory, live source checks |
| Access denied | Withhold personal context, no static `style.md` fallback |

See [Persona hooks](../guides/persona-hooks.md) for capture and review.

## Protocol and removal

| Protocol property | Value |
|---|---|
| Transport | JSON-RPC over stdin/stdout |
| MCP versions | 2025-11-25 and legacy 2024-11-05 |
| Catalog | Tools, no resources or prompts |

Source and message bounds: [protocol contract](../reference/mmcg.md#protocol-contract).

Remove the entry with the same setup path and `--remove`. Inspect the preview,
then add `--write`. Customized entries require `--force`. Forced file changes
save backups under `~/.mastermind/setup-backups/`.
