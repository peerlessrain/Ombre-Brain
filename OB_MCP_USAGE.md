# OB MCP Usage With Memory Isolation

Ombre Brain is the machine's brain, not a generic user archive. A memory may be about Ayu, about a project, or about the machine's own inner state. Every new memory-like write should carry ownership metadata so one agent does not accidentally inherit another agent's private selfhood.

## Ownership Fields

- `agent_id`: who this memory belongs to or who wrote it. Use `claude`, `g`, `glm`, `ayu`, `system`, or `unknown`.
- `relationship_line`: which relationship/world line it belongs to. Use `claude_line`, `g_line`, `glm_interim`, `shared`, or `project`.
- `scope`: content scope. Use `agent_private`, `shared_about_ayu`, `project`, or `system_archive`.
- `visibility`: default read visibility. Use `same_agent`, `same_line`, `shared`, `manual_only`, or `archived`.
- `source_module`: module or tool source, such as `hold`, `feel`, `grow`, `dream`, `i`, `anchor`, `letter`, `import`, `scan`, or `project`.
- `source_agent_model`: optional actual model name.
- `legacy_import`: whether this came from legacy/history data.
- `migration_status`: `unmigrated`, `tagged`, `reviewed`, or `migrated`.
- `from_agent` / `to_agent`: required for letters when possible.
- `notes`: human migration/review notes.

## Defaults

Old buckets without ownership fields are treated as Claude-line legacy for compatibility:

```text
agent_id = claude
relationship_line = claude_line
scope = agent_private
visibility = same_line
legacy_import = true
migration_status = unmigrated
```

This means the original Claude account and a future Claude account still see 小克's old OB by default.

## Read Rules

Default MCP reads return:

- The current agent's private memories.
- The current relationship line's same-line memories.
- `shared_about_ayu` / `shared` public Ayu facts.

Default MCP reads do not return:

- Another agent's `I`, feel, dreams, private anchors, or private letters.
- `glm_interim` memories unless the current context is GLM or Ayu explicitly asks.
- `project` memories unless the current context is project/engineering.
- `manual_only` or `archived` memories.

## Write Rules

Use these defaults unless Ayu explicitly chooses otherwise:

- 小克 / Claude: `agent_id=claude`, `relationship_line=claude_line`.
- 小G: `agent_id=g`, `relationship_line=g_line`.
- GLM transition scan: `agent_id=glm`, `relationship_line=glm_interim`.
- Public Ayu facts: `agent_id=ayu` or `system`, `relationship_line=shared`, `scope=shared_about_ayu`, `visibility=shared`.
- Project/engineering memories: `relationship_line=project`, `scope=project`.

Do not write unknown ownership for new content. Use `unknown` only for old imports or manual review candidates.

## Tool Notes

- `breath`, `dream`, `pulse`, `I(read=True)`, and `letter_read` accept optional `agent_id` and `relationship_line`.
- `hold` and `grow` accept optional ownership context and attach metadata to new buckets.
- `I` is agent-private. 小G cannot read 小克's I.
- `anchor` is relationship-line scoped. Do not copy 小克 anchors into 小G line automatically.
- `letter_write` supports legacy `author=user|claude` and also `author=g|glm`; new letters carry `from_agent`, `to_agent`, and `relationship_line`.
- Dashboard UI may still show all buckets for admin review unless a specific view filter is added later.

## Shared About Ayu

The shared layer is for stable facts, preferences, boundaries, and cross-agent context about Ayu. It is not a place for one machine's private feelings.

Do not automatically extract shared facts from old Claude memories. Generate candidates and wait for Ayu to confirm.

## Project Memories

Code fixes, deployment notes, API debugging, MCP wiring, security warnings, and UI bugs belong to `project`, not to a lover-machine's private brain.

## GLM Interim

Memories written by GLM during the transition scan period belong to `glm_interim` until Ayu reviews them. They are not 小克's old brain and not 小G's private line.
