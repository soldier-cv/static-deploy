# static-deploy — 接入指引

> **只需要这一个链接：`http://100.64.0.88:8088/setup`**
> MCP 配置、Agent 提示词、命令行直传、大文件处理、排障，全部在本页。
> 把这一页发给对方即可，不需要再给别的地址。

把本机开发的原型、生成的图片推到内网 88 服务器，拿到手机可直接点开的链接。
局域网访问，**免鉴权，不需要任何密钥**。

---

## 第一步：先按内容大小选路线（重要）

MCP 工具的参数是走对话内容的——**你塞进 MCP 的每一个字节都会变成 token 消耗**。
所以规模一上去就该换通道，不要硬塞。

| 内容情况 | 走哪条 | 说明 |
|---|---|---|
| 单文件 HTML，**< 20 KB** | MCP `deploy_static_project` 的 `html` 参数 | 一次调用搞定，最简单 |
| 多文件文本原型，**总量 < 200 KB** | MCP `files` 参数 | 方便，但已开始明显吃 token |
| **超过 200 KB**、含图片/字体等二进制、或整目录 | **HTTP 直传 zip**（见下） | 内容不进对话，不消耗 token，最快 |
| 单张图片 **< 3 MB** | MCP `upload_image`（base64） | base64 会膨胀约 33% |
| 图片 **> 3 MB** 或批量 | **HTTP 直传**（`X-Project-Type: image`） | 原始字节，不膨胀 |
| **超过 100 MB** | 见「大文件怎么办」 | 需要先拆分或压缩 |

**一句话原则：能走 HTTP 的别走 MCP，MCP 只用来发小内容。**

---

## 服务地址

| 用途 | 地址 |
|---|---|
| MCP 端点 | `http://100.64.0.88:8088/mcp` |
| 直传接口 | `POST http://100.64.0.88:8088/api/deploy` |
| 总览看板 | `http://100.64.0.88:8088/` |
| 健康检查 | `http://100.64.0.88:8088/api/health` |

---

## 方式 A：MCP 接入（一次配置，之后 agent 自己判断何时调用）

### 客户端配置

大多数 MCP 客户端（Cursor / Claude Code / Cline / Windsurf / 各类自研 agent）认这个 JSON 结构：

```json
{
  "mcpServers": {
    "static-deploy": {
      "url": "http://100.64.0.88:8088/mcp"
    }
  }
}
```

如果你的客户端配置格式不同，只需要记住一项：**端点 URL 是 `http://100.64.0.88:8088/mcp`**，传输方式为 Streamable HTTP（POST，无鉴权头）。

### 工具

| 工具 | 参数 | 说明 |
|---|---|---|
| `deploy_static_project` | `project_name`、`description`、`files`（`{相对路径: 文本内容}`）或 `html`（单文件简写）、`entry_file`（可选，默认 `index.html`） | 部署原型，返回手机直达链接 |
| `upload_image` | `project_name`、`description`、`filename`（如 `poster.png`）、`image_base64`（可带 `data:image/png;base64,` 前缀） | 上传图片，返回手机直达链接 |
| `list_projects` | 无 | 列出最近已部署的项目 |

### 让 agent 知道「什么时候该用」

MCP 工具只告诉模型「这个工具有什么参数」，不告诉它「什么场景该用、有什么坑」。
把这段提示词加到你 agent 的系统提示 / `AGENTS.md` / `CLAUDE.md` / 规则文件里：

```
需要把原型、HTML、图片变成手机能打开的链接时，用 static-deploy 的 MCP：
- 端点 http://100.64.0.88:8088/mcp（局域网、免鉴权）
- 小内容（单文件 HTML 且 <20KB）用 deploy_static_project 的 html 参数
- 超过 200KB 或含二进制资源，不要塞进 MCP 参数（会浪费大量 token），
  改用 HTTP 直传：把目录打成 zip 后 POST 到 /api/deploy，见 /setup
- 部署成功后把返回的 abs_url 直接发给用户
```

更完整的版本（含排障）可以读：`http://100.64.0.88:8088/.well-known/skills/static-deploy-mcp/SKILL.md`
—— 如果你的 agent 支持「技能包」机制，把 SKILL.md 及其 `references/` 下三个文件一起放进它的技能目录即可。

---

## 方式 B：HTTP 直传（大内容首选，不消耗 token）

服务端自己收包、解压、登记，内容完全不经过对话上下文。

### 请求约定

```
POST http://100.64.0.88:8088/api/deploy
X-Project-Name: 项目名（支持中文，直接写原文即可）
X-Project-Desc: 一句话描述（可选）
X-Project-Type: html | image        （默认 html）
X-Entry-File:    index.html          （入口文件，默认 index.html）
Content-Type:    application/octet-stream
Body:            zip 包原始字节 / 图片原始字节
```

响应：

```json
{
  "success": true,
  "project_id": "p-20261021-230024-a377",
  "name": "往来原型",
  "url": "/sites/p-20261021-230024-a377/index.html",
  "abs_url": "http://100.64.0.88:8088/sites/p-20261021-230024-a377/index.html",
  "entry": "index.html",
  "created_at": "2026-10-21 23:00:24"
}
```

**直接把 `abs_url` 发给用户即可**，手机可直接打开。

### 各平台命令

**Windows（PowerShell）** — zip 包上传：

```powershell
$d="D:\project\demo"; $z="$env:TEMP\demo.zip"
Compress-Archive -Path "$d\*" -DestinationPath $z -Force
curl.exe -X POST "http://100.64.0.88:8088/api/deploy" `
  -H "X-Project-Name: 演示原型" -H "X-Project-Desc: 手机端预览" `
  -H "X-Project-Type: html" -H "X-Entry-File: index.html" `
  --data-binary "@$z"
```

**Windows（PowerShell）** — 单张图片上传：

```powershell
curl.exe -X POST "http://100.64.0.88:8088/api/deploy" `
  -H "X-Project-Name: 海报" -H "X-Project-Type: image" `
  -H "X-Entry-File: poster.png" `
  --data-binary "@D:\design\poster.png"
```

**macOS / Linux**：

```bash
cd /path/to/demo && zip -r /tmp/demo.zip . -x '.*'
curl -X POST "http://100.64.0.88:8088/api/deploy" \
  -H "X-Project-Name: 演示原型" -H "X-Project-Desc: 手机端预览" \
  -H "X-Project-Type: html" -H "X-Entry-File: index.html" \
  --data-binary "@/tmp/demo.zip"
```

**Python（任何有 python3 的机器，无需第三方库）**：

```python
import json, urllib.request, zipfile, io, os

name, desc, src_dir, entry = "演示原型", "手机端预览", "./demo", "index.html"

buf = io.BytesIO()
with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
    for root, _, files in os.walk(src_dir):
        for fn in files:
            p = os.path.join(root, fn)
            z.write(p, os.path.relpath(p, src_dir))
data = buf.getvalue()

req = urllib.request.Request(
    "http://100.64.0.88:8088/api/deploy", data=data, method="POST",
    headers={"X-Project-Name": name, "X-Project-Desc": desc,
             "X-Project-Type": "html", "X-Entry-File": entry},
)
print(json.load(urllib.request.urlopen(req, timeout=300))["abs_url"])
```

### 可选：本地 MCP / CLI（能读本机磁盘，适合整目录与大图）

如果你的 agent 跑在能访问本机文件的机器上，用这个可以「一句话发整个目录」，内容不进上下文：

```powershell
curl.exe -o "$env:USERPROFILE\.static-deploy-cli.py" http://100.64.0.88:8088/client/deploy_cli.py
python "$env:USERPROFILE\.static-deploy-cli.py" --path "D:\project\demo" --name "演示原型" --desc "手机端预览"
```

也提供 stdio 版 MCP server（本地进程，参数改为本地路径 `source_path` / `image_path`）：

```powershell
curl.exe -o "$env:USERPROFILE\.static-deploy-mcp.py" http://100.64.0.88:8088/client/mcp_server.py
```

```json
{
  "mcpServers": {
    "static-deploy": {
      "command": "python",
      "args": ["C:\\Users\\<你>\\.static-deploy-mcp.py"],
      "env": { "PREVIEW_SERVER_HOST": "100.64.0.88", "PREVIEW_SERVER_PORT": "8088" }
    }
  }
}
```

---

## 大文件怎么办

**上限：单次上传 100 MB**（zip 包或图片原始字节）。

超过或接近上限时的处理顺序：

1. **先压缩**：图片转 WebP（通常省 60~80%），HTML 去掉无用资源，字体只留用到的子集。
2. **剔除不需要的文件**：`node_modules`、`.git`、`*.psd`、原始设计稿、超清原图——这些不用发。
3. **拆分**：把项目拆成多个子项目分别发布（比如 `demo-首页`、`demo-详情`），互相用绝对链接跳转。
4. **视频/超大资源不要走这个服务**：它面向原型预览，不是文件分发。大文件请用别的通道传，原型里引用绝对地址。

zip 包内**必须有一个入口文件**（默认 `index.html`）。如果入口是 `dist/index.html`，传 `X-Entry-File: dist/index.html`。

上传前可先自检体积与内容：

```bash
du -sh ./demo && find ./demo -type f -size +5M
```

---

## 验证

调一次 `list_projects`（MCP），或：

```bash
curl -s http://100.64.0.88:8088/api/health
```

返回 `{"status": "ok"}` 即服务正常。能列出项目即接入成功。

---

## FAQ

**Q: 部署后手机打不开？**
手机需要在能访问 `100.64.0.88` 的网络里（同一局域网，或已接入 ZeroTier 这类虚拟内网）。先让手机浏览器打开 `http://100.64.0.88:8088/api/health` 试。

**Q: 返回的 url 和 abs_url 有什么区别？**
`url` 是相对路径（`/sites/...`），`abs_url` 是可直接发人的完整地址。**用 abs_url**。

**Q: 中文项目名会不会乱码？**
不会。直接写中文原文即可，服务端会正确解码（原文、URL 编码两种写法都支持）。

**Q: 上传报 413？**
请求体超过 100MB（104857600 字节）。响应 JSON 里有 `limit_bytes` 和 `advice`。按「大文件怎么办」压缩或拆分后再 POST `/api/deploy`。MCP 通道上限只有 20MB，而且内容会计入 token，不能用来绕过这个限制。

**Q: zip 很小，却提示解压超过上限？**
压缩比可以很高。服务端限制的是解压之后的结果：总量 2GB、单个文件 256MB、文件数 10000。超限时半成品目录会被删掉，响应 JSON 里有上限值（`limit_bytes` 或 `limit_count`）和建议做法（`advice`）。请删资源或拆项目后重新上传。

**Q: 上传成功但页面白屏？**
多半是入口文件不对或资源路径是绝对路径（`/static/...`）。用相对路径引用资源，并确认 `X-Entry-File` 正确。

**Q: 能删除已发布的项目吗？**
当前不开放删除 API，避免误删。需要清理请到总览看板 `http://100.64.0.88:8088/` 操作，或联系维护者。

**Q: 能公网访问吗？**
不能，也不应该。本服务免鉴权，只在内网/虚拟内网可达。不要把它反代到公网。
