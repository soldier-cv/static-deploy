# Compose 模板（docker-compose.template.yml）

> 本文件是技能包内可执行资产的 Markdown 转写 —— 分发通道只放行 `SKILL.md` 与 `references/*.md`。
> 落地方法：按各节标题里的路径原样写回磁盘，代码块内容与原文件一致。

## `templates/docker-compose.template.yml`

```yaml
# =============================================================================
# 88 服务器 Docker Compose 标准规范模板
# 部署路径: /opt/deploy/<PROJECT_NAME>/docker-compose.yml
# 持久化路径: /data/<PROJECT_NAME>/
# =============================================================================

services:
  app:
    image: ${APP_IMAGE:-my-app:latest}
    container_name: ${CONTAINER_NAME:-my-app}
    restart: unless-stopped
    security_opt:
      - no-new-privileges:true
    
    # 宿主机端口映射（统一从 .env 读取）
    ports:
      - "${BIND_HOST:-0.0.0.0}:${SERVER_PORT:-8080}:${CONTAINER_PORT:-8080}"
    
    # 持久化数据必须挂载到 /data/<项目>
    volumes:
      - /data/${PROJECT_NAME}/data:/app/data
      # 如有配置文件需要独立挂载:
      # - /opt/deploy/${PROJECT_NAME}/config.yaml:/app/config.yaml:ro
    
    # 环境变量统一注入
    environment:
      - TZ=${TZ:-Asia/Shanghai}
      - APP_ENV=${APP_ENV:-production}
    
    # 容器资源硬限制（防止单容器跑满主机资源）
    deploy:
      resources:
        limits:
          cpus: '${CPU_LIMIT:-1.0}'
          memory: ${MEM_LIMIT:-512M}
        reservations:
          cpus: '${CPU_RESERVATION:-0.1}'
          memory: ${MEM_RESERVATION:-64M}
    
    # 日志轮转限制（防止 Docker 日志撑爆系统盘）
    logging:
      driver: "json-file"
      options:
        max-size: "${LOG_MAX_SIZE:-10m}"
        max-file: "${LOG_MAX_FILE:-3}"
    
    # 健康检查
    healthcheck:
      test: ["CMD-SHELL", "wget -q -O - http://127.0.0.1:${CONTAINER_PORT:-8080}/health || exit 1"]
      interval: 15s
      timeout: 5s
      retries: 3
      start_period: 20s

# 若使用外部已有网络或独立桥接网络
networks:
  default:
    name: ${PROJECT_NAME}-net
    driver: bridge
```
