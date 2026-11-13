---
name: ui-acceptance
description: Use when AI 写完/改完 Web 页面、桌面端或移动端界面后要做 UI 验收：设计走查、页面审查、前端交付自检（功能入口冗余、按钮放错页面、页面写成需求文档、布局不合理），或需要跨平台截图比对与视觉回归（抓取预期与实际画面、逐页分类差异并给出验收结论，覆盖桌面 Web/Tauri、Android 应用与微信小程序）。触发词：UI 走查、设计走查、页面审查、前端验收、按钮位置、功能入口、截图对比、视觉回归、跨平台截图、像素对比、diff 截图、UI acceptance。
version: 1.0.0
author: Hermes coding agent
license: Apache-2.0
metadata:
  hermes:
    tags: [ui, review, layout, ux, self-check, web, screenshot, diff, visual-regression, acceptance, android, wechat]
    related_skills: [app-testing, static-deploy-mcp, project-repo-standards]
---

# UI 验收套件 (ui-acceptance)

> 版本记录：1.0.0 由 frontend-review v1.1.0 + ui-diff v1.0.0 合并首发（2026-11-13）。

> **相关技能**：
> - [app-testing](../app-testing/SKILL.md) — 自动化应用测试套件（接口测试与 Web 功能测试、Playwright DOM 交互与 E2E）
> - [static-deploy-mcp](../static-deploy-mcp/SKILL.md) — 原型与截图静态托管分发，生成手机可访问链接
> - [project-repo-standards](../project-repo-standards/SKILL.md) — 项目工程结构与 CI 规范

## 快速路由

按验收诉求选择路径：

| 诉求与场景 | 推荐路径 | 核心手段 |
|---|---|---|
| 设计/布局/入口合理性走查 | **[第一章 UI 审查](#第一章-ui-审查)** | 功能入口登记表、文案纪律、布局清单、四段式交付自检 |
| 截图比对 / 视觉回归 / 交互验收 | **[第二章 截图比对](#第二章-截图比对)** | 跨平台抓图、语义化 diff 分类、严重度报告与修复复验 |

---

## 第一章 UI 审查

AI 写 UI 快，但四类问题高发：**功能入口冗余**（同一功能在多个页面各写一遍）、**入口杂乱**（按钮放在奇怪的页面）、**页面写成需求文档**（大段描述文字）、**布局不合理**。本章把「合理不合理」变成可机械核对的检查项，交付前逐项过，不靠自觉。

### 铁律一句话
**页面是操作台，不是说明书。每个功能只有一个家。每条文字都要能回答「删掉它用户会少什么」。**

### 1. 功能入口登记表（治冗余和杂乱）

动手写 UI 前（或在改动前）先列登记表，交付时更新：

| 功能/操作 | owner 页面（唯一） | 其它出现点（必须为空或注明复用组件） |
|---|---|---|
| 发布版本 | 资产详情页 | 无 |

交付前机械核对：

```bash
# 同一操作出现在几个文件/路由？>1 即违规：要么收敛到 owner 页，要么抽成共享组件/接口
grep -rn "操作关键词" src/ --include="*.vue" --include="*.tsx" -l
```

- 判据：**一个功能只有一个 owner 页面**。其它页面要触发同一功能，引用同一组件或调同一接口，禁止复制粘贴第二份实现。
- 按钮归属：**对象操作跟对象走**（详情/列表行内），全局操作进固定区（顶栏/侧栏）；任何按钮放到「跟它操作的对象无关的页面」= 违规，这是 AI 最常犯的。

### 2. 文案纪律（治「页面写成需求文档」）

- 页面正文只放三类文字：**操作**（动词短语：发布/回滚/删除）、**状态**（数值+单位+时间戳）、**必要提示**（用户此刻必须知道的后果）。
- 判据三连：这段文字是给「正在操作的人」还是「来了解背景的人」？后者 → 移到 README/帮助/tooltip。删掉它用户会不会做错操作？不会 → 删。超过 2 行的说明段落 → 违规。
- 禁止：把需求描述、实现原理、接口说明写进页面；「本页面用于…」类开头句；空状态写成小作文（一句话 + 一个动作按钮即可）。

### 3. 布局审核（截图走查，不靠想象）

交付前用 Playwright/浏览器截图实际页面（桌面 + 移动宽度各一张），按清单逐项核：

- [ ] 每个按钮的操作对象在当前页面/当前行可见（点得下去也知道作用于谁）
- [ ] 同类操作视觉分组，主操作唯一且视觉最重；危险操作与常规操作隔离（确认弹窗/红色）
- [ ] 移动宽度下无横向滚动、无按钮重叠、文字未截断
- [ ] 空态/加载态/错误态三种异常都有真实呈现（不是白屏或永久 loading）
- [ ] 新增内容与既有页面风格一致（间距、颜色、控件类型不另起炉灶）

### 4. 交付前自检协议（回答「哪些有问题、哪些合理」）

写完程序后，**不要直接报完成**，先输出一份四段式自检：

1. **入口清单**：本次新增/改动的全部可交互元素，逐条对需求意图 diff——每条标注「需求内 / 超纲自作主张 / 遗漏」。超纲项默认删或请人确认，不允许静默保留。
2. **重复实现检测**：跑第 1 节的 grep，列出多实现点并给出收敛方案。
3. **异常态覆盖**：空/错/加载/权限不足四种，逐一说明呈现方式；说不出呈现方式的 = 没做。
4. **残留清理**：对抗测试/造的假数据、临时代码、console.log、注释掉的大段旧代码——清干净再交。

自检里发现的问题自己修完再交付；修不了的（涉及信息架构取舍）明确列出请人拍板，不要藏。

### 硬约束

- 本章是审查协议，**不规定视觉风格**；风格类需求用对应设计技能（如 design-taste-frontend）。
- 检查项必须以 grep/截图/清单等可核对形式执行，禁止「我觉得没问题」式口头自检（自动化交互用 `app-testing`，截图视觉对比用本技能第二章）。

---

## 第二章 截图比对

Verify **one screen at a time**: capture expected + actual → compare → severity report → fix only in-scope gaps → re-capture.

Do **not** treat demo/mock data or deferred-phase placeholders as bugs unless the user says the current phase owns that UI.

### When to use

- Prototype / design / golden screenshot vs running implementation
- After implementing or restyling a page/route/Activity/小程序 page
- User says: 截图对比、原型对比、视觉验收、ui-acceptance、/ui-acceptance

### Hard rules

1. **One screen per run** unless the user lists multiple IDs. Finish report before next screen.
2. **Classify before fixing**: `blocker` / `major` / `minor` / `phase-ok` / `noise`.
3. **Never invent captures**. If a platform toolchain is missing, stop and say what to install.
4. Prefer **semantic UI diff** (layout, IA, missing controls, theme) over raw pixel equality.
5. Artifact root defaults to `<cwd>/tmp/ui-acceptance/<run-id>/` (create if needed). Use **absolute paths** for every image.

### Inputs (resolve before capture)

Collect (ask only for missing pieces):

| Field | Examples |
|-------|----------|
| `platform` | `web` \| `tauri-web` \| `desktop-native` \| `android` \| `wechat-miniprogram` |
| `expected` | prototype HTML/URL, Figma export, golden PNG, prior build screenshot |
| `actual` | running URL, packageId/apk + device, 小程序 project path + route |
| `screen_id` | `dashboard`, `settings`, Activity name, 小程序 route |
| `viewport` | desktop default `1440x900`; mobile use device profile |
| `phase_scope` | optional; if project has a feature matrix / phased plan, load it |

### Pipeline

```text
resolve → capture expected → capture actual → normalize → compare → classify → report → (optional) fix+reverify
```

#### 1. Resolve

- Pick capture backend from `references/diff-platforms.md` for `platform`.
- Create `OUT=<cwd>/tmp/ui-acceptance/<screen_id>-<yyyymmdd-hhmmss>/`.
- Paths: `expected.png`, `actual.png`, `report.md`.

#### 2. Capture

Follow the platform section in `references/diff-platforms.md`.

Shared capture constraints:

- Same **theme** on both sides when controllable (e.g. Claude / light / dark).
- Same **logical viewport** (web) or same **device/emulator profile** (Android).
- Navigate to the **same screen** before shot; wait for idle (network/animations).
- Prefer **viewport screenshot** over noisy full desktop; crop status bar / DevTools chrome when they dominate diffs (`noise`).
- On Windows Playwright, prefer `channel: "msedge"` when Chromium download is slow.
- Write files with **absolute** `path.join(OUT, ...)` — never rely on process cwd.

If expected is already a PNG path, skip expected capture and copy/link into `OUT/expected.png`.

#### 3. Normalize (light)

- If sizes differ wildly, note it in the report; do not stretch to force pixel match.
- Optional crop boxes (status bar, window controls) go in `report.md` under Assumptions.
- Do not overwrite originals; save crops as `expected.crop.png` / `actual.crop.png` if used for compare.

#### 4. Compare

**Primary:** MCP `zai-mcp-server__ui_diff_check`

- `expected_image_source` = absolute expected path
- `actual_image_source` = absolute actual path
- `prompt` = use `references/diff-compare-prompt.md` filled with `screen_id`, `platform`, `phase_scope`

**Fallback** (if MCP errors / network HTML / file not found):

1. `read_file` both PNGs (multimodal).
2. Apply the same rubric in `references/diff-severity-rubric.md`.
3. State in report: `compare_engine: grok-multimodal-fallback`.

**Optional pixel hint** (never sole verdict): note obvious blank vs dense screens, or file size ratio as a smell only.

#### 5. Classify

Use `references/diff-severity-rubric.md`. Map each finding to a severity.  
If `phase_scope` says the control is deferred → `phase-ok`, not `blocker`.

#### 6. Report

Write `OUT/report.md` using `references/diff-report-template.md`.  
User-facing summary must include:

- Screen + platform
- Top findings (≤7)
- Suggested next actions (only for `blocker`/`major` in scope)
- Artifact paths

#### 7. Fix loop (only if user wants implementation)

- Fix **in-scope** `blocker`/`major` only.
- Re-capture **actual** only; keep expected unless expected was wrong.
- Re-compare; append a "Reverify" section to `report.md`.

### Project hooks (when present)

If the repo has these, **read them** before classifying:

- `docs/FEATURE_MATRIX.md` / phased plan → phase ownership
- `docs/PROTOTYPE_SPEC.md` → interaction truth
- Prototype HTML / design file → expected source for web/desktop

Do not require these files; cross-platform runs often have none.

### Anti-patterns

- Declaring "UI complete" from a single screenshot without interaction checks the user asked for
- Failing the run because mock timestamps / avatars / pending counts differ
- Using WeChat **phone client** automation when DevTools automator is the supported path
- Skipping Android capture prerequisites and fabricating a screenshot
- Comparing Windows EXE window chrome to a browser prototype without noting chrome mismatch (`noise` or align both to web shell)

### Quick start examples

**Web / Tauri shell (this workspace pattern):**

1. Expected: open `原型1.html` via Playwright `file://` → navigate → shot  
2. Actual: `pnpm dev` → `http://localhost:1420` → same nav → shot  
3. Compare with `ui_diff_check` or multimodal fallback  

**Android:**

1. Expected: design PNG or prior golden  
2. Actual: Maestro `takeScreenshot` / `adb exec-out screencap -p` after navigating to screen  
3. Compare  

**WeChat mini program:**

1. DevTools 打开服务端口 + `miniprogram-automator` (or Minium)  
2. `redirectTo` / `reLaunch` to route → `screenshot`  
3. Compare to design/golden  

### References

- `references/diff-platforms.md` — capture backends & prerequisites per platform  
- `references/diff-severity-rubric.md` — severity rules  
- `references/diff-compare-prompt.md` — MCP prompt  
- `references/diff-report-template.md` — report skeleton  
- `references/diff-capture-web.md` — optional Playwright helper for web/file URLs  
- `references/diff-capture-examples.md` — Android / 小程序 capture examples  

### Slash

`/ui-acceptance`

### 随附资产对照（分发通道只放行 Markdown）

| 原始路径 | 技能包内位置 |
|---|---|
| `scripts/capture-web.js` | `references/diff-capture-web.md`（`## scripts/capture-web.js` 节） |
| `scripts/capture-android-adb.example.sh` | `references/diff-capture-examples.md`（`## scripts/capture-android-adb.example.sh` 节） |
| `scripts/capture-miniprogram.example.js` | `references/diff-capture-examples.md`（`## scripts/capture-miniprogram.example.js` 节） |
| `templates/compare-prompt.md` | `references/diff-compare-prompt.md`（`## templates/compare-prompt.md` 节） |
| `templates/report.md` | `references/diff-report-template.md`（`## templates/report.md` 节） |

> 本技能的抓图脚本与模板已转写为 Markdown；`capture-web.js` 等按节还原后可直接执行。

## 版本与升级（统一走 skillctl）

更新源（唯一权威）：`http://100.64.0.88:8088/.well-known/skills/index.json`

```bash
# 首次：下载通用客户端（每台机器一次）
curl -fsSL http://100.64.0.88:8088/.well-known/skillctl.py -o skillctl.py && chmod +x skillctl.py

# 干活前惰性检查（约 1 秒）：落后就先升级，再动手
./skillctl.py list                                  # 本地各技能版本 vs 注册表
./skillctl.py update --to <你的技能目录>             # 默认只检测（--to 用绝对路径）
./skillctl.py update --to <你的技能目录> --apply     # 确认后才升级（逐文件 sha256 校验）
```

版本语义：`patch` 修错别字不改结论；`minor` 新增章节/接口；`major` 推翻既有结论（需重读全文）。
