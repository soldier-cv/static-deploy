# 开发 Hearthbox 游戏

游戏是**独立仓库**，只依赖发布后的 `@hearthbox/sdk`，不改平台源码。

## 开工前先加载这两个技能

| 技能 | 用在哪 |
|---|---|
| `2d-games` | sprite 组织、tilemap、碰撞检测、相机、伤害数字 |
| `game-design` | 还没定玩法时，先定核心循环与数值 |

**涉及画面就必须加载 `2d-games`**，否则容易写出"能跑但手感差"的东西——
碰撞用圆形还是 AABB、相机怎么跟随、什么时候不该做屏幕震动，那些它已经写好了。

美术风格与素材规格见 `game-art`，音效见 `game-audio`。

## 开始之前

确认当前目录是不是游戏仓库：有 `game.json` 和 `src/main.ts` 就是。

**不要在平台仓库 `hearthbox/` 里写游戏。**

## 1. 复制模板，不要手搓

```bash
cd hearthbox-projects
cp -r hearthbox/templates/game my-game
cd my-game
git init && git add -A && git commit -m "feat: 从模板初始化"
```

模板里已经有一条能跑通的完整链路：输入 → 移动 → 碰撞 → 状态机 → 存档 → 重开。照它改比从零写快得多。

然后改四处，**id 出现的地方必须完全一致**：

1. `package.json` 的 `name`
2. `game.json` 的 `id` 和 `name`
3. `src/main.ts` 里 `defineGame({ id })`
4. `AGENTS.md` —— **必须改**，它用模板自带的小游戏作为样例填好了，照着改成你的实际情况

**`AGENTS.md` 不是可选项。** 每个游戏仓库都必须有自己的，否则下一个进来的代理只能靠读代码猜这个游戏是什么。它要写清：这个游戏是什么、目录结构、依赖谁、硬性规矩、怎么跑起来。

```bash
pnpm install --ignore-workspace
npx vite build
cd ../hearthbox && pnpm dev
```

浏览器开 `127.0.0.1:5199`，货架上就有你的游戏。

## 2. 目录结构

```
my-game/
├── game.json       清单：id、分辨率、需要哪些输入
├── package.json
├── src/
│   ├── main.ts     入口，defineGame()
│   ├── config.ts   所有常量（分辨率、颜色、体积）
│   └── tuning.ts   可调数值（速度、经验、出怪）
├── tsconfig.json
├── vite.config.ts
├── assets/         素材（可选）
└── docs/           玩法一页纸、系统表、美术规范、验收清单
```

**先填 `docs/pitch.md` 再写代码。** 核心动词填不出来就说明玩法没想清楚。四份文档怎么用见技能 `hearthbox-game-design`。

## 3. 入口

```ts
import { defineGame, type GameContext, type GameInstance } from '@hearthbox/sdk';

export default defineGame({
  id: 'me.my-game',        // 必须与 game.json 一致

  async create(ctx: GameContext): Promise<GameInstance> {
    return {
      update(dt: number) { /* 固定 60Hz，dt 恒为 1/60 */ },
      render(alpha: number) { /* 每显示帧一次，alpha ∈ [0,1) */ },
      pause() {}, resume() {}, dispose() {},
    };
  },
});
```

铁律：

- **不调 `requestAnimationFrame`**。循环归平台，否则暂停、插值、防死亡螺旋全失效。
- **不用 `setTimeout` 驱动逻辑**。要计时就用 `update` 里的 dt 累加。
- **不读 `navigator.getGamepads()`**。输入只从 `ctx.input` 来。
- **`update` 不碰 DOM / Canvas**，`render` 只绘制。
- **不直接写 localStorage / IndexedDB**。存档只走 `ctx.storage`。
- **音频不接 `ctx.destination`**，接 `ctx.audio.music` 或 `ctx.audio.sfx`。

## 4. ctx 提供什么

```ts
ctx.ctx2d        // 2D 上下文，逻辑坐标系（如 320×180），平台负责缩放
ctx.width/height // 逻辑宽高
ctx.input        // 三层输入，见下
ctx.storage      // get/set/delete，同步读内存，异步落盘
ctx.audio        // ctx / music / sfx
ctx.assets       // image/audio/json/text/url，路径相对包内 assets/
ctx.options      // 可调项：金手指、设置、成就
ctx.random       // 可设定种子，能复现整局行为
ctx.debug        // 调试口子，默认全关时是空操作
ctx.platform     // shell / sdkVersion / locale
ctx.exit()       // 返回货架
ctx.rumble()     // 尽力而为
ctx.setPointerMode('hidden' | 'visible' | 'pointer')
```

### 输入三层

```ts
// ① 手柄层：摇杆、按钮。键盘方向键与 WASD 也映射进来
ctx.input.p1.move.x / .y      // 长度 ≤ 1
ctx.input.p1.held('south')    // 也有 pressed / released

// ② 键盘层：完整物理键位
ctx.input.keyboard.held('KeyA')
ctx.input.keyboard.pressed('Space')

// ③ 指针层：鼠标/触控，坐标已是逻辑像素
ctx.input.pointer.x / .y
ctx.input.pointer.pressed('left')
ctx.input.pointer.wheel       // 本帧滚轮，向下为正
```

按游戏类型选：

- 只要上下左右 → 只读 `p1`，手柄和键盘自动都能用
- 有自己的按键方案 → 读 `keyboard`，用 `KeyboardEvent.code`（`KeyA` 不是 `'a'`）
- 点击/拖拽 → 读 `pointer`，**不要自己乘缩放倍数**

三层可以同时读。不要写 `if (hasMouse)` 这种分支。

## 5. game.json

```json
{
  "id": "me.my-game",
  "name": "我的游戏",
  "summary": "一句话介绍，货架上显示",
  "version": "0.1.0",
  "sdk": "^0.1.0",
  "entry": "game.js",
  "display": { "width": 320, "height": 180, "pixelArt": true, "scale": "integer" },
  "players": { "min": 1, "max": 2 },
  "input": ["pad", "keyboard"],
  "pointer": "hidden",
  "license": "MIT"
}
```

| 字段 | 注意 |
|---|---|
| `id` | 格式 `小写.小写`，**发布后不可改**（改了玩家存档与设置会失效） |
| `summary` | 缺了货架会显示 id，很难认 |
| `display.width/height` | 逻辑分辨率。像素风 320×180（1080p 正好 6 倍）；矢量风 960×540 |
| `display.scale` | `integer` 像素风 / `fit` 矢量风 |
| `pointer` | 纯手柄游戏写 `"hidden"`，否则鼠标一直在屏幕上 |
| `players` | `min/max` 是同时游玩人数，最多 4 |

## 6. 数值与金手指

**数值不要写在逻辑里。** 分三层：

```
config.ts   常量      分辨率、颜色、体积        永不变
tuning.ts   可调量    速度、经验、出怪、品质    金手指改这里
main.ts     逻辑      只读 tuning.xxx(base)    不碰数字
```

```ts
// tuning.ts
export const baseline = {
  moveSpeed: (base: number) => base,
  xpNeed: (level: number) => Math.round(10 + level * 7),
};

export function tuned(ctx: GameContext) {
  const cheats = ctx.options;
  return {
    moveSpeed: (base: number) => baseline.moveSpeed(base) * cheats.number('move-speed'),
    xpNeed: (level: number) => baseline.xpNeed(level) / cheats.number('xp-rate'),
  };
}
```

声明金手指（金手指、设置、成就**用同一套 API**，只是 `scope` 不同）：

```ts
// 金手指：数值型，必须给范围
ctx.options.declare({
  id: 'move-speed',
  name: '移动速度',
  description: '方块移动速度倍率。',
  kind: 'number',
  min: 1, max: 3, step: 0.25, defaultValue: 1,
  unit: '×',
});

// 开关型
ctx.cheats.declare({ id: 'god-mode', name: '无敌', severity: 'destructive' });

// 设置项
ctx.options.declare({
  id: 'cursor-style',
  name: '指针样式',
  kind: 'choice',
  scope: 'setting',
  defaultValue: 'cross',
  choices: [
    { value: 'cross', label: '十字' },
    { value: 'dot', label: '圆点' },
  ],
});

// 成就（只读）
ctx.options.declare({ id: 'clicks', name: '累计点击', scope: 'status' });
```

读取：

```ts
ctx.options.number('move-speed')   // 已夹在范围内并对齐步进
ctx.options.enabled('god-mode')    // 布尔
ctx.options.choice('cursor-style') // 字符串
```

四条规则：

1. 逻辑里不写裸数值，一律走 `tuning.xxx(base)`
2. 金手指 `id` 发布后不改
3. 只改**速率**，不改**进度结构**（经验倍率可以，直接改等级不行）
4. 用过金手指的局在存档里打标记

**不要自己写开关界面**，面板由平台渲染。

## 7. 存档

```ts
const saved = ctx.storage.get<State>('state');
ctx.storage.set('state', state);
```

- 按 `game.json` 的 id 隔离，不同游戏互不可见
- 同步写内存，约每秒落盘一次；暂停、退出、页面卸载时立刻落
- **关键进度立刻 set**，不要攒到关卡结束——Android 可能直接杀进程
- 单游戏上限 1MB，值必须是可序列化的纯数据

## 8. 素材

放 `src/../assets/`，游戏里用相对路径：

```ts
const tile = await ctx.assets.image('tile.png');   // → assets/tile.png
const level = await ctx.assets.json('level1.json');
```

- **在 `create` 里预加载**，不要在 `render` 里加载
- 路径相对 `assets/`，不要写 `assets/tile.png`
- 允许：png、jpg、webp、gif、json、txt、ogg、mp3、wav

## 9. 构建

`vite.config.ts` 必须做到三件事：

```ts
export default defineConfig({
  build: {
    target: 'chrome87',                                  // 平台基线
    lib: { entry: 'src/main.ts', formats: ['es'], fileName: () => 'game.js' },
    rollupOptions: { output: { inlineDynamicImports: true } },
    // 不要写 external: ['@hearthbox/sdk']
  },
});
```

**SDK 必须内联**：包在 blob URL 下执行，裸说明符解析不了，import maps 又要 Chromium 89+。

自检：产物里不允许有 `import` 语句。

## 10. 排查

| 现象 | 原因 |
|---|---|
| 黑屏没报错 | `create` 里 await 了不 resolve 的东西；或 `render` 没画东西 |
| `Failed to resolve module specifier` | 产物有裸导入，SDK 没内联 |
| `SyntaxError` 在 blob URL | 用了基线以上语法，检查 target 是否 `chrome87` |
| 手柄按了没反应 | 读了 `navigator.getGamepads()` 而不是 `ctx.input` |
| 鼠标点不准 | 自己乘了缩放倍数，`pointer.x` 已经是逻辑像素 |
| 刷新后存档没了 | 只写在 `dispose` 里；或者没用 `ctx.storage.set` |
| 画面糊 | `pixelArt: true` 却在画矢量；或逻辑分辨率太高 |
| 改了代码没变化 | 游戏是构建产物，要重新 `npx vite build` |
| HUD 位置不对 | 用了物理像素坐标，应该用 `ctx.width/height` |

## 11. 开发时的调试

```
play.html?...&debug=1&seed=42&speed=0.5
```

- `debug=1`：`ctx.debug.enabled` 为 true
- `seed=42`：`ctx.debug.seed` 拿到 42，配合 `ctx.random` 可复现整局
- `speed=0.5`：`update` 的 dt 减半，慢放观察

`ctx.debug.stepFrames(n)` 暂停主循环手动推帧，用来复现"第 N 帧才出现"的 bug。

## 12. 什么不该做

- 不要在游戏里自己实现暂停菜单、设置页、金手指面板——平台的事
- 不要假设有 `window`、`document` 之外的全局对象
- 不要在 `update`/`render` 里每帧创建对象、数组、闭包
- 不要为"只支持手柄"写分支，输入层已经统一了
- 不要用 `Math.random()`，用 `ctx.random` 才能复现
