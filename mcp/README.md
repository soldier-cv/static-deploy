# MCP 接入文档中心

各项目的 MCP 接入说明集中在本目录维护，与代码同仓（`static-deploy` 仓库 `mcp/` 目录）。

在线地址（局域网，由本服务直接托管，改完即生效）：

```
http://100.64.0.88:8088/docs/
```

| 项目 | MCP 端点 | 鉴权 | 文档 |
|---|---|---|---|
| static-deploy（原型与图片分发） | `http://100.64.0.88:8088/mcp` | 免鉴权（局域网内直连） | [static-deploy.md](static-deploy.md) |
| ImageGallery（生图工作站） | `http://100.64.0.88:30904/mcp` | 需个人令牌 `X-API-Token` | [image-gallery.md](image-gallery.md) |

新增一个项目：在本目录加 `<项目名>.md`，并在上表登记一行。文档只写「接入步骤 + 客户端配置模板 + 可执行 FAQ」，产品介绍与规则不进安装文档（接口本身就是权威数据源，复述会过时）。
