---
name: static-deploy-mcp
description: Use when 用户要把原型 / HTML / 截图 / 图片 / 静态文件发布到服务器并拿到一个可访问链接，或抱怨「手机上打不开你生成的东西 / 只看得到本地路径」。
version: 2.0.0
---

# static-deploy 原型与图片分发 MCP

把本机生成的 HTML 原型、截图、图片推到一台内网服务器，换成一个**手机能直接点开**的网址。

典型场景：agent 跑在用户的电脑上，用户人在手机旁——他看不到 `D:\project\demo\index.html` 这种本地路径，
只想要一个能点开的链接。

## 何时用

- 「把这个页面/原型发我」「给我个链接，我手机上看」「把这张图传到服务器」
- 你生成了 HTML 原型、截图或图片，需要变成可访问网址
- 需要把成品交付给只能在手机上看的人

## 第一步：确认工具是否可用

你的 MCP 客户端工具列表里应该有这三个工具：

| 工具 | 用途 |
|---|---|
| `deploy_static_project` | 发布 HTML 原型，返回可访问链接 |
| `upload_image` | 上传图片，返回可访问链接 |
| `list_projects` | 列出已发布的项目 |

- **有** → 直接调用。
- **没有** → 按 [references/config-snippet.md](references/config-snippet.md) 把端点加进客户端配置，重启客户端使其生效。

## 端点（局域网，免鉴权）

| 用途 | 地址 |
|---|---|
| MCP 端点（客户端配置用） | `http://100.64.0.88:8088/mcp` |
| 权威接入文档（工具名与参数以它为准） | `http://100.64.0.88:8088/setup` |
| 看板（人工浏览） | `http://100.64.0.88:8088/` |

本服务**只在局域网/虚拟内网**可达（`100.64.0.88`），没有公网入口。给用户的链接必须是这个地址。

## 选对通道（重要，直接决定成本）

MCP 工具的参数会变成对话内容——**你塞进去的每个字节都会消耗 token**。

| 内容规模 | 该怎么做 |
|---|---|
| 单文件 HTML，小于 20 KB | 用 `deploy_static_project` 的 `html` 参数，一步到位 |
| 多文件文本，总量小于 200 KB | 用 `files` 参数 |
| **超过 200 KB / 含二进制资源 / 整个目录** | **不要塞进 MCP 参数**，改用 HTTP 直传（见下） |
| 图片小于 3 MB | 用 `upload_image`（base64） |
| 图片大于 3 MB | 改用 HTTP 直传，避免 base64 膨胀 |

HTTP 直传（内容不进对话，零 token 成本）：

```bash
# macOS / Linux
cd /path/to/demo && zip -r /tmp/demo.zip . -x '.*'
curl -X POST "http://100.64.0.88:8088/api/deploy" \
  -H "X-Project-Name: 演示原型" -H "X-Project-Type: html" \
  -H "X-Entry-File: index.html" --data-binary "@/tmp/demo.zip"
```

```powershell
# Windows
$d="D:\project\demo"; $z="$env:TEMP\demo.zip"
Compress-Archive -Path "$d\*" -DestinationPath $z -Force
curl.exe -X POST "http://100.64.0.88:8088/api/deploy" `
  -H "X-Project-Name: 演示原型" -H "X-Project-Type: html" `
  -H "X-Entry-File: index.html" --data-binary "@$z"
```

返回 JSON 里的 `abs_url` 就是可发给用户的链接。

## 不要做的事

- **不要凭本 skill 猜工具参数**：以 `http://100.64.0.88:8088/setup` 和 `tools/list` 实测为准（本 skill 有意不复述完整参数表）。
- **不要把大内容硬塞进 MCP 参数**：超过 200 KB 走 HTTP 直传，否则白白烧掉几万 token。
- 管理类操作（浏览、删除）不调 MCP，让用户自己在看板做。
- 不要把需要保密的内容发上去——服务免鉴权，只适合公开的原型/图片。

## 参考

- [references/config-snippet.md](references/config-snippet.md) — 客户端配置、能力提示词
- [references/publish-patterns.md](references/publish-patterns.md) — 发布 HTML/图片的套路与链接改写
- [references/troubleshooting.md](references/troubleshooting.md) — 上传失败、链接打不开、目录残留
