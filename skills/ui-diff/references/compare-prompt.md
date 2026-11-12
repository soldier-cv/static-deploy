# 比对提示词模板（compare-prompt.md）

> 本文件是技能包内可执行资产的 Markdown 转写 —— 分发通道只放行 `SKILL.md` 与 `references/*.md`。
> 落地方法：按各节标题里的路径原样写回磁盘，代码块内容与原文件一致。

## `templates/compare-prompt.md`

```markdown
Compare two UI screenshots for acceptance.

- screen_id: {{SCREEN_ID}}
- platform: {{PLATFORM}}
- phase_scope: {{PHASE_SCOPE}}
- expected = design / prototype / golden (reference)
- actual = current implementation

Focus on:
1. Information architecture and major regions
2. Required controls for this screen (presence, placement, hierarchy)
3. Layout proportion and spacing of primary content
4. Theme / color / typography alignment at a product level
5. Explicitly separate: deferred-phase placeholders vs real layout bugs vs noise (status bar, clocks, dynamic counts, window chrome)

Output:
- blocker / major / minor / phase-ok / noise findings (short bullets)
- pass or fail under: no in-scope blocker; majors only if acceptable
- top 3–5 recommended fixes (in-scope only)
```
