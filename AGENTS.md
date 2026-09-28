# AGENTS.md — static-deploy 项目开发指南

## 定位

内网静态资产分发服务：Agent 把本机开发的原型目录 / 生成的图片推到 88 服务器，拿到手机可点开的局域网链接。两个入口共用同一套存储与元数据：Web 看板（人看）、MCP 端点（Agent 用）。

## 运行环境事实

- 代码：`/opt/code/static-deploy`（宿主 git 仓库），由本仓库 compose 直接跑容器
- 数据：`/data/static-deploy/{sites,meta}`（sites 存解包后的原型与图片，meta/projects.json 存元数据）
- 端口：`8088`（宿主）→ nginx 80；Python API 只在容器网络内监听 `8089`
- 容器：`static-deploy-web`（nginx:alpine）、`static-deploy-api`（python:3.12-alpine）
- 服务端只用 **Python 标准库**，零 pip 依赖，新增能力不得引入第三方包
- `receiver.py` 与 `nginx.conf` 是 bind mount，改完 `docker compose restart` 即生效，无需重建镜像

## 对外路径契约

| 路径 | 用途 |
|---|---|
| `/` | 看板 portal.html |
| `/sites/<project_id>/<entry>` | 原型/图片静态直发 |
| `/api/health`、`/api/projects`、`/api/deploy`（POST）、`/api/projects/<id>`（DELETE） | HTTP API |
| `/mcp` | MCP 端点（streamable HTTP，JSON-RPC 2.0） |
| `/setup` | MCP 接入指引（全生态统一路径） |
| `/client/` | 客户端 MCP 脚本下载（托管仓库 `client-mcp/`） |

## 铁律

1. **局域网默认免鉴权**：`API_TOKEN` 为空即不校验；非空时 `/api/deploy`、`DELETE` 校验 `Authorization: Bearer`。MCP 端点不鉴权。**因此禁止把 8088 反代到公网**，要公网访问必须先设 `API_TOKEN`。
2. **写盘必须落在 project_dir 内**：任何上传内容先做路径规范化与越界检查（Zip Slip、`../`、绝对路径、符号链接一律拒绝或跳过），验收要实测「宿主机其他目录未被创建」。
3. **元数据写入必须原子**（临时文件 + `os.replace`），失败时清理半成品目录。
4. **对外返回的 URL 一律绝对地址**：MCP 与 API 响应用请求 `Host` 头推导基址，禁止硬编码 host；不得对外暴露本地路径。
5. **时区**：容器 `TZ=Asia/Shanghai`，`created_at` 必须是本地时间。
6. **零 emoji、零破折号**（看板与文档文案），图标一律 SVG。
7. **不动别人的东西**：不改 88 服务器其他服务（openresty/registry/CI/数据库），不改 Hermes profile 配置。
8. **不代管其它项目文档**：本仓库不托管其它项目的 MCP 文档；老链接迁移用 302 重定向到目标项目自身地址。
9. **MCP 指引统一挂 `/setup`**：MCP 指引统一挂 `/setup`，不再新增 `/docs/` 类目录。

## 开发工作流

1. 改代码 → `docker compose -f server/docker-compose.yml --env-file server/.env restart api web`（env 变更用 `up -d`）
2. 自测：`python3 tools/selftest_mcp.py http://127.0.0.1:8088`
3. 逻辑分 commit，push 到 GitHub
4. 部署：宿主 `git pull && docker compose up -d`

## 已知坑

- **zip 带单一顶层目录时入口必须逐层找**：曾把入口记成根目录 `index.html` 而实际文件在 `demo/index.html`，看板卡片 404
- **`location = /mcp`（端点）与 `/setup`（指引）必须分开**：指引如果与端点重叠会让 Agent 误把指引地址当端点写入配置
- 上传体积上限由 nginx `client_max_body_size` 与 Python 侧双重限制，超限要返回明确错误（不是 500）
- `projects.json` 并发写要用原子替换，避免截断
