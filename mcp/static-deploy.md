# static-deploy MCP — 接入指引

把本机开发的原型、生成的图片推到内网 88 服务器，拿到手机可直接点开的链接。

## 给 Agent 装能力（一次安装，之后它会自己判断何时调用）

本服务把「何时该调这个 MCP、怎么接入、怎么排障」打包成 agent 技能包，自托管在这里：

- 技能索引：`http://100.64.0.88:8088/.well-known/skills/index.json`
- 安装（推荐，不依赖任何开关）：
  ```bash
  D=~/.hermes/skills/devops/static-deploy-mcp
  B=http://100.64.0.88:8088/.well-known/skills/static-deploy-mcp
  mkdir -p "$D/references"
  for f in SKILL.md references/config-snippet.md references/publish-patterns.md references/troubleshooting.md; do
    curl -fsSL "$B/$f" -o "$D/$f" || echo "FAIL $f"
  done
  ```
- 或一条命令装（需放行内网地址）：`HERMES_ALLOW_PRIVATE_URLS=1 hermes skills install http://100.64.0.88:8088/.well-known/skills/static-deploy-mcp/SKILL.md --category devops --yes`
  —— Hermes 的技能抓取带 SSRF 防护，默认屏蔽 `100.64.0.0/10` 等私网地址；**MCP 端点本身不受此限制**。
- 其它 agent（Claude Code / Cursor）：把 MCP 配置片段写进其配置，并把技能里的「何时调用」提示词粘进 `CLAUDE.md` / `AGENTS.md`。

## 服务地址（局域网，免鉴权，无需任何密码）

| 用途 | 地址 |
|---|---|
| MCP 端点 | `http://100.64.0.88:8088/mcp` |
| 总览看板 | `http://100.64.0.88:8088/` |
| 健康检查 | `http://100.64.0.88:8088/api/health` |

## 接入方式（二选一）

### 方式一：远程 MCP（零安装，推荐）

Agent 直连内网端点，不需要装脚本、不需要密钥。

**Cursor / Claude Code / 通用 JSON 客户端**

```json
{
  "mcpServers": {
    "static-deploy": { "url": "http://100.64.0.88:8088/mcp" }
  }
}
```

**Hermes**（`/home/xl/.hermes/profiles/<profile>/config.yaml`）

```yaml
mcp_servers:
  static-deploy:
    url: http://100.64.0.88:8088/mcp
    enabled: true
```

工具：

| 工具 | 参数 | 说明 |
|---|---|---|
| `deploy_static_project` | `project_name`、`description`、`files`（`{相对路径: 文本内容}`）或 `html`（单文件简写）、`entry_file`（可选，默认 `index.html`） | 部署原型，返回手机直达链接 |
| `upload_image` | `project_name`、`description`、`filename`（如 `poster.png`）、`image_base64`（可带 `data:image/png;base64,` 前缀） | 上传设计图，返回手机直达链接 |
| `list_projects` | 无 | 列出最近已部署的原型与图片 |

### 方式二：本地 MCP（本机有文件，直接传路径）

Agent 在本机读文件、打包、流式上传，适合整目录原型与大图（内容不进上下文）。

```powershell
# 1. 一条命令拿到脚本（无需 git、无需 pip）
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

工具与方式一相同，只是路径类参数改为本地路径：`deploy_static_project` 用 `source_path`（本地目录或 HTML 文件绝对路径），`upload_image` 用 `image_path`。

顺带拿到命令行工具（可选，手动上传用）：

```powershell
curl.exe -o "$env:USERPROFILE\.static-deploy-cli.py" http://100.64.0.88:8088/client/deploy_cli.py
python "$env:USERPROFILE\.static-deploy-cli.py" --path "D:\project\demo" --name "演示原型" --desc "手机端预览"
```

## 验证

对 agent 说：`用 static-deploy 的 list_projects 看看有哪些项目`。返回项目列表即接入成功。

## FAQ

**Q: 部署后手机打不开？**
手机要在能访问 `100.64.0.88` 的网络（连 ZeroTier，或与服务器同一局域网）。

**Q: 不想用 MCP，能一条命令上传吗？**

```powershell
$d="D:\project\demo"; $z="$env:TEMP\demo.zip"
Compress-Archive -Path "$d\*" -DestinationPath $z -Force
curl.exe -X POST "http://100.64.0.88:8088/api/deploy" `
  -H "X-Project-Name: 演示原型" -H "X-Project-Desc: 手机端预览" `
  -H "X-Project-Type: html" -H "X-Entry-File: index.html" `
  --data-binary "@$z"
```

返回 JSON 的 `url` 前拼 `http://100.64.0.88:8088` 就是手机直达链接。

**Q: 入口不是 index.html，或原型在子目录里？**
传 `entry_file`，例如 `demo/index.html`（方式一）；CLI 用 `--entry demo/index.html`。

**Q: 上传失败怎么排查？**
先 `curl http://100.64.0.88:8088/api/health`，应返回 `{"status":"ok"}`；不通即网络问题，不是 MCP 的问题。
