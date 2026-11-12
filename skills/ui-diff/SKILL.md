---
name: ui-diff
description: Use when 需要跨平台 UI 截图比对：抓取预期与实际画面、逐页分类差异并给出验收结论，覆盖桌面 Web/Tauri、Android 应用与微信小程序。触发词：screenshot compare、prototype vs app、UI acceptance、visual regression、页面验收、Android/小程序页面对比、/ui-diff。
version: 1.0.0
---

# ui-diff — Cross-platform UI screenshot verify

Verify **one screen at a time**: capture expected + actual → compare → severity report → fix only in-scope gaps → re-capture.

Do **not** treat demo/mock data or deferred-phase placeholders as bugs unless the user says the current phase owns that UI.

## When to use

- Prototype / design / golden screenshot vs running implementation
- After implementing or restyling a page/route/Activity/小程序 page
- User says: 截图对比、原型对比、视觉验收、ui-diff、/ui-diff

## Hard rules

1. **One screen per run** unless the user lists multiple IDs. Finish report before next screen.
2. **Classify before fixing**: `blocker` / `major` / `minor` / `phase-ok` / `noise`.
3. **Never invent captures**. If a platform toolchain is missing, stop and say what to install.
4. Prefer **semantic UI diff** (layout, IA, missing controls, theme) over raw pixel equality.
5. Artifact root defaults to `<cwd>/tmp/ui-diff/<run-id>/` (create if needed). Use **absolute paths** for every image.

## Inputs (resolve before capture)

Collect (ask only for missing pieces):

| Field | Examples |
|-------|----------|
| `platform` | `web` \| `tauri-web` \| `desktop-native` \| `android` \| `wechat-miniprogram` |
| `expected` | prototype HTML/URL, Figma export, golden PNG, prior build screenshot |
| `actual` | running URL, packageId/apk + device, 小程序 project path + route |
| `screen_id` | `dashboard`, `settings`, Activity name, 小程序 route |
| `viewport` | desktop default `1440x900`; mobile use device profile |
| `phase_scope` | optional; if project has a feature matrix / phased plan, load it |

## Pipeline

```text
resolve → capture expected → capture actual → normalize → compare → classify → report → (optional) fix+reverify
```

### 1. Resolve

- Pick capture backend from `references/platforms.md` for `platform`.
- Create `OUT=<cwd>/tmp/ui-diff/<screen_id>-<yyyymmdd-hhmmss>/`.
- Paths: `expected.png`, `actual.png`, `report.md`.

### 2. Capture

Follow the platform section in `references/platforms.md`.

Shared capture constraints:

- Same **theme** on both sides when controllable (e.g. Claude / light / dark).
- Same **logical viewport** (web) or same **device/emulator profile** (Android).
- Navigate to the **same screen** before shot; wait for idle (network/animations).
- Prefer **viewport screenshot** over noisy full desktop; crop status bar / DevTools chrome when they dominate diffs (`noise`).
- On Windows Playwright, prefer `channel: "msedge"` when Chromium download is slow.
- Write files with **absolute** `path.join(OUT, ...)` — never rely on process cwd.

If expected is already a PNG path, skip expected capture and copy/link into `OUT/expected.png`.

### 3. Normalize (light)

- If sizes differ wildly, note it in the report; do not stretch to force pixel match.
- Optional crop boxes (status bar, window controls) go in `report.md` under Assumptions.
- Do not overwrite originals; save crops as `expected.crop.png` / `actual.crop.png` if used for compare.

### 4. Compare

**Primary:** MCP `zai-mcp-server__ui_diff_check`

- `expected_image_source` = absolute expected path
- `actual_image_source` = absolute actual path
- `prompt` = use `references/compare-prompt.md` filled with `screen_id`, `platform`, `phase_scope`

**Fallback** (if MCP errors / network HTML / file not found):

1. `read_file` both PNGs (multimodal).
2. Apply the same rubric in `references/severity-rubric.md`.
3. State in report: `compare_engine: grok-multimodal-fallback`.

**Optional pixel hint** (never sole verdict): note obvious blank vs dense screens, or file size ratio as a smell only.

### 5. Classify

Use `references/severity-rubric.md`. Map each finding to a severity.  
If `phase_scope` says the control is deferred → `phase-ok`, not `blocker`.

### 6. Report

Write `OUT/report.md` using `references/report-template.md`.  
User-facing summary must include:

- Screen + platform
- Top findings (≤7)
- Suggested next actions (only for `blocker`/`major` in scope)
- Artifact paths

### 7. Fix loop (only if user wants implementation)

- Fix **in-scope** `blocker`/`major` only.
- Re-capture **actual** only; keep expected unless expected was wrong.
- Re-compare; append a "Reverify" section to `report.md`.

## Project hooks (when present)

If the repo has these, **read them** before classifying:

- `docs/FEATURE_MATRIX.md` / phased plan → phase ownership
- `docs/PROTOTYPE_SPEC.md` → interaction truth
- Prototype HTML / design file → expected source for web/desktop

Do not require these files; cross-platform runs often have none.

## Anti-patterns

- Declaring "UI complete" from a single screenshot without interaction checks the user asked for
- Failing the run because mock timestamps / avatars / pending counts differ
- Using WeChat **phone client** automation when DevTools automator is the supported path
- Skipping Android capture prerequisites and fabricating a screenshot
- Comparing Windows EXE window chrome to a browser prototype without noting chrome mismatch (`noise` or align both to web shell)

## Quick start examples

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

## References

- `references/platforms.md` — capture backends & prerequisites per platform  
- `references/severity-rubric.md` — severity rules  
- `references/compare-prompt.md` — MCP prompt  
- `references/report-template.md` — report skeleton  
- `references/capture-web.md` — optional Playwright helper for web/file URLs  

## Slash

`/ui-diff`

## 随附资产对照（分发通道只放行 Markdown）

| 原始路径 | 技能包内位置 |
|---|---|
| `scripts/capture-web.js` | `references/capture-web.md`（`## scripts/capture-web.js` 节） |
| `scripts/capture-android-adb.example.sh` | `references/capture-examples.md`（`## scripts/capture-android-adb.example.sh` 节） |
| `scripts/capture-miniprogram.example.js` | `references/capture-examples.md`（`## scripts/capture-miniprogram.example.js` 节） |
| `templates/compare-prompt.md` | `references/compare-prompt.md`（`## templates/compare-prompt.md` 节） |
| `templates/report.md` | `references/report-template.md`（`## templates/report.md` 节） |

> 本技能的抓图脚本与模板已转写为 Markdown；`capture-web.js` 等按节还原后可直接执行。

## 更新与升级（统一走 skillctl）

更新源：`http://100.64.0.88:8088/.well-known/skills/index.json`

```bash
./skillctl.py list                                  # 本地各技能版本 vs 注册表
./skillctl.py update --to <你的技能目录>             # 默认只检测
./skillctl.py update --to <你的技能目录> --apply     # 确认后升级（逐文件 sha256 校验）
```
