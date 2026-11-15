---
name: docker-image-ops
version: 1.0.0
description: 当 docker 镜像拉不动或要给 compose 服务升镜像版本时使用。含换镜像域名拉取后 tag 回填、版本判断、备份、重建、验证、回滚。
tags: [docker, compose, mirror, upgrade, rollback, 镜像升级]
triggers:
  - ghcr.io 拉取失败
  - docker pull 超时
  - 镜像升级
  - compose 升版本
---

# Docker 镜像：拉取与升级

> 空间管理见 `devops/docker-disk-cleanup`（本技能只管版本与拉取，不管空间）。

两条铁律：
1. **镜像域名只用于取货，最终 tag 必须是官方原名**；compose 里永远写官方 image 名，绝不改写成镜像域名——换源不用改配置，配置永远干净。
2. **先备份、锁版本、可回滚**；禁止无脑 `compose pull && up -d`。

## A. 拉不动（超时 / TLS / 403）

1. 分清病因：`docker manifest inspect <官方镜像>:<tag>` —— 超时或 TLS 是网络问题；404 / manifest unknown 是标签写错，**别去换源**。
2. 换域名拉：
   - Docker Hub：`docker pull docker.1ms.run/<ns>/<image>:<tag>`
     备选：`docker.m.daocloud.io`（dockerpull.org 已失效，2026-11-13 实测各镜像均 not found，勿再使用）
   - GHCR：`docker pull ghcr.1ms.run/<owner>/<image>:<tag>`
3. tag 回填官方名：`docker tag docker.1ms.run/<ns>/<image>:<tag> <ns>/<image>:<tag>`
4. `docker compose up -d <服务>` —— 本地已命中官方名，不触发重新拉取。
5. 验 digest 一致：`docker inspect <ns>/<image>:<tag> --format '{{index .RepoDigests 0}}'`，
   与 `docker buildx imagetools inspect <官方镜像>:<tag>` 对比。**加速源可能给旧缓存，别把旧镜像当新版本升。**
6. 清中转 tag（可选）：`docker rmi docker.1ms.run/<ns>/<image>:<tag>`
7. 内网 registry `100.64.0.88:5000` 的镜像走 ZeroTier 隧道，不用镜像域名；先 `zerotier-cli listpeers` 查隧道通不通，再怀疑镜像。
8. 长期方案（改 `/etc/docker/daemon.json` 配 registry-mirrors）会重启全部容器，**先问用户**再动。

### A 的补充经验（ghcr 实战）
- **大镜像（>1GB）首次拉取可能超时**，重试一次通常成功（3.35GB hindsight 镜像实测重试后成功）；`ghcr.1ms.run` 返回 302 重定向是正常的。
- 部分镜像同时存在于 ghcr.io 和 Docker Hub。ghcr 持续拉不动时，试 Docker Hub 版本，`docker tag` 回 `ghcr.io/<org>/<img>:<tag>` 让 compose 引用不变；**Hub 版本可能不是同一构建，验证 tag/digest 后再上生产**。
- Alpine 等非 ghcr.io 官方镜像不适用 ghcr 代理（`library/alpine` 在 ghcr.io 上不存在）。

### Pitfall: 更新检测用 digest，不要用 image ID
巡检脚本检测镜像是否有更新，**必须比较 RepoDigests 而非 image ID**：`docker inspect --format '{{.Id}}'` 是本地 ID，partial pull（超时中断）也会改变它 → 误报"已更新"。`RepoDigests` 才是 registry 端权威标识。首次拉取（旧 digest 为空）不算更新，只在已有旧版本且 digest 变化时才报告。

## B. 升级 compose 服务镜像

1. 记现状：`docker inspect <容器> --format '{{.Image}}'`；compose 文件复制 `.bak-<日期>`（只留最近一份）；给旧镜像打 rollback tag：`docker tag <img>:<tag> <img>:rollback-$(date +%Y%m%d)`。
2. 判断能不能升：只升 minor/patch，**不跨大版本**；数据库类（mysql/postgres/redis）跨大版本一律先问。
3. 备份数据：sqlite 类（如 bitwarden `/data`、rustdesk `/db`）停容器后 cp，或 `sqlite3 .backup`；数据库类先 dump。
4. 拉取：`docker compose pull <服务>`；失败转 A 节，**原地重试不超过 2 次**。
5. 重建：`docker compose up -d <服务>`；等 30 秒查 `docker ps` 是否 healthy，再验业务端口（curl / ss -tlnp）。
6. 回滚：image 改回原 tag/digest（或 rollback tag）→ `up -d --force-recreate`。
7. 顺手把 `:latest` 钉成固定 tag（或 digest）：不钉的话重建就换版本，出问题分不清线上是哪版。
8. 时窗：避开早 8-10 点，放凌晨或用户同意的时间。
9. 汇报：服务 / 旧→新版本 / 验证结果 / 回滚点。

### 升级后的两个"假失败"（别急着回滚）
- **新镜像移除了 curl**（hindsight 0.10.0-slim 实测）：升级后容器 unhealthy，根因是新镜像不再内置 curl，而 compose healthcheck 用 `curl` → `exec: "curl": executable file not found`。看 `docker inspect <容器> --format '{{json .State.Health}}'` 的 ExitCode -1 + executable file not found；镜像内有 python3 就把 healthcheck 改用 python3 urllib，改后需 `up -d --force-recreate` 生效。API 本身正常，别误判成升级失败。
- **首次启动慢**（hermes-webui 实测）：新版本首次启动装 Python 依赖，unhealthy 约 2-3 分钟，装完自动恢复。不要 1 分钟内就判定失败回滚。

## B2. compose pull 拉不到新版本（先验「最新版是否真的存在」）

用户报「pull 没拉到最新」时，先按链路逐段验证，不要急着查网络：

1. **registry 的 latest digest**：`curl -I -H 'Accept: application/vnd.docker.distribution.manifest.v2+json' <registry>/v2/<repo>/manifests/latest` 的 `Docker-Content-Digest`，与版本 tag 的 digest 对比。
2. **源码仓库的 tag**：`git ls-remote --tags origin`——tag 存在不代表镜像存在。
3. **CI 流水线**：tag 流水线可能失败而 latest 仍停在旧 digest（test 门禁失败 → build-and-push 被跳过是最常见形态）。查 Woodpecker：API token 失效时，可从 GitHub webhook URL 里取 access_token，或用宿主只读副本查 sqlite（`cp` 出来再查，避免 database is locked）。
4. 结论按证据落位：digest 未变 + CI 失败 = 发版没发出来，修 CI 重发版；digest 已变 = 才是拉取侧问题转 A 节。

### Pitfall: slim 基础镜像跑不了原生模块编译
ci/构建用 `node:<v>-slim` 这类 slim 基础镜像时，原生模块（better-sqlite3 等）在**新 node ABI 下可能没有预编译二进制**，回落 node-gyp 源码编译，而 slim 里没有 python3/make/g++ → `npm ci` 失败。修法是在依赖安装前置装工具链（`apt-get install -y --no-install-recommends python3 make g++`），CI test 步骤和 Dockerfile deps 阶段**两处都要补**——只补一处，本地过了 CI 照样红。升 node 基础镜像版本时，先确认所有原生依赖对新 ABI 有 prebuild。

### Pitfall: docker image prune -a 会吃掉无容器引用的本地构建镜像
清理脚本里的 `docker image prune -a -f` 删除**所有没有运行中容器引用**的镜像——包括本地构建的服务镜像和 rollback tag。服务下线/容器被删后跑一次清理，镜像就没了（本地无回滚点，只能回源码重建当前版本）。自建镜像的回滚 tag 应推送进私有 registry 保存，别只留在本地 image store。

## C. 归 1Panel 管的应用：命令行升级可用，但必须同步面板版本

1Panel 面板拉取有时会失败，**归面板管的应用同样允许命令行升级**，不是"归面板就不能动"。但命令行改了镜像后面板数据库里的版本不会自己变，必须手动同步，否则面板显示与实际不一致，后续面板操作会被旧版本带偏。

面板安装记录在 `/opt/1panel/db/agent.db` 的 `app_installs` 表（2026-11-13 实测，v2 系面板）：
- 关键列：`name`（安装名，如 `openresty`）、`version`（当前版本标签）、`container_name`、`app_id`、`app_detail_id`、`status`。
- **命令行升级后的同步写入**（需 sudo，sqlite 直写即可，实测无需重启面板）：
  ```bash
  sudo -n sqlite3 /opt/1panel/db/agent.db \
    "update app_installs set version='<新版本tag>', updated_at=datetime('now','localtime') \
     where name='<安装名>';"
  ```
- **一致性验证**（升级后必须两边对上）：
  ```bash
  docker inspect <容器> --format '{{.Config.Image}}'    # 取镜像 tag 的版本段
  sudo -n sqlite3 /opt/1panel/db/agent.db \
    "select version from app_installs where name='<安装名>';"
  # 两者版本段必须一致（实测 openresty：镜像 1panel/openresty:1.31.8.1-2-1-noble ↔ version 1.31.8.1-2-1-noble）
  ```
- 注意：agent.db 是 WAL 模式且面板常驻，直写前确认面板服务正常（写失败会留下 db-wal 锁冲突）；写完用上面的 select 回读确认。
- 判断某应用是否归面板管：`sudo -n sqlite3 /opt/1panel/db/agent.db "select name,version,container_name from app_installs;"` 里有就是面板装的；也可看 `/opt/deploy/<名>/` 有无 compose，没有就默认归面板。

## 相关
- PyPI 包镜像失败 → 见 `hermes-cron-jobs` 技能的 `references/pypi-mirror-fallback.md`，模式相同（阿里云/清华源）。
- 磁盘被镜像撑爆 → 见 `devops/docker-disk-cleanup`。
