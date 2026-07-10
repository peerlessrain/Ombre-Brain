# OB MCP Usage With Memory Isolation

Ombre Brain is the machine's brain, not a generic user archive. Every new memory-like write belongs to exactly one active agent so one agent does not accidentally inherit another agent's private selfhood.

## Ownership Fields

- `agent_id`: who this memory belongs to. Use `claude`, `g`, or `glm`.
- `relationship_line`: fixed per agent: `claude_line`, `g_line`, or `glm_interim`.
- `scope`: use `agent_private`.
- `visibility`: use `same_agent`, `same_line`, `manual_only`, or `archived`.
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

Default MCP reads do not return:

- Another agent's `I`, feel, dreams, private anchors, or private letters.
- `glm_interim` memories unless the current context is GLM or Ayu explicitly asks.
- `manual_only` or `archived` memories.
- Retired public/project ownership records that may remain in old files.

## Write Rules

Use these fixed ownership pairs:

- 小克 / Claude: `agent_id=claude`, `relationship_line=claude_line`.
- 小G: `agent_id=g`, `relationship_line=g_line`.
- GLM transition scan: `agent_id=glm`, `relationship_line=glm_interim`.

New writes reject public, project, system, Ayu-owned, and unknown ownership values. Old files using retired values are preserved without migration but are not returned by normal reads.

## Tool Notes

- `breath`, `dream`, `pulse`, `I(read=True)`, and `letter_read` accept optional `agent_id` and `relationship_line`.
- `hold` and `grow` accept optional ownership context and attach metadata to new buckets.
- `I` is agent-private. 小G cannot read 小克's I.
- `anchor` is relationship-line scoped. Do not copy 小克 anchors into 小G line automatically.
- `letter_write` supports legacy `author=user|claude` and also `author=g|glm`; new letters carry `from_agent`, `to_agent`, and `relationship_line`.
- Dashboard data views use the global 小克 / 小G / GLM switcher and never change MCP identity.

## GLM Interim

Memories written by GLM during the transition scan period belong to `glm_interim` until Ayu reviews them. They are not 小克's old brain and not 小G's private line.
