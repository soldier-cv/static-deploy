# Capture backends by platform

Skill home: choose **one** backend per run. Prefer the first listed option that is installed.

## web / tauri-web

**Use when:** HTML prototype, Vite/React shell, Tauri UI via `pnpm dev` (WebView content ≈ browser).

| Role | Method |
|------|--------|
| Tooling | Existing `playwright-skill` (`node run.js <script>`) or `scripts/capture-web.js` |
| Expected | `file://` prototype, staging URL, or static PNG |
| Actual | `http://localhost:<port>` (detect via playwright helpers or project docs; Agent Sync Manager uses **1420**) |
| Navigate | Click sidebar / router to `screen_id`; wait network idle + short settle |
| Browser | Playwright; on Windows prefer `channel: "msedge"` |

**Tauri note:** Full native window chrome (custom title bar) may differ slightly in browser preview. For EXE-accurate chrome, use `desktop-native`. For layout/IA of main content, `tauri-web` is enough and preferred during day-to-day UI work.

## desktop-native

**Use when:** Must include real window frame / OS chrome / packaged EXE/DMG behavior.

| Method | Notes |
|--------|-------|
| OS screenshot of focused window | Last resort; document crop of non-app areas |
| Platform-specific window capture | Use only if already available in environment |

Keep expected on the same surface when possible (both native, or both web). Mixed native-vs-browser → mark window-chrome deltas as `noise` unless the bug is inside content.

## android

**Goal:** Stable screen bitmap after navigating to the target UI.

### Preferred: Maestro

- Docs: Maestro `takeScreenshot` / `assertScreenshot` (threshold-based pixel check is **optional hint only**; this skill still runs semantic compare).
- Flow sketch:

```yaml
appId: your.package.id
---
- launchApp
- tapOn: "Settings"   # or deep link / start activity
- takeScreenshot: actual
```

- Copy Maestro output PNG into `OUT/actual.png`.

### Fallback: adb

Prereqs: `adb devices` shows a device/emulator; app installed; USB debugging on.

```bash
adb shell am start -n <package>/<activity>   # or monkey / deep link
# wait for UI
adb exec-out screencap -p > actual.png
```

### Heavier: Appium

Use when Maestro cannot express the navigation. Still export a PNG into `OUT`; do not make Appium the compare engine.

### Android normalization

Treat as **`noise`** unless user cares:

- Status bar clock / battery / notification icons  
- Gesture bar  
- Dynamic badges / unread counts / ads  

Prefer cropping to the app content region when comparing to a design that excludes system chrome.

## wechat-miniprogram

**Supported path:** WeChat DevTools automation — **not** driving the consumer WeChat mobile app UI.

### Prerequisites

1. 微信开发者工具 installed  
2. **设置 → 安全设置 → 服务端口：开启**  
3. Project path with `project.config.json`  
4. One of:
   - **JS:** `miniprogram-automator` (official)
   - **Python:** `minium` (official MiniTest)
   - Optional agent CLIs/MCPs wrapping automator (e.g. community DevTools automator) — only if already installed

### Capture sketch (miniprogram-automator)

```js
const automator = require("miniprogram-automator");
const miniProgram = await automator.launch({
  projectPath: "D:/path/to/miniapp",
  // cliPath: optional path to DevTools CLI
});
const page = await miniProgram.reLaunch("/pages/index/index");
await page.waitFor(500);
await miniProgram.screenshot({ path: "actual.png" });
await miniProgram.close();
```

### Expected sources

- Design PNG / 视觉稿  
- Prior golden from same route  
- DevTools simulator screenshot of a known-good branch  

### Mini program noise

- Home indicator / nav bar differences between iOS/Android simulator skins  
- User nicknames / avatars  
- 胶囊按钮区域 — usually ignore unless the bug is collision/layout under the capsule  

If DevTools port is closed or automator cannot attach: **stop** and report prerequisites — do not fake a screenshot.

## Matrix (decision)

| Platform | Capture first choice | Compare |
|----------|----------------------|---------|
| web / tauri-web | Playwright | `ui_diff_check` → multimodal |
| desktop-native | Focused window / native shot | same |
| android | Maestro screenshot → adb screencap | same |
| wechat-miniprogram | miniprogram-automator / Minium | same |

Compare engine is **platform-agnostic**. Only capture + crop rules change.
