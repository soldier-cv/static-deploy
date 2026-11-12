---
name: server-88-deploy
description: Standard operating procedure and automation for deploying services on LAN server 88 (100.64.0.88). Use whenever deploying, updating, inspecting, or managing containers or services on server 88, or working with /opt/deploy and /data paths.
version: 1.0.0
---

# 局域网 88 服务器 (100.64.0.88) 部署与运维技能

本技能规定了在局域网 **88 服务器**（`100.64.0.88`）上部署、升级与管理 Docker 化应用的标准规范、约束条件及自动化流程。

---

## 1. 主机基本信息与凭据

| 配置项 | 规范值 | 说明 |
|---|---|---|
| **主机 IP** | `100.64.0.88` | 局域网主机，操作系统 Ubuntu 24.04 LTS |
| **SSH 私钥** | `C:\Users\HXD\.ssh\xl` | Windows 本机密钥路径 |
| **SSH 用户** | `root` 或 `xl` | `xl` 具备免密 `sudo` 权限，已在 `~/.ssh/config` 配置别名 |
| **容器引擎** | Docker 29.x + Docker Compose v5.x | 支持 Compose 原生规范 |

---

## 2. 核心架构约束 (Core Principles)

### 2.1 目录划分标准
*   **发布物与配置目录**：`/opt/deploy/<项目名称>/`
    *   包含：`docker-compose.yml`、`.env`、`OPERATIONS.md` 及项目专用启动脚本。
    *   **权限规范**：`/opt` 下文件操作若使用非 root 账号登录**必须带 `sudo`**。
*   **数据持久化目录**：`/data/<项目名称>/`
    *   持久化挂载所有业务数据、数据库数据、上传文件，确保**容器重建/销毁时不丢数据**。
    *   **权限规范**：部署前必须预先建立好 `/data/<项目名称>` 并赋予合适的权限（默认 `chmod 755`；若容器以非 root 运行如 postgres 70/redis 999，需预先设置 `chown` 或 `chmod 777`）。

### 2.2 环境变量统一管理
*   **统一使用 `.env`**：所有可变参数（端口号、数据目录、密码密钥、时区、资源限制）统一放项目目录 `/opt/deploy/<项目>/.env`。
*   **禁止硬编码**：`docker-compose.yml` 中必须通过 `${VARIABLE_NAME}` 引用。
*   **重载规则**：修改 `.env` 之后，`docker compose restart` **不会**加载新变量，**必须执行 `docker compose up -d --force-recreate`**。

### 2.3 容器硬限制与日志轮转 (Mandatory)
为了防止单个容器异常消耗过多系统资源或撑爆磁盘，每个容器**必须显式声明**：
1.  **日志限制（Log Rotation）**：
    ```yaml
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
    ```
2.  **资源限制（CPU & Memory Limits）**：
    ```yaml
    deploy:
      resources:
        limits:
          cpus: '1.0'
          memory: 512M
        reservations:
          cpus: '0.1'
          memory: 64M
    ```
3.  **重启策略**：统一设置 `restart: unless-stopped`。

---

## 3. 标准部署工作流 (Deployment Workflow)

在执行任何部署操作前，按以下六个阶段执行：

```
[1. 端口与资源排查] ──> [2. 创建目录与赋权] ──> [3. 准备 .env & compose]
                                                         │
[6. 生成 OPERATIONS] <── [5. 健康检查验证] <── [4. 传输并启动]
```

### 第一步：排查宿主机端口冲突
在分配端口前，远程检查目标端口是否已被已有服务占用：
```powershell
ssh -i "C:\Users\HXD\.ssh\xl" root@100.64.0.88 "ss -tulpn | grep :<PORT> || echo 'PORT_FREE'"
```
> [!WARNING]
> 88 服务器已部署多个核心服务（Sub2API: 8280, N8N: 5678, PostgreSQL: 5432, Redis: 13302, Grafana: 3000, Prometheus: 9091, Registry: 5000 等），分配端口前务必确保未冲突。

### 第二步：创建部署与持久化目录
```powershell
ssh -i "C:\Users\HXD\.ssh\xl" root@100.64.0.88 "mkdir -p /opt/deploy/<项目名称> /data/<项目名称> && chmod 755 /data/<项目名称>"
```

### 第三步：配置 Compose 与 .env
参照模板目录：
*   Compose 模板：[docker-compose.template.md](./references/compose-template.md)
*   配置模板：`.env.template`（未随包提供：按项目所需变量自行创建）

### 第四步：文件传输与启动
> [!TIP]
> 从 Windows 发送文本到 Linux 时，为避免 PowerShell 字符串转义或 `\r\n` 换行符破坏 YAML 语法，推荐使用 **Base64 传输** 或辅助脚本：
```powershell
$content = Get-Content -Raw -Encoding UTF8 .\docker-compose.yml
$b64 = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($content))
ssh -i "C:\Users\HXD\.ssh\xl" root@100.64.0.88 "echo '$b64' | base64 -d > /opt/deploy/<项目名称>/docker-compose.yml"
```
传输完成后启动服务：
```powershell
ssh -i "C:\Users\HXD\.ssh\xl" root@100.64.0.88 "cd /opt/deploy/<项目名称> && docker compose up -d --force-recreate"
```

### 第五步：验证与健康检查
1. 检查容器状态：
   ```powershell
   ssh -i "C:\Users\HXD\.ssh\xl" root@100.64.0.88 "cd /opt/deploy/<项目名称> && docker compose ps"
   ```
2. 查看启动日志：
   ```powershell
   ssh -i "C:\Users\HXD\.ssh\xl" root@100.64.0.88 "cd /opt/deploy/<项目名称> && docker compose logs --tail=50"
   ```
3. 本机 Curl 探测：
   ```powershell
   curl http://100.64.0.88:<PORT>/<HEALTH_PATH>
   ```

### 第六步：固化运维文档
在 `/opt/deploy/<项目名称>/OPERATIONS.md` 生成运维手册，参考 [operations-template.md](./references/operations-template.md)。

---

## 4. 常见问题与踩坑指南 (Pitfalls & Solutions)

1.  **Redis Command 参数黏连报错**：
    *   *问题*：YAML 折叠语法 `command: > redis-server \ --save 60 1` 会把反斜杠换行压成空格，导致将 `--save` 当成配置文件路径。
    *   *解决方案*：在 compose 中一律使用 JSON 数组写法：
        ```yaml
        command: ["redis-server", "--save", "60", "1", "--appendonly", "yes", "--appendfsync", "everysec"]
        ```
2.  **PostgreSQL Bind Mount 数据不落盘**：
    *   *问题*：挂载 `/data/<项目>/postgres` 时，容器内若未显式声明 `PGDATA`，可能挂载未生效或初始化失败。
    *   *解决方案*：显式配置环境变量 `PGDATA=/var/lib/postgresql/data`。
3.  **权限不足导致容器启动失败**：
    *   *问题*：容器以非 root 用户运行时（如 UID 1000、999、70），宿主机 `/data/<项目>` 默认 root 属主导致写权限被拒绝。
    *   *解决方案*：根据容器运行用户执行 `chown -R <uid>:<gid> /data/<项目>` 或调整读写权限。
4.  **修改环境变量不生效**：
    *   *问题*：直接 `docker compose restart` 不会更新已挂载的环境变量。
    *   *解决方案*：必须执行 `docker compose up -d --force-recreate`。

---

## 5. 本地快捷辅助脚本

技能目录下提供 Windows PowerShell 自动化运维脚本：[deploy-helper.md](./references/deploy-helper.md)

```powershell
# 1. 检查服务器连接与环境
.\scripts\deploy-helper.ps1 -Action check-server

# 2. 检查端口是否被占用
.\scripts\deploy-helper.ps1 -Action check-port -Port 8080

# 3. 从本地目录一键部署至 88 服务器
.\scripts\deploy-helper.ps1 -Action deploy -ProjectName myapp -LocalDir "C:\projects\myapp\deploy"

# 4. 查看运行状态
.\scripts\deploy-helper.ps1 -Action status -ProjectName myapp

# 5. 查看实时日志
.\scripts\deploy-helper.ps1 -Action logs -ProjectName myapp

# 6. 重建容器（更新 .env 或配置后）
.\scripts\deploy-helper.ps1 -Action recreate -ProjectName myapp

# 7. 下线服务
.\scripts\deploy-helper.ps1 -Action down -ProjectName myapp
```

## 随附资产对照（分发通道只放行 Markdown）

| 原始路径 | 技能包内位置 |
|---|---|
| `scripts/deploy-helper.ps1` | `references/deploy-helper.md`（`## scripts/deploy-helper.ps1` 节） |
| `templates/docker-compose.template.yml` | `references/compose-template.md`（`## templates/docker-compose.template.yml` 节） |
| `templates/OPERATIONS.template.md` | `references/operations-template.md`（`## templates/OPERATIONS.template.md` 节） |

> 本技能的 PowerShell 脚本与 Compose 模板已转写为 Markdown；`deploy-helper.ps1` 按节还原后可直接执行。

## 更新与升级（统一走 skillctl）

更新源：`http://100.64.0.88:8088/.well-known/skills/index.json`

```bash
./skillctl.py list                                  # 本地各技能版本 vs 注册表
./skillctl.py update --to <你的技能目录>             # 默认只检测
./skillctl.py update --to <你的技能目录> --apply     # 确认后升级（逐文件 sha256 校验）
```
