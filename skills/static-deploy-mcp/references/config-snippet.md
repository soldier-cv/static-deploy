# 客户端接入配置片段

## Hermes（自托管/本机）
目标 profile 的 `config.yaml`：
```yaml
mcp_servers:
  static-deploy:
    url: http://100.64.0.88:8088/mcp
    enabled: true
```
本服务**免鉴权**，不需要 token。改完重启对应网关生效。

生效判据（该 profile 日志）：`tools.mcp_tool: MCP server 'static-deploy' (HTTP): registered N tool(s)`；出现 `registered 0 tool(s) (1 failed: ...)` 说明没连上，先 `curl -X POST http://100.64.0.88:8088/mcp`（initialize）看是否 200。

## Claude Code / Cursor 等标准 MCP 客户端
```json
{
  "mcpServers": {
    "static-deploy": { "type": "http", "url": "http://100.64.0.88:8088/mcp" }
  }
}
```

## 技能包安装（本文件的来源）
```bash
D=~/.hermes/skills/devops/static-deploy-mcp
B=http://100.64.0.88:8088/.well-known/skills/static-deploy-mcp
mkdir -p "$D/references"
for f in SKILL.md references/config-snippet.md references/publish-patterns.md references/troubleshooting.md; do
  curl -fsSL "$B/$f" -o "$D/$f" || echo "FAIL $f"
done
```
- 该服务只有内网入口，**用 `hermes skills install` 直接装会被 Hermes 的 SSRF 防护拦下**（默认屏蔽 `100.64.0.0/10` 等私网地址，报 `Could not download`）。要一条命令装，需加开关：
  ```bash
  HERMES_ALLOW_PRIVATE_URLS=1 hermes skills install http://100.64.0.88:8088/.well-known/skills/static-deploy-mcp/SKILL.md --category devops --yes
  ```
- 上面的 curl 版本不依赖任何开关，推荐作为默认做法。

## 非 Hermes agent 的「何时调用」提示（粘进 CLAUDE.md / AGENTS.md）
```
原型/图片分发：本地生成的 HTML、截图、图片要让用户在手机上看到时，用 static-deploy MCP 发布，
把返回的链接换成 http://100.64.0.88:8088 开头的地址再发人。参数以 http://100.64.0.88:8088/setup 为准。
```
