---
name: hearthbox
description: Use when 进行 Hearthbox（炉边）自制游戏平台的全部开发工作：写游戏、设计玩法、改平台本体、配置金手指/设置项/成就、调试运行时与货架。触发词：hearthbox、炉边、写游戏、defineGame、game.json、金手指、货架、运行时、平台。
version: 1.0.0
author: Hermes coding agent
license: MIT
metadata:
  hermes:
    tags: [game, hearthbox, sdk, defineGame, cheats, runtime]
    related_skills: [ui-diff, webapp-testing, project-repo-standards]
---

# Hearthbox（炉边）

> 版本记录：1.0.0 首发 Hearthbox 平台开发与游戏接入规范，补齐标准 frontmatter、相关技能与升级段。

> **相关技能**：
> - [ui-diff](../ui-diff/SKILL.md) — 游戏与平台界面跨端截图比对验收
> - [webapp-testing](../webapp-testing/SKILL.md) — Web 运行时 Playwright 交互与自动化测试
> - [project-repo-standards](../project-repo-standards/SKILL.md) — 项目工程结构与代码规范

一个手柄优先的自制游戏平台：壳 + 货架 + 游戏包。游戏只针对 SDK 写，不针对操作系统。

**先判断用户要做哪件事，再读对应的参考文件。** 别一次读全部。

## 必须搭配使用的通用技能

**这些技能不能省。** 本技能只讲平台约束（契约、输入、存档、构建），
不教游戏该怎么做。设计失误大多来自漏掉下面这些：

| 场景 | 必须加载 | 补什么 |
|---|---|---|
| 做 2D 游戏（本项目默认） | `2d-games` | sprite 组织、tilemap、碰撞、相机、屏幕震动 |
| 定玩法、核心循环、数值平衡 | `game-design` | GDD 结构、玩家心理、难度曲线 |
| 定美术风格、做素材 | `game-art` | 视觉风格、素材管线、动画 |
| 做音效与音乐 | `game-audio` | 音效设计、自适应音频 |
| 不确定该用哪套 | `game-development` | 它是个编排技能，会路由到上面几个 |
| 验收要截图对比/交互测试 | `ui-diff` / `webapp-testing` | 自动截图、视觉回归与浏览器交互 |
| 设计模块边界 | `codebase-design` | 深模块、接口放置 |

**规则**：

- 只要涉及**玩法设计**，先加载 `game-design` 再动手写代码。
- 只要涉及**画面**，先加载 `game-art`，把色板和素材规格定死。
- 只要涉及**2D 渲染与碰撞**，加载 `2d-games`。
- 这三条是硬要求，不是"看情况"。

**为什么写在这里**：技能是按 description 自动匹配的。
"写一个游戏"这种请求可能只命中本技能，漏掉游戏设计方法论，
结果就是代码能跑但玩法空洞——这是最常见的失误。

| 用户在做什么 | 读哪个 | 大概要多久 |
|---|---|---|
| 要写一个新游戏 | `references/game-dev.md` | 一天起 |
| 有个玩法想法，要理清怎么落地 | `references/game-design.md` | 先花一小时 |
| 要改平台本身（运行时、壳、SDK） | `references/platform.md` | 看改动面 |

参考文件在 `references/` 目录下，用相对路径读。**只有确实需要时才读**，不要为了"了解一下"把三份都读进来。

## 这个平台是什么样

```
玩家：打开壳 → 看到货架 → 点游戏 → 玩
开发：写游戏 → 打包 → 放到货架
```

三层：

```
壳（Windows / Android TV）   提供窗口、输入、屏幕常亮
  └ 平台（运行时 + SDK）      主循环、输入统一、存档、金手指
      └ 游戏                 只管 update 和 render
```

**游戏不碰平台细节。** 循环归平台、输入归平台、存档归平台、UI 面板归平台。游戏只写逻辑和绘制。

## 三条最容易踩的规则

不论做哪件事，这三条都成立：

1. **游戏是一个模块，不是一个网页。** 不自己 `requestAnimationFrame`、不自己读 `navigator.getGamepads()`、不自己写 `localStorage`。全部走 `ctx`。
2. **数值不写在逻辑里。** 常量（分辨率、颜色）放 `config.ts`，可调量（速度、经验）放 `tuning.ts`，逻辑只读。金手指和难度都改这一层。
3. **金手指、设置、成就是同一套东西。** 都是"游戏声明一个可调项，平台渲染" 。用 `ctx.options.declare()`，靠 `scope` 区分进哪个面板。

## 现在能做什么

| 能做 | 不能做 |
|---|---|
| 在 PC 浏览器里开发和玩 | 打包成 `.hbx`（M2） |
| 手柄、键盘、鼠标三种输入 | 从货架安装游戏（M2） |
| 存档、金手指、设置、成就 | 在电视上跑（M4，要真机） |
| 改平台并跑测试 | 公网分发（M5） |

游戏放在**工作区根目录**，和平台仓库平级：

```
hearthbox-projects/
  hearthbox/        平台
  my-game/          你的游戏
```

`pnpm dev` 会自己扫到。启动后开 `127.0.0.1:5199`。

## 平台仓库在哪

`hearthbox/`。里面的文档是**事实来源**，技能只是操作步骤。两者冲突时以仓库 `docs/` 为准。

| 想查什么 | 看哪份 |
|---|---|
| 游戏契约（生命周期、ctx 有什么） | `docs/game-sdk.md` |
| 三层输入 | `docs/input.md`、`docs/pointer.md` |
| 金手指与数值分层 | `docs/cheats.md`、`docs/tuning.md` |
| 可调项架构、未来扩展 | `docs/plugins.md` |
| 卡带格式、资源上限 | `docs/cartridge-contract.md` |
| 兼容基线、性能预算 | `docs/compatibility.md` |
| 为什么这样设计 | `docs/decisions.md` |
| 新游戏跑不起来 | `docs/local-dev.md` |

---

## 参考文件说明

### `references/game-dev.md`

写游戏的全部技术细节：目录结构、`defineGame` 入口、`ctx` 的每个字段、三层输入怎么用、`game.json` 每个字段的含义、金手指与设置怎么声明、存档怎么写、素材怎么加载、构建配置、排查表、调试参数。

**什么时候读**：用户要动手写代码时。

### `references/game-design.md`

设计流程：先做什么后做什么，怎么避免返工。玩法一页纸、美术规范、系统表、垂直切片、验收。核心是"把会返工的东西前置"。

**什么时候读**：用户说"我有个想法"、还不确定能不能做、或者问顺序该怎么排时。

### `references/platform.md`

改平台本体：代码地图、热路径纪律、存储迁移、测试怎么写、提交前检查。

**什么时候读**：用户要改运行时、SDK 契约、壳页面，或者排查平台侧的问题。

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
