---
name: static-deploy-mcp
description: Use when 用户要把原型 / HTML / 截图 / 图片 / 静态文件发布到服务器并拿到一个可访问链接，或抱怨「手机上打不开你生成的东西 / 只看得到本地路径」。
version: 1.0.0
---

# static-deploy 原型与图片分发 MCP（跨机器使用）

## 何时用
- 用户说「把这个页面/原型发我」「给我个链接，我手机上看」「把这张图传到服务器」
- 你在本地生成了 HTML 原型、截图或图片，用户看不到本地路径（典型场景：agent 跑在用户的 Windows 电脑上，人在手机上）
- 需要把成品变成一个**能直接点开**的网址

## 第一步：确认工具是否可用
本机 Hermes 的工具表里应有 `mcp__static_deploy__*`（发布/上传/列表类工具）。
- **没有** → 按 [references/config-snippet.md](references/config-snippet.md) 加配置并重启网关（本服务局域网免鉴权，配置只需一个 URL）。
- **有** → 直接调工具发布；返回的链接要**换成本机可达的对外地址**再发给用户（见 references/publish-patterns.md 的坑）。

## 端点（局域网免鉴权）
| 用途 | 地址 |
|---|---|
| MCP 端点（客户端配置用） | `http://100.64.0.88:8088/mcp` |
| 权威接入文档（工具名与参数以它为准） | `http://100.64.0.88:8088/setup` |
| 看板（人工浏览/删除） | `http://100.64.0.88:8088/` |

本服务**只在局域网**（ZeroTier `100.64.0.88`），没有公网入口；给用户的链接必须是这个内网地址。

## 不要做的事
- **不要凭本 skill 猜工具名或参数**：以 `<入口>/setup` 与 `tools/list` 实测为准（本 skill 有意不复述清单）。
- 管理类操作（浏览、删除）**不调 MCP**，让用户自己在看板做。
- 不要把发布出去的内容当私密数据（服务无鉴权，只放可公开的原型/图片）。

## 参考
- [references/config-snippet.md](references/config-snippet.md) — 客户端配置、技能包安装（含内网限制）
- [references/publish-patterns.md](references/publish-patterns.md) — 发布 HTML/图片的套路与链接改写
- [references/troubleshooting.md](references/troubleshooting.md) — 上传失败、链接打不开、目录残留
