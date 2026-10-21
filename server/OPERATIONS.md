# static-deploy 运维手册

本服务为局域网静态原型与生图展示平台，提供 Web 端直达阅览与 MCP 自动上传能力。

## 1. 基础信息

*   **代码目录**：`/opt/code/static-deploy`
*   **持久化目录**：`/data/static-deploy`（包含 `sites/` 与 `meta/`）
*   **服务端口**：`8088`（可在 `.env` 修改；容器内 API 监听 `8089`）
*   **服务网段**：`http://100.64.0.88:8088/`
*   **容器名**：`static-deploy-web`（nginx:alpine）、`static-deploy-api`（python:3.12-alpine）
*   **时区**：容器 `TZ=Asia/Shanghai`，`created_at` 写本地时间

## 2. 鉴权

`API_TOKEN` 留空（默认）则 `/api/deploy` 与 `DELETE /api/projects/<id>` **不校验**。
设为非空后，上述写接口要求 `Authorization: Bearer <token>`，不匹配返回 401。
健康检查、`/api/projects`、`/mcp` 任何情况下都免鉴权。

**告警：当前默认免鉴权，禁止把 8088 反代到公网。** 要公网访问必须先设非空 `API_TOKEN`，并确认 8088 未对公网开放。

## 3. 常用操作命令

在仓库根目录执行：

```bash
# 查看容器运行状态
docker compose -f server/docker-compose.yml --env-file server/.env ps

# 查看实时日志
docker compose -f server/docker-compose.yml --env-file server/.env logs -f

# 改代码后热重启（bind mount，无需重建镜像）
docker compose -f server/docker-compose.yml --env-file server/.env restart api web

# 更新 .env 或 compose 后拉起
docker compose -f server/docker-compose.yml --env-file server/.env up -d

# 自测 MCP
python3 tools/selftest_mcp.py http://127.0.0.1:8088
```

不要对公网开放 8088。不要 `docker compose down` 除非明确要停服务。

## 4. 备份与数据持久化

所有项目原型与设计图均保存在宿主机 `/data/static-deploy/sites/` 下，元数据保存在 `/data/static-deploy/meta/projects.json`。容器更新或重建不会造成任何数据丢失。

## 5. 上传与解压上限

HTTP 请求体上限 100MB（`MAX_BODY_BYTES`），同时受 nginx `client_max_body_size 110M` 约束，以便超限时由 API 返回 JSON 413。
MCP 内容上限 20MB（`MAX_CONTENT_BYTES`），保持不变。
解压另有三道上限，默认值写在 `server/receiver.py`，可用同名环境变量覆盖（正整数；非法值回落默认）：

*   解压后总量 `ZIP_MAX_TOTAL_BYTES`，默认 2GB
*   解压后单文件 `ZIP_MAX_SINGLE_BYTES`，默认 256MB
*   解压文件数与显式目录数 `ZIP_MAX_FILE_COUNT`，默认各 10000

环境变量只在 api 进程启动时读取。修改后执行 `docker compose -f server/docker-compose.yml --env-file server/.env restart api`。超限会删除该项目的半成品目录，并在 JSON 里给出上限值和建议做法。
