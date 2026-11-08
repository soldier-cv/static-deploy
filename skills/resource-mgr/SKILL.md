---
name: resource-mgr
description: Use when 发布资源包、管理下载版本或设备拉包更新。
version: 1.1.0
author: Hermes coding agent
license: MIT
metadata:
  hermes:
    tags: [release, publish, mcp, firmware, apk, download, versioning]
    related_skills: [static-deploy-mcp, project-repo-standards, woodpecker-ci-pipelines]
---

# resource-mgr：内部资源发布与分发

> 内网服务：`http://100.64.0.88:13000`（容器 `resource-mgr`，数据 `/data/resource-mgr`）
> 代码：`/opt/code/resource-mgr`；部署：`/opt/deploy/resource-mgr`

## When to Use

要让「一台设备/一个人拿到最新版安装包或固件」时用它，而不是把文件丢到共享目录或发链接：

- 发布 APK / 固件 bin / 安装包 / 资源包，并且**以后还要发新版本**
- 设备需要「检查更新」（轮询几百字节，而不是反复下整包）
- 需要稳定下载 URL（写进固件/客户端，跨版本不变）
- 需要知道「谁发布了什么、谁拉取的」（审计）

**不要用**：一次性文件传给别人（用 static-deploy / dufs）；代码制品（用 registry / GitHub Release）。

## 更新与版本

| 项 | 值 |
|---|---|
| 当前版本 | 见 frontmatter 的 `version` |
| 更新源 | `http://100.64.0.88:8088/.well-known/skills/index.json` |
| 安装根 | `http://100.64.0.88:8088/.well-known/skills/resource-mgr/` |

```bash
# 查版本
curl -s http://100.64.0.88:8088/.well-known/skills/index.json | python3 -c "
import json,sys
s=[x for x in json.load(sys.stdin)['skills'] if x['name']=='resource-mgr'][0]
print(s['version'], s['updated_at'])"

# 升级（单文件）
curl -fsSL http://100.64.0.88:8088/.well-known/skills/resource-mgr/SKILL.md -o <你的技能目录>/resource-mgr/SKILL.md
```

版本语义：`patch` 修错别字不改结论；`minor` 新增章节/工具；`major` 推翻既有结论（需重读全文）。

## 1. 三条链路先分清

| 链路 | 谁用 | 鉴权 | 能干什么 |
|---|---|---|---|
| `/admin/*` | 人（浏览器） | Session + CSRF | 建项目、传包、管 key、看审计 |
| `/push/*` | Agent / CI | push key | 只能发布本项目的版本 |
| `/r/*` | 设备 / 客户端 | download key | 只能下载（含 manifest / latest / 精确版本） |
| `/mcp` | Agent | Bearer token | 全部 18 个工具（推荐给 Agent 用这个） |

**Agent 优先用 MCP**：不用记路由和请求体格式，且有结构化返回。

## 2. MCP 接入

```text
POST http://100.64.0.88:13000/mcp
Authorization: Bearer <MCP_TOKEN 或 MCP_TOKENS 里的某个令牌>
Accept: application/json, text/event-stream
Content-Type: application/json
```

有状态会话：`initialize` 后拿 `Mcp-Session-Id`，后续请求带上；再发一条 `notifications/initialized`。

令牌位置：`/opt/deploy/resource-mgr/.env` 的 `MCP_TOKEN`（默认身份）与 `MCP_TOKENS`（多身份，格式 `名称:令牌,名称:令牌`）。
**审计里的身份形如 `mcp:coding`、`mcp:default`**——你用的哪个令牌，就记在谁头上；要分清责任就给自己领一个独立令牌。

stdio 模式（本地 agent）：`pnpm mcp:stdio`，身份取 `MCP_ACTOR`（默认 `local`）。

## 3. 工具速查（18 个）

- **项目**：`list_projects` / `get_project` / `create_project` / `update_project`
- **版本**：`list_releases` / `get_release` / `publish_release` / `delete_release` / `set_latest` / `run_retention`
- **钥匙**：`list_keys` / `create_key` / `revoke_key` / `get_download_url`
- **设置与观测**：`get_settings` / `update_settings` / `get_stats` / `get_audit_log`

关键参数（其余字段看 tools/list）：

- `create_project`: `slug`（↑小写连字符，内部用，不对外）/ `name`
- `publish_release`: `slug`, `version`, `file_name`, **`slot`**（稳定槽位）, `content_base64` 或 `source_path`（stdio）, `notes`
- `create_key`: `slug`, `name`, **`scope`**（`download` 设备用 / `push` Agent 用）, 可选 `version_scope`
- `get_audit_log`: `limit` / 按 action、actor 过滤

## 4. 四个高频配方

### 4.1 发布一个新版本（Agent 最常用）

```text
publish_release { slug: "my-app", version: "v1.2.3", file_name: "my-app-v1.2.3.apk",
                  slot: "my-app.apk", content_base64: "..." }
```

**`slot` 是设备的生命线**：设备里写死 `/r/<key>/latest/my-app.apk`，以后发 `my-app-v1.2.4.apk` 仍挂同一个 slot，URL 永远不变。不填 slot 则默认等于 file_name——那设备就得跟着改 URL，不要这么干。

### 4.2 给设备发一个下载 key + 稳定 URL

```text
create_key { slug: "my-app", name: "客厅电视", scope: "download" }
→ { rawKey, keyPrefix, pushEndpoint }
```

`rawKey` **只返回这一次**，丢了只能吊销重建。给设备的 URLs：

```text
GET /r/<rawKey>/manifest/<slot>       # 检查更新（几百字节，可带 If-None-Match 拿 304）
GET /r/<rawKey>/latest/<slot>         # 稳定下载（写进设备）
GET /r/<rawKey>/<version>/<file_name> # 精确版本（回滚用）
```

注意：**URL 里没有项目 slug**，slug 只在管理端和 MCP 里用。

### 4.3 回滚到上一个版本

`set_latest { slug, release_id }` —— 把某个历史版本设为「当前版本」，`latest/<slot>` 立刻指向它，设备下次检查更新就会降级。设备端必须允许降级，否则这个功能没用。

### 4.4 清理旧版本

`run_retention { slug }` —— 按 `retainCount`（默认 5）保留最近几个版本；`pinned` 的版本不会被删。删之前确认设备已升级到新版，否则回滚无门。

## 5. 审计：谁做了什么

`get_audit_log { limit: 20 }` 返回 `actor / action / target / ip / createdAt`。

- 管理端操作：`admin` 或具体用户名
- MCP 操作：`mcp:<身份名>`
- key 相关：`key.create` / `key.revoke`；版本：`release.publish` / `release.delete` / `release.set_latest`

要追责时先看 actor：如果全是 `mcp:default`，说明多个 agent 共用了同一个令牌，无法区分——给每个 agent 发独立令牌。

## 6. 常见坑

| 坑 | 说明 |
|---|---|
| URL 里带上了 slug | 开放端路径是 `/r/<key>/...`，没有项目 slug，带了就 404 |
| 把 key 当机密 | key 是运维控制面（可限流、可吊销、可观测），不是保险柜；URL 流出去了照样能下 |
| 一个项目放多个平台 | 一个项目只有**一个当前版本**；Android/iOS/固件各自建项目 |
| 用 file_name 当 slot | 版本一多，设备里的 URL 就得跟着改 |
| internal 项目对外访问 | 一律 404（包括正确的 key），这是设计 |
| 401/404 分不清原因 | 不存在的 key、已吊销的 key、错路径全部 404，不泄露存在性 |

## 7. 部署与运维（改代码时）

- 端口：宿主 `13000` → 容器 `3000`（**不要用 3000，已被 grafana 占用**）
- 数据：`/data/resource-mgr`（SQLite + 文件存储），备份走 `/data` 周备
- 回滚：把 `/opt/deploy/resource-mgr/.env` 的 `TAG` 改回旧版本号 → `docker compose --env-file .env up -d`（旧镜像仍在 registry）
- 健康：`docker exec resource-mgr node -e "fetch('http://127.0.0.1:3000/health').then(r=>r.text()).then(console.log)"`

### 发一个版本（标准动作）

```bash
# 1) 版本号必须与 tag 一致，先改再发
sed -i "s/APP_VERSION = '.*'/APP_VERSION = '1.2.0'/" packages/shared/src/constants.ts
sed -i 's/"version": ".*"/"version": "1.2.0"/' package.json
git commit -am "chore(release): 版本号对齐到 1.2.0" && git push

# 2) 打 tag 推上去，剩下全自动
git tag v1.2.0 && git push origin v1.2.0
```

流水线四步：**质量门**（typecheck + test + build）→ **构建推镜像**（版本 tag 与 latest 同 digest）→ **部署**（改宿主 `.env` 的 `TAG` 再 `compose up -d`）→ **健康检查**（容器内探活）。

流水线红了的排查顺序（都踩过）：

| 现象 | 原因 | 处置 |
|---|---|---|
| step 无日志直接失败 | 卷挂载与 agent 信任卷白名单不完全一致（多写 `:ro` 也会不匹配） | 去掉后缀，与白名单逐字一致 |
| `invalid reference format` | `.woodpecker.yml` 的全局 `variables` 没注入 step 环境 | 镜像地址写字面量 |
| 健康检查 502 | step 里 `wget` 继承了 `HTTP_PROXY`，访问内网地址走了代理 | 改 `docker exec <容器> node -e fetch(...)` |
| GitHub 显示 500 但 Woodpecker 无记录 | GitHub webhook 投递 10s 超时（偶发） | 本地 POST 同一个 `/api/hook` 补发 |

### 新增一个仓库接入 CI（不需要点网页）

`repos.hash` 列就是 `model.Repo.WebhookSecret`。写一行 repo 记录 + 用该字符串签 token 即可：

```python
import base64, hmac, hashlib, json, secrets
secret = base64.b32encode(secrets.token_bytes(32)).decode()   # 存进 repos.hash
# JWT: header {"alg":"HS256","typ":"JWT"}
#      payload {"forge-id":"1","repo-forge-remote-id":"<GitHub repo id>","type":"hook"}
#      签名 key = secret 的**原始字符串**（不是 base32 解码后的字节）
```

然后把 webhook 指到 `https://ci.xl.codec.top/api/hook?access_token=<jwt>`，事件选 push / pull_request / deployment / pull_request_review。

## 8. 安全边界

- 管理端密码、`MCP_TOKEN`、key 原文都只在 `.env`（600）和一次性的工具返回里，**不要写进仓库或日志**
- 反代层要开 `TRUST_PROXY=true`，否则所有设备挤在一个 IP 限流桶里
- 上 HTTPS 后必须 `COOKIE_SECURE=true`，否则管理端登录不上
