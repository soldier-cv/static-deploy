# 抓图助手（capture-web.js）

> 本文件是技能包内可执行资产的 Markdown 转写 —— 分发通道只放行 `SKILL.md` 与 `references/*.md`。
> 落地方法：按各节标题里的路径原样写回磁盘，代码块内容与原文件一致。

## `scripts/capture-web.js`

```javascript
/**
 * Web / file:// capture helper for ui-acceptance.
 *
 * Usage (via playwright-skill run.js recommended):
 *   node run.js <this-file>
 *
 * Env:
 *   UI_DIFF_OUT        absolute output directory (required)
 *   UI_DIFF_EXPECTED   expected URL (file:// or http)
 *   UI_DIFF_ACTUAL     actual URL (http)
 *   UI_DIFF_WIDTH      default 1440
 *   UI_DIFF_HEIGHT     default 900
 *   UI_DIFF_NAV_TEXT   optional: click control containing this text after load (both sides)
 *   UI_DIFF_SETTLE_MS  default 800
 */
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");

const OUT = process.env.UI_DIFF_OUT;
const EXPECTED = process.env.UI_DIFF_EXPECTED;
const ACTUAL = process.env.UI_DIFF_ACTUAL;
const WIDTH = Number(process.env.UI_DIFF_WIDTH || 1440);
const HEIGHT = Number(process.env.UI_DIFF_HEIGHT || 900);
const NAV_TEXT = process.env.UI_DIFF_NAV_TEXT || "";
const SETTLE = Number(process.env.UI_DIFF_SETTLE_MS || 800);

function die(msg) {
  console.error("FAILED:", msg);
  process.exit(1);
}

async function shot(page, url, file) {
  await page.goto(url, { waitUntil: "domcontentloaded", timeout: 45000 });
  try {
    await page.waitForLoadState("networkidle", { timeout: 10000 });
  } catch (_) {
    /* prototypes may not networkidle */
  }
  if (NAV_TEXT) {
    const loc = page.getByText(NAV_TEXT, { exact: false }).first();
    if (await loc.count()) {
      await loc.click({ timeout: 5000 }).catch(() => {});
    }
  }
  await page.waitForTimeout(SETTLE);
  const abs = path.join(OUT, file);
  await page.screenshot({ path: abs, fullPage: false });
  console.log("saved", abs);
}

(async () => {
  if (!OUT) die("UI_DIFF_OUT is required (absolute path)");
  if (!EXPECTED && !ACTUAL) die("set UI_DIFF_EXPECTED and/or UI_DIFF_ACTUAL");
  fs.mkdirSync(OUT, { recursive: true });

  const browser = await chromium.launch({
    headless: true,
    channel: process.env.UI_DIFF_CHANNEL || "msedge",
  });
  const context = await browser.newContext({
    viewport: { width: WIDTH, height: HEIGHT },
  });
  const page = await context.newPage();

  if (EXPECTED) await shot(page, EXPECTED, "expected.png");
  if (ACTUAL) await shot(page, ACTUAL, "actual.png");

  await browser.close();
  console.log("DONE");
})().catch((e) => {
  console.error("FAILED", e);
  process.exit(1);
});
```
