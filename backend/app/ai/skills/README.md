# Skills — 领域知识模块（Phase H4）

Skills 把专业领域知识（标准规范、合规要点、计价技巧）从 Agent 代码中解耦，
以可复用的 Markdown 模块形式组织。多个 Agent 可以共享同一个 Skill。

## 与 Agent 的区别

| | Agent | Skill |
|-|-------|-------|
| 是什么 | 完整的推理主体（prompt + tools + loop）| 纯领域知识片段 |
| 能执行工具吗 | 可以 | 不可以 |
| 谁加载 | Orchestrator / 用户 | Agent 声明或运行时 `load_skill` |
| 多处复用 | 每个 Agent 独立 | 多个 Agent 共享 |

## 文件格式

`.md` 文件，snake_case 命名，含 YAML frontmatter：

```markdown
---
name: hksmm4_basics
title: HKSMM4 第四版基础规则
description: 香港标准工程量计算方法第四版核心规则
triggers:
  - HKSMM4
  - 香港工程量
applies_to:
  region: HK
tags:
  - standard
  - hong_kong
version: "4.0"
---

## 总则
...domain knowledge body...
```

## 必填字段

- **name**：snake_case，作为唯一标识。
- **title**：人类可读标题。
- **description**：一句话说明。
- **body**：frontmatter 之后的 Markdown 正文（即知识内容）。

## 可选字段

- **triggers**：关键词列表，用于 `match_skills` 自动匹配。
- **applies_to**：映射形式的过滤条件，例如 `{region: HK}`。
- **tags**：标签，用于按类别检索。
- **version**：版本号，便于追溯。

## 两种使用方式

### 1. 静态声明（推荐）

在 Agent YAML 配置中列出所用 Skill：

```yaml
---
name: hk_boq_agent
tools:
  - search_boq
  - validate_boq
skills:
  - hksmm4_basics
---

你是一位香港 BOQ 编制专家...
```

Agent 启动时会自动把 `hksmm4_basics.body` 拼接到 system prompt 之前。

### 2. 动态加载（运行时）

Agent 通过工具在对话中按需加载：

```python
# Agent decides mid-conversation:
match_skills(query="混凝土泵送费")
# → [{"name": "concrete_pricing_tips", ...}]

load_skill(name="concrete_pricing_tips")
# → {"content": "<full skill body>"}
```

## 现有 Skill 清单

- `hksmm4_basics` — HKSMM4 第四版基础规则（香港）
- `gb50500_compliance` — GB50500-2013 工程量清单计价规范合规要点（中国大陆）
- `concrete_pricing_tips` — 混凝土工程计价实战技巧

## 添加新 Skill

1. 在本目录下新建 `snake_case.md` 文件。
2. 填写 YAML frontmatter + 知识内容。
3. 重启应用（或在测试中手动调用 `skill_registry.register(parse_skill_file(...))`）。
4. 自动被 `list_skills` / `match_skills` 发现。

## 最佳实践

- **聚焦单一主题**：一个 Skill 一个领域，便于组合。
- **可执行的 checklist**：规则应可直接验证（"门窗洞口 > 0.5m² 扣减"）。
- **给示例和数字**：让 LLM 能直接引用，避免空泛。
- **标注版本**：标准会改版（HKSMM3 vs HKSMM4），必须写明。
- **引用权威出处**：标注规范条款编号（HKSMM4 Part C, GB50500 §9.x 等）。
