# 报告骨架（report.md）

> 本文件是技能包内可执行资产的 Markdown 转写 —— 分发通道只放行 `SKILL.md` 与 `references/*.md`。
> 落地方法：按各节标题里的路径原样写回磁盘，代码块内容与原文件一致。

## `templates/report.md`

```markdown
# ui-diff report — {{SCREEN_ID}}

| Field | Value |
|-------|-------|
| platform | {{PLATFORM}} |
| phase_scope | {{PHASE_SCOPE}} |
| compare_engine | {{COMPARE_ENGINE}} |
| result | {{PASS_FAIL}} |
| out_dir | {{OUT_DIR}} |
| expected | {{EXPECTED_PATH}} |
| actual | {{ACTUAL_PATH}} |
| captured_at | {{TIMESTAMP}} |

## Assumptions

- 

## Findings

| Severity | Finding |
|----------|---------|
| | |

## Recommended fixes (in-scope)

1. 

## Out of scope / ignored

- phase-ok:
- noise:

## Reverify

<!-- append after fix loop -->
```
