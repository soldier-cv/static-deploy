# ImageGallery 生图 MCP — 安装指引

> 本文件是集中副本，来源为 ImageGallery 服务自带的公开文档路由
> `http://100.64.0.88:30898/docs/mcp-setup.md`（随镜像发布）。更新时以服务端为准，并同步本文件。

## 服务地址

```
http://100.64.0.88:30904/mcp
```

> 仅限内网访问。不在内网请先连 VPN 或咨询管理员。

## 三步接入

### 第 1 步：拿令牌

浏览器打开画廊 `https://gallery.xl.codec.top`（公网）或 `http://100.64.0.88:30898`（局域网） → 登录 → 「令牌管理」 → 复制你的令牌（形如 `tok_xxxxxxxx`）。

### 第 2 步：写入客户端配置

**Hermes**（`~/.hermes/profiles/<你的profile>/config.yaml`）：

```yaml
mcp_servers:
  imagegallery:
    url: http://100.64.0.88:30904/mcp
    headers:
      X-API-Token: ***
    enabled: true
```

**Claude Code**（`~/.claude.json` 或项目 `.mcp.json`）：

```json
{
  "mcpServers": {
    "imagegallery": {
      "type": "http",
      "url": "http://100.64.0.88:30904/mcp",
      "headers": { "X-API-Token": "tok_你的令牌" }
    }
  }
}
```

**Cursor / 其他 OpenAI 风格客户端**（`mcp.json`）：

```json
{
  "mcpServers": {
    "imagegallery": {
      "url": "http://100.64.0.88:30904/mcp",
      "headers": { "X-API-Token": "tok_你的令牌" }
    }
  }
}
```

### 第 3 步：重启客户端，验证

对 agent 说：`用 imagegallery 的 get_info 查一下可用模型`，返回模型列表即接入成功。

## 可用工具

| 工具 | 用途 |
|---|---|
| `generate_image` | 生图（同步等待 10~90 秒；`prompt` 必填，`model`/`size`/`reference_image`/`tags` 可选） |
| `get_task` | 超时兜底查询，参数 `task_id` |
| `get_info` | 查可用模型、积分价与余量 |

## 常见问题

**Q: 超时了怎么办？**
`generate_image` 最多等 25 秒，慢任务返回 `task_id` + `status:'generating'`，这是正常流程不是失败。间隔 20~30 秒调用 `get_task(task_id)` 轮询至 `done` 或 `error`，图不会丢。

**Q: 返回的 url 怎么下载？**
在 URL 后附加 `?token=你的令牌`（例：`curl -o out.png "...xxx.png?token=tok_xxx"`）。URL 有效期 7 天。

**Q: 我生成的图别人能看到吗？**
看不到。每个令牌独立画廊隔离，仅管理员可查看全局。

**Q: 令牌泄露了怎么办？**
画廊「令牌管理」页一键轮转，旧令牌立即失效。

**Q: 连不上？**
先 `curl http://100.64.0.88:30904/health` 确认服务在线（应返回 `{"status":"ok"}`），不通则检查内网连通性。
