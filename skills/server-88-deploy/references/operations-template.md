# 运维手册模板（OPERATIONS.template.md）

> 本文件是技能包内可执行资产的 Markdown 转写 —— 分发通道只放行 `SKILL.md` 与 `references/*.md`。
> 落地方法：按各节标题里的路径原样写回磁盘，代码块内容与原文件一致。

## `templates/OPERATIONS.template.md`

````markdown
# {{PROJECT_NAME}} 运维手册

## 1. 服务定位
- **功能描述**: {{PROJECT_DESCRIPTION}}
- **维护人员**: {{MAINTAINER}}

## 2. 部署拓扑
| 资源项 | 物理路径 / 容器内路径 | 说明 |
|---|---|---|
| **配置目录** | `/opt/deploy/{{PROJECT_NAME}}/` | 存放 `docker-compose.yml`、`.env`、`OPERATIONS.md` |
| **持久数据** | `/data/{{PROJECT_NAME}}/` | 容器重启/重建保留数据 |
| **运行容器** | `{{CONTAINER_NAME}}` | Docker 容器实例 |

## 3. 端口与网络
| 宿主机端口 | 容器内端口 | 协议 | 外部访问地址 | 安全级别 |
|---|---|---|---|---|
| `{{SERVER_PORT}}` | `{{CONTAINER_PORT}}` | HTTP | `http://100.64.0.88:{{SERVER_PORT}}` | 局域网公开 / 仅内网 |

## 4. 常用维护命令
```bash
# 1. 进入配置目录
cd /opt/deploy/{{PROJECT_NAME}}

# 2. 查看容器运行状态
sudo docker compose ps

# 3. 实时查看日志
sudo docker compose logs -f {{SERVICE_NAME}}

# 4. 重载配置并重建容器（修改 .env 或 compose 后必须执行 --force-recreate）
sudo docker compose up -d --force-recreate

# 5. 优雅停止
sudo docker compose down

# 6. 进入容器排查
sudo docker exec -it {{CONTAINER_NAME}} /bin/sh
```

## 5. 避坑与注意事项
1. **修改 `.env` 必须重建**：`docker compose restart` 不会重载环境变量，必须执行 `docker compose up -d --force-recreate`。
2. **数据持久化落盘**：所有持久化数据必须且只能放在 `/data/{{PROJECT_NAME}}/`，并保证宿主机目录已有正确权限（如容器非 root 运行时预先 chown）。
3. **资源占用**：如出现 OOM，可调整 `.env` 中的 `MEM_LIMIT` 后重新 `up -d --force-recreate`。
````
