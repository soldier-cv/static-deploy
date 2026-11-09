---
name: resource-mgr
description: Use when 发布资源包、管理下载版本或设备拉包更新。
version: 1.5.0
author: Hermes coding agent
license: MIT
metadata:
  hermes:
    tags: [release, publish, mcp, firmware, apk, download, versioning, ota]
    related_skills: [static-deploy-mcp, project-repo-standards]
---

# resource-mgr：内部资源发布与分发

> 公网入口：`https://fmgr.xl.codec.top` —— **只反代 `/r/*`（设备下载）**，其余路径公网 404
> 内网入口：`http://100.64.0.88:13000` —— 管理端、`/mcp`、`/push` 一律走这里
> 代码：`/opt/code/resource-mgr`；部署：`/opt/deploy/resource-mgr`
> 链路：公网 VPS `47.117.97.173`（openresty，证书 `*.xl.codec.top`）→ ZeroTier → 本机 `13000`

**暴露面**（2026-11-09 实测）：公网 `/r/...` 能到达应用（返回应用自己的 404 文案），而 `/admin`、`/mcp`、`/push`、`/api`、`/health` 全部 404。管理面只在 ZeroTier 内网可达——这是刻意设计：**外网只能拉包，不能操作**。

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

## 1. 四条链路先分清

| 链路 | 谁用 | 鉴权 | 能干什么 | 公网可达 |
|---|---|---|---|---|
| `/r/*` | 设备 / 客户端 | download key | 只能下载（manifest / latest / 精确版本） | ✅ **唯一对外路径** |
| `/admin/*` | 人（浏览器） | Session + CSRF | 建项目、传包、管 key、管令牌、看审计 | ❌ 仅内网 |
| `/push/*` | Agent / 构建流水线 | push key | 只能发布本项目的版本 | ❌ 仅内网 |
| `/mcp` | Agent | Bearer（Web 签发） | 全部 20 个工具（推荐给 Agent 用这个） | ❌ 仅内网 |

**Agent 优先用 MCP**：不用记路由和请求体格式，且有结构化返回。

**公网只放 `/r/*`**。管理端、MCP、push 都只在 `http://100.64.0.88:13000` 可达——反代只配一条 `location /r/`，其余路径 VPS 直接 404（配置见 9.4）。这样即使公网入口被打，攻击面也只有「下载」这一个只读面。

## 2. MCP 接入

```text
POST http://100.64.0.88:13000/mcp        ← 内网地址，公网不开放
Authorization: Bearer <管理员签发的 Agent 令牌>
Accept: application/json, text/event-stream
Content-Type: application/json
```

有状态会话：`initialize` 后拿 `Mcp-Session-Id`，后续请求带上；再发一条 `notifications/initialized`。
会话与令牌身份绑定：拿 A 的令牌复用 B 的会话会被 401；会话有空闲回收与数量上限。

### 令牌从哪来：管理员在 Web 里签发（1.2.0 起）

**`MCP_TOKEN` / `MCP_TOKENS` 环境变量已废弃**，不再读取。令牌存在数据库 `mcp_tokens` 表里（只存 sha256 + 前缀），由管理员在 Web「Agent 令牌」页（`#/mcp-tokens`）签发：

| 操作 | 效果 |
|---|---|
| 签发 | 返回原文**仅一次**，丢了只能轮换；名称未吊销时唯一 |
| 吊销 | 下一个请求立即 401（无内存缓存，按哈希每请求查库） |
| 轮换 | 吊销旧的 + 同名生成新的，一个事务内完成，历史审计里的 `mcp:<名称>` 不断档 |

**审计里的身份形如 `mcp:coding`**——你用的哪把令牌，责任就记在谁头上。多个 agent 共用一把 = 追责时全是同一个名字，所以**每个 agent 领独立令牌**。

没令牌时 `/mcp` 一律 401（这是正常的，不是服务坏了）。

stdio 模式（本地 agent）：`pnpm mcp:stdio`，身份取 `MCP_ACTOR`（默认 `local`），不经过 HTTP 令牌。

## 3. 工具速查（20 个）

- **项目**：`list_projects` / `get_project` / `create_project` / `update_project` / `delete_project`
- **版本**：`list_releases` / `get_release` / `publish_release` / `update_release` / `delete_release` / `set_latest` / `run_retention`
- **钥匙**：`list_keys` / `create_key` / `revoke_key` / `get_download_url`
- **设置与观测**：`get_settings` / `update_settings` / `get_stats` / `get_audit_log`

注意：**key 轮换、Agent 令牌管理没有 MCP 工具**，只能在 Web 管理端或 admin API 做（见 4.5 与第 2 节）。

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

`rawKey` **只返回这一次**，丢了只能吊销重建。返回体里直接带面板的公网地址，不用自己拼：

```text
create_key → {
  rawKey, baseUrl, baseUrlSource,
  endpoints: {
    manifestUrl,          # 检查更新
    latestUrl,            # 稳定下载
    versionUrlTemplate    # 精确版本 / 回滚
  }
}
```

给设备的 URLs：

```text
GET /r/<rawKey>/manifest/<slot>       # 检查更新（几百字节，可带 If-None-Match 拿 304）
GET /r/<rawKey>/latest/<slot>         # 稳定下载（写进设备）
GET /r/<rawKey>/<version>/<fileName> # 精确版本（回滚用）
```

`baseUrlSource` 是 `config` 说明用的是部署配置的 `PUBLIC_BASE_URL`（正确）；是 `request` 说明没配、回落到了请求地址——**这时候返回的可能是内网地址，不要直接写进固件**。

如果手上没有 rawKey 想先看地址模板，`get_download_url` 只传 `slug` 也能拿到含 `{key}` 占位的地址。

注意：**URL 里没有项目 slug**，slug 只在管理端和 MCP 里用。

### 4.3 回滚到上一个版本

`set_latest { slug, release_id }` —— 把某个历史版本设为「当前版本」，`latest/<slot>` 立刻指向它，设备下次检查更新就会降级。设备端必须允许降级，否则这个功能没用。

### 4.4 清理旧版本

`run_retention { slug }` —— 按 `retainCount`（默认 5）保留最近几个版本；`pinned` 的版本不会被删。删之前确认设备已升级到新版，否则回滚无门。

### 4.5 轮换 key（应急断供 / 定期换）

```text
POST /admin/projects/<slug>/keys/<id>/rotate
→ { rawKey, keyPrefix }        # 原文仍然只返回一次
```

Web 项目详情页的 key 行上有「轮换」按钮，走同一个接口。行为：

- **一个事务内**「吊销旧的 + 建新的」，不会出现「旧的已废、新的没建出来」把设备全停摆的中间态
- 新 key 继承旧的 `name` / `scope` / `version_scope`
- 旧 key **立刻失效**，正在拉的设备下次请求就 401

⚠️ 所以 rotate 是**应急场景**（旧 key 已泄漏、必须立刻断）用的。要平滑换 key 走 7.3 的「新旧并存 → 下发新配置 → 再吊销旧」流程，别直接 rotate，否则在用旧 key 的设备会在下一次检查更新时集体失败。

## 5. 审计：谁做了什么

`get_audit_log { limit: 20 }` 返回 `actor / action / target / ip / createdAt`。

- 管理端操作：具体用户名（如 `rongzhen777`）
- MCP 操作：`mcp:<令牌名称>`
- key 相关：`key.create` / `key.revoke` / **`key.rotate`**；版本：`release.publish` / `release.delete` / `release.set_latest`
- Agent 令牌：**`mcp_token.create` / `mcp_token.revoke` / `mcp_token.rotate`**（detail 里只有前缀，不含原文）
- 初始化：`user.create`（首个超管）；登录失败：`auth.login_failed` / `auth.setup_failed`
- 登录失败是**最重要的入侵信号**，定期看——尤其管理端虽在内网，但内网被打穿后这就是第一现场

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
| 把 `version_scope` 当「精确版本」用 | 它是**上限**：设备仍能检查更新、拿旧版，但看不到更高版本 |
| 上传超过 `max_file_bytes` | 读流前就 413；反代 `client_max_body_size` 必须 ≥ 该值 |
| 升级到 1.2.0 后 `/mcp` 一直 401 | 正常：令牌台账是空的。去 Web 签一把，别再去翻 `.env` 的 `MCP_TOKEN` |
| 公网访问 `/admin` 或 `/health` 是 404 | 正常，**这是设计**。管理面只在 `100.64.0.88:13000` |
| 以为 rotate 是「平滑换 key」 | rotate 立刻废掉旧 key；平滑过渡走 7.3 新旧并存 |

## 7. OTA 凭证落位（做固件/客户端 OTA 必须先读这节）

设备端必须知道两样东西才能升级：**① 从哪儿下（基址 URL + 槽位）② 用什么身份下（download key）**。这两样总得写进某个地方，问题不是「要不要写」，而是「写在哪一层、能不能换」。

### 7.1 三个候选位置的取舍

| 位置 | 能不能改 | key 泄漏后怎么办 | 结论 |
|---|---|---|---|
| 固件只读区（rodata / ROM） | ❌ 终身不变 | 只能服务端吊销 → **同 key 的所有设备一起停摆** | 只放权限最窄的「引导 key」 |
| APP 可写配置（NVS / 加密存储 / 配置文件） | ✅ 可远程更新 | 吊销 + 下发新配置，平滑轮换 | ✅ **正式 key 放这里** |
| 服务端 | — | — | 不能替设备保管，只能下发 |

**本项目不支持设备身份绑定**（设计决策 D14：不做设备管理、不做 OTA 编排）。这意味着：

- ❌ 不能「按单台设备吊销」——吊销 key 会把这批设备一起停
- ✅ 可以「按批次发 key」：100 台设备分 5 批，每批一个 key，泄漏只停一批
- ✅ key 可以多条并存，支持新旧并存过渡

所以**「一个项目一个 key 让所有设备共用」不可接受**——一次泄漏就是全量停摆。

### 7.2 推荐架构：引导 key + 运行 key（两级）

```text
出厂烧录（只读区）     →  引导 key（bootstrap）
                          scope=download；只挂在「配置包」项目上
                          ↓ 只能拉 device.conf，拉不到固件
设备启动 / 定期        →  GET /r/<bootstrap>/latest/device.conf
                          ↓ 内容 { "base_url": "...", "key": "<runtime key>" }
写进加密配置区（可写）  →  运行 key（runtime）
                          ↓ 用它拉固件 / 检查更新
日常 OTA              →  GET /r/<runtime>/manifest/fw.bin → 304 或下载
```

落地步骤：

1. `create_project` 建两个项目：`device-config`（配置包）与 `fw-main`（固件）
2. `create_key` 给 `device-config` 建 **bootstrap** key；给 `fw-main` 建 **runtime** key
3. 把 `device.conf` 用 `publish_release` 发到 `device-config`，槽位 `device.conf`
4. 设备只用 bootstrap key 拉配置，用配置里的 runtime key 拉固件

**key 是项目级的，跨项目无效**——这是天然的权限隔离，不用额外配置。

### 7.3 轮换流程（项目能力完全支持）

1. 在 `fw-main` 下 `create_key` 建新的 runtime key（旧的**先不吊销**）
2. 发布新的 `device.conf`（含新 key）到 `device-config`
3. 设备用旧 runtime key 拉 `device.conf` → 写入可写区
4. 设备切到新 key 拉固件
5. 确认全量切换后，`revoke_key` 吊销旧 key

过渡期新旧 key 并存，老设备不会断——这就是需求里「换 key 用新旧并存过渡」的落地方式。

### 7.4 最低限度做法（设备端不想做两级时）

1. **按批次发 key**（20 台一批），台账记 `keyPrefix → 批次 → 设备清单`
2. key 存**可写区**，APP 提供「换 key」入口（配置包或管理命令）
3. 固件里只写**基址 URL + 槽位名**，URL 用公网域名 `https://fmgr.xl.codec.top`，不要写内网 IP
4. 绝不要把 **push key** 放进设备——push key 能发布任意版本，等于给攻击者一个投毒入口

### 7.5 设备端必须实现的三件事

| 能力 | 为什么 | 服务端接口 |
|---|---|---|
| `Range` 断点续传 | 服务端升级 / 网络抖动后不用重下整个包 | 已支持 `Range` / `206` / `Accept-Ranges` |
| `If-None-Match` 检查更新 | 100 台每 10 分钟轮询从 GB 级降到 KB 级 | 已支持 `ETag` / `304` |
| `X-Content-SHA256` 校验 | 下完先验哈希再刷写，防止半包刷成砖 | 已支持，响应头带 sha256 |

**服务端升级会断连接**（进程被替换，TCP 必断），K3S/蓝绿都解决不了根因。唯一兜底是设备端 `Range` 续传 + 退避重试。**OTA 不断的关键在客户端，不在服务端编排。**

### 7.6 能力边界：支持什么、不支持什么

| 能力 | 支持 | 说明 |
|---|---|---|
| 稳定 URL（槽位不变） | ✅ | 发新版 URL 不变 |
| 多 key 并存 / 按批次吊销 | ✅ | 支持新旧并存过渡 |
| 通道版本上限（`version_scope`） | ✅ | 分批升级的基础 |
| 检查更新 304 | ✅ | 几乎零带宽 |
| 断点续传 | ✅ | 服务端已就绪 |
| 按设备身份鉴权 | ❌ | D14 明确不做，只能按 key 批次 |
| key 自动下发 / 轮换 | ❌ | 要设备端实现（用配置包） |
| 分批推送 / 灰度编排 | ❌ | 项目只「放包」不「推包」；灰度靠 `version_scope` + 多项目 |

## 8. 部署与初始化（维护者）

> 使用方可以忽略这节。包的版本、槽位、下载 key 全部由 API/MCP 管理，与部署形态无关。

### 8.1 部署必配项

| 变量 | 为什么必须 |
|---|---|
| `PUBLIC_BASE_URL=https://fmgr.xl.codec.top` | 设备侧基址。**不配就回落到请求 origin**：内网管理端建 key 会返回 `http://100.64.0.88:13000`，写进固件的公网设备直接拉不到 |
| `SETUP_TOKEN` | 首次初始化一次性凭据，见 8.2 |
| `TRUST_PROXY=true` | 串在 VPS 反代后面时必须开，否则所有设备挤进一个 IP 限流桶 |
| ~~`MCP_TOKEN` / `MCP_TOKENS`~~ | **1.2.0 起废弃**，不再读取也不再校验。Agent 令牌改为管理员在 Web 签发（见第 2 节） |

**升级到 1.2.0 必做**：升级后 `/mcp` 全部 401，因为令牌台账是空的。管理员登录 Web →「Agent 令牌」→ 给每个 agent 签一把，把原文配到对应 agent 的 MCP 客户端里。旧 `.env` 里的 `MCP_TOKEN` 删掉即可，留着无效。

**`PUBLIC_BASE_URL` 必须在 `docker-compose.yml` 的 `environment:` 里显式透传**（`PUBLIC_BASE_URL: ${PUBLIC_BASE_URL:-}`）。compose 不会自动把 `.env` 里的变量灌进容器，漏了这一行 `GET /api/meta` 会一直返回 `baseUrlSource: "request"`。

验证方法：

```bash
curl -s http://127.0.0.1:13000/api/meta
# 期望 {"version":"...","publicBaseUrl":"https://fmgr.xl.codec.top","baseUrlSource":"config"}
# 若 baseUrlSource 是 "request" → 配置没生效
```

### 8.2 首次初始化超管

部署完成后 `users` 表为空，网页入口直接显示「初始化超级管理员」表单，由用户自己设用户名密码。**系统只有一个用户**，其余全是 key/token 权限。

| 端点 | 说明 |
|---|---|
| `GET /admin/setup/status` | `{ needsSetup, requireToken }`，公开只读 |
| `POST /admin/setup` | `{ username, password, token? }`，仅 `needsSetup` 为真时可创建，限流 5 次/分钟/IP |
| 密码要求 | ≥12 位，同时含字母和数字，拒绝常见弱口令（`password`/`123456`/`admin` 等子串）|

**公网部署必须配 `SETUP_TOKEN`**：没有它，「部署完成 → 有人初始化」这段时间里任何能访问的人都可能把自己建成超管。配置后初始化表单会多一个「初始化凭据」输入框。

```bash
# 生成并写入（600 权限的 .env）
openssl rand -hex 24
# 初始化完成后建议删掉这一行并重启容器，彻底关掉这个入口
```

### 8.3 `setup_completed` 是防重开标记

初始化成功时会在 `settings` 表写 `setup_completed`。此后**即使 `users` 表被清空，`needsSetup` 仍然为 false**，`POST /admin/setup` 返回 409「初始化已完成但用户表为空，需人工恢复」。

这是有意的：否则任何能删库的人都能重新抢注超管。真要重来，必须手工清掉这个标记：

```bash
sudo docker stop resource-mgr
sudo sqlite3 /data/resource-mgr/db/app.sqlite \
  "DELETE FROM users; DELETE FROM sessions; DELETE FROM settings WHERE key='setup_completed';"
sudo docker start resource-mgr
curl -s http://127.0.0.1:13000/admin/setup/status   # 期望 {"needsSetup":true,...}
```

⚠️ 执行到 `needsSetup:true` 那一刻起，任何能访问该端口的人都能创建超管——**只在能立刻完成初始化时做这一步**，做完确认 `needsSetup` 变回 false。

### 8.4 发布流程

镜像由 Woodpecker 构建（tag `vX.Y.Z` → 构建 → 推内网 registry → 部署 → 健康检查），配置真源在宿主 `/opt/deploy/resource-mgr/.env`。改服务本身看仓库 `AGENTS.md` 与 `README.md`。

## 9. 安全边界（公网暴露后必读）

服务已有公网入口（`https://fmgr.xl.codec.top`）。**「不能因为公网暴露就完蛋」的前提是下面这些条件成立**：

### 9.1 应用侧已具备（不用你操心）

- 口令用 `scrypt` + `timingSafeEqual` 校验，不手写哈希
- 会话是数据库里的随机不透明 id，不参与签名
- 所有被拒响应统一纯文本 `404 Not Found` + `no-store`，不泄露「路径/记录/key 是否存在」
- 限流三档：按 key 600/min、按真实 IP 120/min、`/mcp` 与登录各自独立限流
- 上传两道闸门：`Content-Length` 预检 + 流中累计兜底，无界 chunked 打不穿
- `version_scope` 越界、`scope` 不符、internal 项目一律 404
- 审计记录 `auth.login_failed`、`key.create` / `key.revoke` / `release.publish`

### 9.2 公网暴露必须满足的外部条件（缺一条就有洞）

| # | 项 | 检查方法 |
|---|---|---|
| 1 | `COOKIE_SECURE=true`（上 HTTPS 后必须） | `grep COOKIE_SECURE /opt/deploy/resource-mgr/.env`；false 时 cookie 可能被降级到明文 |
| 2 | 应用端口**不直接暴露公网**，只走反代 | 否则伪造 `X-Real-IP` / `XFF` 就能绕过按 IP 限流 |
| 3 | `TRUST_PROXY=true`，且反代**覆盖**而非追加 `X-Real-IP` | 反代里 `proxy_set_header X-Real-IP $remote_addr` |
| 4 | **反代 access log 脱敏 key** | key 在 URL 路径里，不脱敏等于把凭证写进日志，见 9.3 |
| 5 | `client_max_body_size` ≥ `DEFAULT_MAX_FILE_BYTES` | 不匹配会出现「应用能收、反代先 413」 |
| 6 | 公网**只**反代 `/r/*`，`/admin` `/mcp` `/push` 全部 404 | 见 9.4 的 `location / { return 404; }`；管理面入口越少越好 |
| 7 | 管理端口令 ≥ 20 位随机，不与其他服务复用 | 存 `.env`（600），不进仓库 |
| 8 | 定期备份 `data/db` + `data/storage` | 攻击/误删后能回滚，见第 11 节 |

### 9.3 nginx 侧 key 脱敏（复制即用）

```nginx
# key 在路径里，日志必须脱敏后再落盘
map $request_uri $rg_uri {
    default                $request_uri;
    "~^/r/[^/]+(/.*)$"     /r/REDACTED$1;
    "~^/push/[^/]+(/.*)$"  /push/REDACTED$1;
}
log_format rg '$remote_addr - [$time_local] "$request_method $rg_uri $server_protocol" '
              '$status $body_bytes_sent "$http_referer" "$http_user_agent"';
access_log /var/log/nginx/resource-mgr.access.log rg;
```

### 9.4 反代白名单（公网**只放 `/r/`**）

线上就是这么配的：整站只反代下载路径，管理面完全不上公网。

```nginx
server {
    server_name fmgr.xl.codec.top;

    # 唯一对外面：设备拉包
    location /r/ {
        proxy_pass http://100.64.0.88:13000;
        proxy_http_version 1.1;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
        proxy_request_buffering off;       # 大包流式下发，不在 VPS 落盘
    }

    # 其余一律拒绝：/admin /mcp /push /api /health 都不出去
    location / { return 404; }
}
```

验证（四个都应是 404，只有 `/r/...` 返回应用自己的 404 文案而非 openresty 默认页）：

```bash
for p in /r/x/manifest/a /admin/setup/status /mcp /health; do
  printf '%-24s ' "$p"; curl -s -o /dev/null -w '%{http_code}\n' https://fmgr.xl.codec.top$p
done
```

**代价**：管理员和 Agent 从公网是够不着的，要进 ZeroTier 网段或用 SSH 隧道才能操作。这是安全换来的，不要为了图方便把 `/admin` 放出去。

## 10. 公网入口排障

**当前状态（2026-11-09）**：已通。`/r/...` 到达应用，其余路径 404。历史故障是 504（VPS 上游写错），排障步骤保留在下面。

> ⚠️ 不要再用 `/health` 判断入口是否正常——`/health` 现在**故意不对外**，返回 404 是正确状态。判断入口是否通，用 `/r/<任意>/manifest/x` 看响应体是应用的 `Not Found` 还是 openresty 默认页。

**历史故障症状**：60 秒后 `504`，但 `openssl s_client` 握手正常、证书有效 → TLS 在 VPS 终止成功，是 VPS → 上游那段不通。

```bash
# 1. 应用本身活着吗（在 88 本机跑）
curl -s http://127.0.0.1:13000/health          # 期望 {"status":"ok","database":"ok"}

# 2. 裸 TLS 是否正常（任意机器）
openssl s_client -connect 47.117.97.173:443 -servername fmgr.xl.codec.top </dev/null | grep "Verify return code"

# 3. 对照同 VPS 上另一个域名（区分反代整体故障 / 单个 vhost 故障）
curl -s -o /dev/null -w '%{http_code}\n' https://ci.xl.codec.top/

# 4. 从 VPS 测上游（需 VPS 权限）
curl -s -m 5 http://100.64.0.88:13000/health
zerotier-cli listnetworks    # VPS 的 ZeroTier 是否 OK、是否有 100.64.0.0/24
```

**两种常见成因**：

1. VPS 的 `proxy_pass` 指向 `127.0.0.1:13000`（VPS 本地）而不是 `100.64.0.88:13000` → 上游无人监听，等满 60s 后 504
2. VPS 的 ZeroTier 成员掉线 / 不在 `myNet`（`6afb53abb7828058`）→ 到 `100.64.0.88` 不通

修好后验证：`curl -s https://fmgr.xl.codec.top/health` 返回 `{"status":"ok",...}`，再走一遍 `manifest` + `Range` 下载。

## 11. 数据与备份

| 项 | 值 |
|---|---|
| 数据根 | `/data/resource-mgr`（宿主，容器内 `/app/data`） |
| 数据库 | `data/db/app.sqlite`（SQLite WAL，**文件名是 app.sqlite 不是 resource-mgr.db**） |
| 包文件 | `data/storage/`（按项目/版本分目录） |
| 备份 | 停写窗口内 `sqlite3 .backup` + `tar storage`；**库与 storage 必须同版本一起备**，只备库会出现「有记录无文件」 |
| 重建 | 恢复 `data/` → `docker compose up -d` → `curl /health` 验证 `database: ok` |

会话、key、版本元数据全在 SQLite 里；丢了等于全员重新发 key，所以备份优先级高于一切。
