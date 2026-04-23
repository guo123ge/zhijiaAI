# Agent Configs — YAML-driven agent definitions (Phase H1)

This directory contains **declarative agent definitions**. Each `.md` file here
becomes a fully working agent at runtime, without writing any Python code.

## File format

Each file has YAML frontmatter + a system prompt body:

```markdown
---
name: my_agent             # required, snake_case, unique
description: 一句话描述     # required
model: fast                # fast | balanced | powerful (default: balanced)
read_only: true            # default: false
max_turns: 6               # default: 12
max_tool_concurrency: 5    # default: 5
compact_threshold_tokens: 0  # default: 0 (disabled)
tools:                     # list of tool names from ToolRegistry
  - search_quotas
  - get_quota_detail
---

你是一个... (system prompt body, multi-line)
```

## How to add a new agent

1. Drop a `.md` file in this directory (follow the format above).
2. Use only tool names that exist in the global `ToolRegistry`
   (see `app/ai/tools/` for the full list of 22 tools).
3. Run the test suite — `test_agent_framework.py` validates all configs.
4. Load them at runtime via:

   ```python
   from app.ai.framework.agent_loader import load_agents_from_dir
   agents = load_agents_from_dir("app/ai/agents/configs")
   ```

## Current configs

| File | Agent | Purpose |
|------|-------|---------|
| `quick_explorer.md` | quick_explorer | 最轻量级只读查询 (fast tier) |
| `price_checker.md` | price_checker | 单价异常专项审核 |

## Validation

The loader validates:
- YAML frontmatter is well-formed
- `name` is lowercase snake_case
- All `tools` exist in the global registry
- `model` is one of `fast | balanced | powerful`
- No duplicate agent names across files

Invalid files are skipped with a warning (or raise if `strict=True`).

## README exclusion

This `README.md` file is automatically skipped because its filename starts
with an uppercase letter and would fail name validation. The loader also
skips any file whose YAML fails to parse.
