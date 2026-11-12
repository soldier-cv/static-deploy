# 维护 Hearthbox 平台

平台仓库是 `hearthbox/`，游戏不在里面（D12，见 `docs/decisions.md`）。

## 开工前

```bash
git fetch --all --prune
git status --short && git log --oneline -5
git pull --ff-only
```

有未提交改动先 `git stash push -u -m "说明"`，拉完 `git stash pop`。

## 代码地图

```
packages/sdk/src/index.ts       契约。改这里等于改所有游戏的编译面
packages/runtime/src/
  loop.ts         固定 60Hz，单帧最多 5 步
  input.ts        三层汇总、边沿、保留键
  input-source.ts 位掩码、Raw* 结构
  input-gamepad.ts / input-keyboard.ts / input-pointer.ts
  deadzone.ts     纯函数，好测
  display.ts      缩放、DPR、坐标换算、指针外观
  audio.ts        单上下文 + 双总线
  storage.ts      IndexedDB，版本化迁移
  session.ts      组装一次游戏会话，最复杂
  cheats.ts       金手指声明与状态合并
  debug.ts        种子/时间缩放/手动步进
  web-bridge.ts   浏览器壳的输入源与生命周期
apps/shell/src/
  shelf.tsx       货架（Preact）
  play.ts         宿主页：加载包、解锁音频、错误边界
  pads.ts         手柄检测页，M0 实测用
demo/              演示游戏，验证平台每项能力
```

## 改 SDK 契约时的规矩

SDK 主版本内**只加不改**。加字段用可选，删字段或改语义必须升主版本。

改完 SDK 要连带做：

1. `pnpm --filter @hearthbox/sdk build`（runtime 读的是 `dist/*.d.ts`）
2. 更新 `docs/game-sdk.md` 的类型片段
3. 如果动了输入或金手指，更新对应文档
4. 跑 `pnpm typecheck`（演示游戏会立刻暴露破坏性改动——它们就是干这个的）

## 加一个新能力的最小路径

以"加一个指针模式"为例：

1. `packages/sdk/src/index.ts` 加类型
2. `packages/runtime/src/*.ts` 实现，接进 `session.ts`
3. `packages/runtime/test/*.test.ts` 写单元测试（**先写测试**，热路径的 bug 靠肉眼看不出来）
4. 演示游戏里用一下，证明端到端通
5. `apps/shell/test/e2e.spec.ts` 加一条真浏览器用例
6. `docs/` 更新，必要时在 `docs/decisions.md` 追加 D 记录

## 热路径纪律

`loop` / `input` / `display` 每帧都跑：

- 不分配。`PadState`、`Raw*`、视图对象全部预分配、跨帧复用。
- 不 `JSON.stringify`、不做字符串拼接、不建闭包。
- 数组用 `Int32Array` / `Uint8Array` 而不是 `number[]`。
- 用 `fill(0)` 清零，不要每帧 new。

测试里有一条"不分配新的 PadState 对象"，改输入逻辑时要让它继续过。

## 存储迁移

`packages/runtime/src/storage.ts` 的 `DB_VERSION`。加对象库时：

1. 版本号 +1
2. 在 `STORES` 里加名字（`onupgradeneeded` 会自动补建缺失的库）
3. **绝不删除重建** —— 会丢所有用户的存档与已装游戏

## 测试

```bash
pnpm test                                   # Vitest，快
pnpm exec playwright test                   # 真浏览器，会自己起 dev server
pnpm exec playwright test -g "鼠标"          # 只跑匹配的
```

端到端里玩像素画布的技巧：`getImageData` 扫描，按"饱和色 / 低饱和"区分游戏物件和 UI。演示游戏里的 `findBlock` / `findInputBlock` 是范例。

**共用 origin 的坑**：多个用例共享 IndexedDB，前一个的存档会变成后一个的初始状态，表现为"首轮失败、重试通过"。用 `indexedDB.deleteDatabase` 清，或让每个用例自己处理。

## 常见错误

| 症状 | 原因 |
|---|---|
| `Cannot find module '@hearthbox/sdk'` | 新包没 `pnpm install` 建链接；或 SDK 没 build |
| 构建成功但 `dist` 是空的 | `tsconfig.base.json` 的 `noEmit: true` 被继承，build 配置要显式写 `noEmit: false` |
| 演示游戏改了不生效 | 忘了 `pnpm fixtures`，或 `public/fixtures/*` 被缓存 |
| Vite 报 "file is in /public" | public 下的文件不能被 `import`，只能 `fetch` |
| Playwright 起不来 | 端口 5199 被占用；Vite 要用 `host: '127.0.0.1'`，它默认只监听 localhost |
| 中文文档 diff 巨大 | Prettier 重排了表格。`docs/` 已在 `.prettierignore` 里 |

## 提交前

```bash
pnpm lint && pnpm typecheck && pnpm test && pnpm build
```

四条全绿再提交。提交信息用中文主题 + 约定式前缀。

改了文档就在 `docs/roadmap.md` 勾上对应项，别另开 Markdown 记进度。
