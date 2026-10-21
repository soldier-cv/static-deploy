# 客户端接入配置

## 标准 MCP 客户端（Claude Code / Cursor / Cline / Windsurf 等）

```json
{
  "mcpServers": {
    "static-deploy": {
      "type": "http",
      "url": "http://100.64.0.88:8088/mcp"
    }
  }
}
```

服务**免鉴权**，不需要 token、不需要 header。改完重启客户端生效。

如果你的客户端用别的方式描述传输协议，只需要记住两项：
- **端点 URL**：`http://100.64.0.88:8088/mcp`
- **传输方式**：Streamable HTTP（JSON-RPC over POST）

## 验证是否连上

客户端里应该出现三个工具：`deploy_static_project`、`upload_image`、`list_projects`。
或者直接探一下端点：

```bash
curl -s -X POST http://100.64.0.88:8088/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"probe","version":"0"}}}'
```

返回里带 `serverInfo` 即端点正常。

## 让 agent 知道「什么时候该用」

MCP 工具只告诉模型「有哪些参数」，不告诉它「什么场景该用、有什么坑」。
把下面这段加到你 agent 的系统提示 / 规则文件 / `AGENTS.md` / `CLAUDE.md`：

```
需要把原型、HTML、图片变成手机能打开的链接时，用 static-deploy：
- 端点 http://100.64.0.88:8088/mcp（局域网、免鉴权）
- 小内容（单文件 HTML 且小于 20KB）用 deploy_static_project 的 html 参数
- 超过 200KB、含二进制资源、或整个目录，不要塞进 MCP 参数（会浪费大量 token），
  改用 HTTP 直传：打包成 zip 后 POST 到 http://100.64.0.88:8088/api/deploy，
  请求头带 X-Project-Name / X-Project-Type: html / X-Entry-File
- 发布成功后把返回的 abs_url 直接发给用户（那是手机可打开的完整地址）
- 完整说明见 http://100.64.0.88:8088/setup
```

## 如果支持技能包机制

把本文件所在目录的 `SKILL.md` 与 `references/` 下三个文件一起放进你 agent 的技能目录即可。
文件清单与下载地址见 `http://100.64.0.88:8088/setup`。

不支持技能包的 agent，直接把上面那段「何时该用」的提示词加进规则文件就行——效果等价。
