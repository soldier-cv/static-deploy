# 抓图示例（Android / 小程序）

> 本文件是技能包内可执行资产的 Markdown 转写 —— 分发通道只放行 `SKILL.md` 与 `references/*.md`。
> 落地方法：按各节标题里的路径原样写回磁盘，代码块内容与原文件一致。

## `scripts/capture-android-adb.example.sh`

```bash
#!/usr/bin/env bash
# Example only — copy and fill package/activity. Requires adb + device/emulator.
set -euo pipefail
OUT="${UI_DIFF_OUT:?set UI_DIFF_OUT to absolute dir}"
mkdir -p "$OUT"
# adb shell am start -n "$PACKAGE/$ACTIVITY"
adb exec-out screencap -p > "$OUT/actual.png"
echo "saved $OUT/actual.png"
```

## `scripts/capture-miniprogram.example.js`

```javascript
/**
 * Example only — requires 微信开发者工具服务端口 + miniprogram-automator.
 *
 *   npm i -D miniprogram-automator
 *   set UI_DIFF_OUT / UI_DIFF_MP_PROJECT / UI_DIFF_MP_ROUTE
 */
const automator = require("miniprogram-automator");
const fs = require("fs");
const path = require("path");

const OUT = process.env.UI_DIFF_OUT;
const PROJECT = process.env.UI_DIFF_MP_PROJECT;
const ROUTE = process.env.UI_DIFF_MP_ROUTE || "/pages/index/index";

(async () => {
  if (!OUT || !PROJECT) {
    console.error("UI_DIFF_OUT and UI_DIFF_MP_PROJECT required");
    process.exit(1);
  }
  fs.mkdirSync(OUT, { recursive: true });
  const miniProgram = await automator.launch({ projectPath: PROJECT });
  await miniProgram.reLaunch(ROUTE);
  await new Promise((r) => setTimeout(r, 800));
  const file = path.join(OUT, "actual.png");
  await miniProgram.screenshot({ path: file });
  console.log("saved", file);
  await miniProgram.close();
})().catch((e) => {
  console.error("FAILED", e);
  process.exit(1);
});
```
