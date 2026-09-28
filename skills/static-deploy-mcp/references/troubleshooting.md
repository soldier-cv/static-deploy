# 故障对照表

| 现象 | 含义 | 处置 |
|---|---|---|
| `File is not a zip file` | 用了 REST 上传口发单文件 | 单文件走 MCP 工具（html 参数），或用 zip |
| 返回链接 404 | 打包入口解析回落（zip 带顶层目录） | 重新发布为自包含单文件 HTML；发布后必 curl 校验 |
| 用户点开是 `127.0.0.1` / `localhost` | 链接没改写 | 换成 `http://100.64.0.88:8088/...` 再发 |
| 手机打不开链接 | 手机没连内网（ZeroTier/VPN） | 让用户连上内网；本服务没有公网入口 |
| `registered 0 tool(s) (1 failed: static-deploy)` | 客户端没连上 | 先 `curl -X POST http://100.64.0.88:8088/mcp` 发 initialize（`GET /mcp` 返 405 是协议要求，不是故障） |
| 上传超限 | nginx / 解析层体积上限 | 压缩图片或拆分文件；错误信息里会给上限 |
