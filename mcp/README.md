# static-deploy MCP 接入指引

本目录只维护 static-deploy 自身的 MCP 接入指引。

在线访问地址（局域网，由本服务直接托管）：

```
http://100.64.0.88:8088/setup
```

## 文档归属规则

每个项目的 MCP 端点与接入文档由各项目自身独立维护与托管，禁止集中跨项目代管：

1. static-deploy（原型与图片展示中心）：接入文档见 [static-deploy.md](static-deploy.md)（在线地址 `http://100.64.0.88:8088/setup`）。迭代修改同一原型必须复用同一个 `project` slug，主链接 `/sites/<slug>/` 永远是最新内容，`/sites/<slug>/versions/<版本号>/` 保留最近 3 版快照。只有真正不同的方案才不传 `project` 或另起新 slug。不传时仍按标题保留最新 3 版。
2. image-gallery（生图工作站）：文档由其自身服务托管，访问地址为 `http://100.64.0.88:30898/setup`。
3. trade-pulse（交易脉冲数据服务）：文档由其自身服务托管，访问地址为 `http://100.64.0.88:30899/setup`。
