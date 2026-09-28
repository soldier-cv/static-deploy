# static-preview 运维手册

本服务为局域网静态原型与生图展示平台，提供 Web 端直达阅览与 MCP 自动上传能力。

## 1. 基础信息

*   **部署目录**：`/opt/deploy/static-preview`
*   **持久化目录**：`/data/static-preview`（包含 `sites/` 与 `meta/`）
*   **服务端口**：`8088` (可在 `.env` 修改)
*   **服务网段**：`http://100.64.0.88:8088/`

## 2. 常用操作命令

```bash
cd /opt/deploy/static-preview

# 查看容器运行状态
docker compose ps

# 查看实时日志
docker compose logs -f

# 更新 .env 或配置后重载
docker compose up -d --force-recreate

# 停止服务
docker compose down
```

## 3. 备份与数据持久化

所有项目原型与设计图均保存在宿主机 `/data/static-preview/sites/` 下，元数据保存在 `/data/static-preview/meta/projects.json`。容器更新或重建不会造成任何数据丢失。
