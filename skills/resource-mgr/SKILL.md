---
name: resource-mgr
description: Use when 发布资源包、管理下载版本或给客户端配置下载地址。
version: 4.1.0
author: Hermes coding agent
license: MIT
metadata:
  hermes:
    tags: [release, publish, agent-api, assets, firmware, apk, download, versioning, ota]
    related_skills: [static-deploy-mcp, project-repo-standards]
---

# resource-mgr：资源发布与下载地址配置

> 公网下载入口：`https://api.xl.codec.top/ui9hbnpb1x0izu4wkc`（网关路径，上游代理到 resource-mgr 的 `/r/`）—— 生成的设备地址**不带 `/r`**
> 内网操作入口：`http://100.64.0.88:13000` —— `/agent` 与管理端一律走这里，公网够不着

## When to Use

要让「一台设备/一个人拿到最新版安装包或固件」时用它，而不是把文件丢到共享目录或发链接：

- 发布 APK / 固件 bin / 安装包 / 资源包，并且**以后还要发新版本**
- 设备需要「检查更新」（轮询几百字节，而不是反复下整包）
- 需要稳定下载 URL（写进固件/客户端，跨版本不变）
- 需要给自己的程序配好下载地址与取件凭证

**不要用**：一次性文件传给别人（用 static-deploy / dufs）；代码制品（用 registry / GitHub Release）。

## 这个技能只做两件事

| 部分 | 你要做的事 | 看哪节 |
|---|---|---|
| **一、操作资源管理项目** | 拿令牌、建项目、登记资产、流式发版本、回滚、轮换 key | 第 1–4 节 |
| **二、给客户端配置下载地址** | 确定基址 / 资产槽位 / key 放在客户端哪里、怎么处理停用与轮换 | 第 5–8 节 |

两块之外的内容不在本技能范围内。

## 更新与版本

| 项 | 值 |
|---|---|
| 当前版本 | 见 frontmatter 的 `version` |
| 更新源 | `http://100.64.0.88:8088/.well-known/skills/index.json` |
| 安装根 | `http://100.64.0.88:8088/.well-known/skills/resource-mgr/` |

## 版本与升级（统一走 skillctl）

更新源（唯一权威）：`http://100.64.0.88:8088/.well-known/skills/index.json`

```bash
# 首次：下载通用客户端（每台机器一次）
curl -fsSL http://100.64.0.88:8088/.well-known/skillctl.py -o skillctl.py && chmod +x skillctl.py

# 干活前惰性检查（约 1 秒）：落后就先升级，再动手
./skillctl.py list                                  # 本地各技能版本 vs 注册表
./skillctl.py update --to <你的技能目录>             # 默认只检测
./skillctl.py update --to <你的技能目录> --apply     # 确认后才升级（逐文件 sha256 校验）
```

版本语义：`patch` 修错别字不改结论；`minor` 新增章节/接口；`major` 推翻既有结论（需重读全文）。
**4.0.0 对齐服务 2.0.0**：未知 `X-Slot` 不再自动建资产，发布前必须先登记，否则 400；令牌改为 `rmag_...`，管理接口为 `/admin/agent-tokens`。一把下载 key 打开该项目全部通道。升级不迁移旧数据，空库重建即可。3.0.0 起一个项目恒有一把有效 key、资产是一级实体、令牌改为改名 / 启用 / 禁用 / 删除；再早的 2.x 技能文档已移除 MCP、统一走 `/agent`。
**3.0.1 补充边界说明**：Agent 令牌可处理管理端以外的全部工作流（建项目、管资产、发版、key 复制 / 轮换）；`/admin/*` 在任何情况下都不接受令牌。

---

# 第一部分：操作资源管理项目

## 1. 一套接口、一把令牌

**`/agent` 是 Agent 的唯一入口**，原生 HTTP + Bearer。没有 MCP、没有 tools/list、没有会话。

- 地址：`http://100.64.0.88:13000/agent/...`（内网，公网不开放）
- 鉴权：`Authorization: Bearer <Agent 令牌>`
- **令牌从哪来**：管理员在 Web「Agent 令牌」页（`#/agents`）签发，原文只显示一次；格式 `rmag_...`。令牌不进环境变量、DB 只存 sha256 + 前缀。丢了只能让管理员重新签发或禁用旧令牌，**令牌不轮换**。
- **审计身份**：`agent:<令牌名称>`。你用哪把令牌，责任就记在谁头上，所以每个 Agent 领独立令牌，不要共用一把。
- **权限边界别搞错**：`/agent` 只认 Agent 令牌，**不认 Session Cookie、不认 download key、不走 RBAC**；零令牌时一律 401（正常，不是服务坏了）。
- **权限范围**：Agent 能处理管理端以外的全部工作流——建项目、管资产、发布 / 回滚 / 删除版本、复制或轮换下载 key。管理端接口（`/admin/*`）会拒绝任何 Bearer 令牌，令牌只能在 `/agent` 用。

令牌的日常操作只在 Web 管理端，`/agent` 里没有这些接口：

| 方法 | 路径 | 作用 |
|---|---|---|
| POST | `/admin/agent-tokens` | 签发令牌（原文只显示一次） |
| PATCH | `/admin/agent-tokens/:id` | 改名 |
| POST | `/admin/agent-tokens/:id/enable` | 启用 |
| POST | `/admin/agent-tokens/:id/disable` | 禁用（下一个请求即 401） |
| DELETE | `/admin/agent-tokens/:id` | 删除（物理删） |

没有 `/rotate`：禁用后启用即可恢复，不必换令牌。

为什么没有 MCP：工具参数是 JSON，协议没有流式参数这回事；SDK 的 HTTP 传输还有默认 4 MiB 请求体上限，base64 再膨胀 33%，实际能塞的产物不到 3 MB。**发不了大包就不能用它**，`/agent` 直接消费原始字节流，内存占用与文件大小无关。

### 四条链路别混

| 链路 | 谁用 | 鉴权 | 能干什么 | 公网可达 |
|---|---|---|---|---|
| `/admin/*` | 人（浏览器 / CI） | Session + CSRF + RBAC | 全部管理操作，含签发 Agent 令牌 | 仅内网 |
| `/agent/*` | Agent | Bearer（Agent 令牌） | 项目 / 资产 / 版本 / key 的最小工作流，含流式发布 | 仅内网 |
| `/r/*` | 设备 / 客户端 | download key | 只能下载 | 公网唯一暴露面 |
| `/`、`/assets/*` | 浏览器 | 无 | 管理端静态文件 | — |

## 2. 接口速查（只给 Agent 真正要做的事）

**三级模型**：项目 → 资产 → 版本。资产是项目下的一级实体，有 `name` 与稳定 `slot`；`slot` 建后不可改（它写在设备 URL 里），`name` 可改。每个资产有自己的版本序列和一个当前版本。必须先登记资产再发布；未知 `X-Slot` 返回 400，**已禁用的资产不能发布**（409）。项目与资产都支持启用 / 禁用，禁用后对外地址一律立即 404。一把下载 key 打开该项目的全部通道。

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/agent/projects/:slug` | 项目概况 + 资产列表 + 版本列表 + 那把 key（不含原文） |
| POST | `/agent/projects` | 建项目（自动发一把 `default` 下载 key，恒有且仅有一把） |
| PATCH | `/agent/projects/:slug` | 改项目设置：name / visibility / retainCount / quotaBytes / maxFileBytes |
| POST | `/agent/projects/:slug/enable` | 启用项目 |
| POST | `/agent/projects/:slug/disable` | 禁用项目（对外地址全 404，`/agent` 写操作 409） |
| GET | `/agent/projects/:slug/assets` | 列资产 |
| POST | `/agent/projects/:slug/assets` | 登记资产（传 `name` + `slot`；可选但推荐，可给资产起名字） |
| PATCH | `/agent/projects/:slug/assets/:id` | 资产改名 / 启用 / 禁用（传 `disabled`） |
| DELETE | `/agent/projects/:slug/assets/:id` | 删除资产 |
| GET | `/agent/projects/:slug/releases?asset=<slot>` | 按资产列版本 |
| GET | `/agent/projects/:slug/releases/:id` | 版本详情（sha256、大小、是否当前版本） |
| POST | `/agent/projects/:slug/releases` | **流式发布**（请求体是原始字节；未知 `X-Slot` 返回 400，已禁用则返回 409） |
| PATCH | `/agent/projects/:slug/releases/:id` | 只改 `notes` |
| POST | `/agent/projects/:slug/releases/:id/latest` | **回滚到此版本**（设为该资产的当前版本） |
| DELETE | `/agent/projects/:slug/releases/:id` | 软删版本（当前版本不可删） |
| GET | `/agent/projects/:slug/keys` | 列 key（恒一把，只有前缀，不含原文） |
| GET | `/agent/projects/:slug/keys/:id/reveal` | 取回 key 原文（逐次记审计） |
| POST | `/agent/projects/:slug/keys/:id/rotate` | 轮换 key（旧 key 立即失效，新 key 原文只返回一次） |
| GET | `/agent/projects/:slug/access` | 那把 key + **已启用资产**的设备地址（配客户端时用这个） |

**刻意不提供**，别去找：列所有项目（slug 已知）、删项目、审计 / 统计 / 全局设置、手动留存、版本文件下载、Agent 令牌管理、新建 key / 吊销 key / 启用禁用 key。这些要么是人看的、要么是不开放的高风险操作，要么属于设备下载端。审计要看就在管理端「审计」页看，按 `actor` 过滤 `agent:<名称>`。

所有 JSON 接口用 `Content-Type: application/json`；`POST /projects` 与 `POST /assets` 的 body 是 JSON，只有发布是二进制。

```bash
BASE=http://100.64.0.88:13000/agent
H="Authorization: Bearer $AGENT_TOKEN"          # 管理员签发的那把，别写进固件
```

## 3. 常用工作流

推荐顺序：**建项目 → 登记并命名资产 → 发布到资产 → 回滚 / 轮换**。登记不能跳过：未知槽位会 400，不会悄悄建成一条产物通道。

### 3.1 建项目

```bash
curl -sS -X POST "$BASE/projects" \
  -H "$H" -H 'Content-Type: application/json' \
  -d '{"slug":"my-app","name":"My App"}'
# → 201 { project: {...} }；自动带一把名为 default 的下载 key
```

`slug` 只允许小写字母、数字、`-`、`_`，建后不可改。**slug 只在管理端和 `/agent` 里用，不进设备地址**。项目已存在时返回 409，直接接着用即可，不必先列项目。

建项目自动发 `default` key，恒有且仅有一把有效，正常流程不用也不能手工再建。要按批次隔离权限，做法是**拆成多个项目**，每项目一把 key。

### 3.2 登记资产（推荐）

```bash
curl -sS -X POST "$BASE/projects/my-app/assets" \
  -H "$H" -H 'Content-Type: application/json' \
  -d '{"name":"安卓安装包","slot":"android-apk"}'
# → 201 { asset: { id, name, slot, ... } }
```

- 资产是项目下的一级实体：`name` 是给人看的名称（可改），`slot` 是稳定产物通道名（**建后不可改**，它写进设备 URL）。
- 每个资产有自己的版本序列和一个当前版本；一个工程可以并行维护多条产物（`windows-installer` / `android-apk` / `source`），各发各的，互不顶掉。
- **必须先登记并命名**：`X-Slot` 命中未登记的资产时返回 400，请先 `POST /assets`。设备 URL 里的 slot 一旦写进固件就不要改。
- **已禁用的资产不能发布**：`X-Slot` 命中已禁用的资产返回 409，先 `/assets/:id` 启用它。
- 资产可以改名、启用 / 禁用、删除；禁用后该资产 manifest / latest / 精确版本对外 404，版本文件不删，可重新启用。

### 3.3 发布一个版本（流式）

```bash
curl -sS -X POST "$BASE/projects/my-app/releases" \
  -H "$H" \
  -H "X-Version: v1.2.3" \
  -H "X-File-Name: my-app-v1.2.3.apk" \
  -H "X-Slot: android-apk" \
  -H "X-Notes: $(python3 -c 'import urllib.parse;print(urllib.parse.quote("夜间构建"))')" \
  --data-binary @my-app-v1.2.3.apk
# → 201 { release: { id, version, fileName, slot, sha256, sizeBytes, isLatest, ... } }
```

| 头部 | 必填 | 说明 |
|---|---|---|
| `X-Version` | 是 | 版本号；同一 `version × file_name` 不可覆盖，只能发新版 |
| `X-File-Name` | 是 | 真实文件名，决定存储路径 |
| `X-Slot` | 推荐 | 资产 slot，必须已登记；未知槽位返回 400，已禁用返回 409；留空则以文件名为 slot，同样必须已登记 |
| `X-Notes` | 否 | 百分号转义后的备注 |

- 请求体就是原始字节，`Content-Length` 超过项目 `maxFileBytes` 在**读流之前**返回 413；落盘全程流式。
- 没有 `content_base64`、没有 `source_path`：不要试图把二进制塞进 JSON，服务端也不会去读本地路径。
- `slot` 是**产物通道名**，不是文件名，也是设备的生命线：设备里写死 `.../latest/<slot>`，以后换文件名只要挂同一个 slot，URL 永远不变。
- 发布新版本自动成为该资产的当前版本；同一资产跨版本必须保持同一个 slot。留存清理按资产各自进行。

### 3.4 回滚、备注与清理

```bash
# 按资产看有哪些版本、拿到 release id
curl -sS "$BASE/projects/my-app/releases?asset=android-apk" -H "$H"

# 回滚：把某个历史版本设为该资产的当前版本（其它资产不受影响）
curl -sS -X POST "$BASE/projects/my-app/releases/12/latest" -H "$H"

# 改备注
curl -sS -X PATCH "$BASE/projects/my-app/releases/12" -H "$H" \
  -H 'Content-Type: application/json' -d '{"notes":"首版"}'

# 软删非当前版本
curl -sS -X DELETE "$BASE/projects/my-app/releases/11" -H "$H"
```

`.../latest` 是**「回滚到此版本」**，不是常规「设为当前」；版本表里没有「锁定」开关。设备端必须允许降级，否则回滚没意义。删之前确认设备已升级到新版，否则回滚无门；当前版本不可删（409），要先 `.../latest` 切到别的版本。

### 3.5 key 管理

```bash
# 列 key（恒一把，只有前缀，没有原文）
curl -sS "$BASE/projects/my-app/keys" -H "$H"

# 之后随时可取回原文（每次记 key.reveal 审计）
curl -sS "$BASE/projects/my-app/keys/3/reveal" -H "$H"        # → { rawKey }

# 轮换：立刻废掉旧 key、生成新 key，原文只返回一次
curl -sS -X POST "$BASE/projects/my-app/keys/3/rotate" -H "$H"
```

- 一个项目**恒有一把有效 key**，只提供复制（`reveal`）与轮换（`rotate`）；没有新建、吊销、启用禁用接口。
- `rawKey` 丢了不用慌，`reveal` 能取回（库里存 AES-256-GCM 密文 + sha256）。
- **`rotate` 是应急止血，也是唯一的换 key 手段**：旧 key 立即失效，正在拉的设备下一次请求统一 404，**没有新旧并存过渡**。设备端要先有「换 key」通道（见第 6、7 节）。
- key **不随版本滚动**：它是长期取件凭证，版本变化体现在 URL 的版本路径里；key 是项目级的，覆盖该项目全部资产。
- `version_scope` 是**资产允许的最高版本**，不是精确版本：设备仍能检查更新、拿旧版，但看不到更高版本。
- 项目不想要 key 时用「禁用项目」，不要再找吊销接口。

### 3.6 给客户端取地址

地址不用单独铺开找：Web 项目详情的**资产行内「复制地址」按钮**直接复制该资产的 `manifestUrl` / `latestUrl`；需要一次拿全时用 `access`：

```bash
curl -sS "$BASE/projects/my-app/access" -H "$H"
# → { access: { key, baseUrl, downloadBaseUrl, baseUrlSource,
#               assets:[{ slot, name, version, fileName, manifestUrl, latestUrl }],
#               urlTemplate } }
```

`access` 用那把有效 key 按**已启用资产**拼好地址，**不回显 key 原文**，禁用资产不出现。把 `manifestUrl` / `latestUrl` 直接写进配置，不要自己拼。

> 注意 `baseUrlSource`：`config` 表示用了管理端「全局设置」里配好的下载基址（正确，地址原样使用）；`request` 表示没配、回落到了请求地址——`/agent` 是内网调用，这时拿到的是**内网地址，绝不能写进固件**。

## 4. 第一部分的边界

| 坑 | 说明 |
|---|---|
| 还在找 MCP / tools/list / `publish_release` | 已整体移除，统一用 `/agent` 的 HTTP 接口 |
| 用 Session Cookie 或 download key 调 `/agent` | 一律 401，只有管理员签发的 Agent 令牌能用 |
| 想用 `/agent` 管令牌 / 查审计 / 改全局设置 | 没这些接口，令牌管理只在 Web 管理端 |
| 拿 Agent 令牌调 `/admin/*` | 一律 401：管理端只接受管理员登录会话，令牌进不去 |
| 找令牌的 `/rotate` | 令牌已去掉轮换，改为改名 / 启用 / 禁用 / 删除 |
| 把二进制塞进 JSON 或 base64 | 发布只收原始字节流，`--data-binary @文件` |
| 上传超限 | `Content-Length` 预检就 413；超过项目上限调大 `maxFileBytes` 或换更小的包 |
| 发布时随手传个新 `X-Slot` | 会返回 400；先登记资产再发布，避免拼写错误污染通道 |
| 想改资产 slot | slot 建后不可改（在设备 URL 里），只有 name 可改 |
| 找「新建 key / 吊销 key / 多把 key / 启用禁用 key」 | 一个项目恒有一把有效 key，只留 `GET keys` / `reveal` / `rotate` |
| 给 `PATCH releases/:id` 传锁定字段，找「设为当前」 | 只改 `notes`；`.../latest` 是「回滚到此版本」 |
| 项目禁用后仍调 `/agent` 写操作 | 返回 409，先启用项目 |
| 把 Agent 令牌放进设备 | 它能发任意版本，等于给攻击者一个投毒入口；设备只需要 download key |
| 把 slug 写进设备地址 | 设备地址里只有 key，带 slug 必 404 |

---

# 第二部分：给客户端配置下载地址

## 5. 地址形态

客户端只需要两样东西：**从哪儿下（基址 + 资产槽位）** 和 **用什么身份下（download key）**。

```bash
# GET https://api.xl.codec.top/ui9hbnpb1x0izu4wkc/<key>/manifest/<slot>       检查更新（几百字节，可带 If-None-Match 拿 304）
# GET https://api.xl.codec.top/ui9hbnpb1x0izu4wkc/<key>/latest/<slot>         稳定下载（写进设备）
# GET https://api.xl.codec.top/ui9hbnpb1x0izu4wkc/<key>/<version>/<fileName>  精确版本 / 回滚
```

- **公网地址不带 `/r`**：管理端「全局设置」里的下载基址就是下载根，地址里不带 `/r`；应用内部路径形如 `/r/<key>/...`，只在直连 `http://100.64.0.88:13000` 时可见。**永远优先使用 `GET /access` 返回或资产行内复制的 `manifestUrl` / `latestUrl`，不要自己拼。**
- **URL 里没有项目 slug**：slug 只在管理端和 `/agent` 里用，带进设备地址就 404。
- `access` 会带回 `downloadBaseUrl` 与 `baseUrlSource`：`config` 表示用了管理端配好的下载基址（下载根）；`request` 表示没配、回落到了请求地址——**这时候拿到的是内网地址，不要写进固件**。
- 手上没有 key 想先看形状时，用 `GET /agent/projects/:slug/access`（需要 Agent 令牌）拿模板；它给的是那把真实 key 与**已启用资产**的地址。

验证一个设备地址是否真的可用（不需要登录）：

```bash
curl -i https://api.xl.codec.top/ui9hbnpb1x0izu4wkc/<rawKey>/manifest/<slot>
# 正确：返回 { slot, version, sizeBytes, sha256, url }
# 404 且 body 是应用自己的 Not Found：key / slot 不对，或地址里多拼了 /r
```

## 6. download key 放在客户端哪里

设备端必须知道「从哪儿下」和「用什么身份下」。这两样总得写进某个地方，问题不是「要不要写」，而是「写在哪一层、能不能换」。

### 6.1 一个项目恒有一把有效 key

- 建项目自动发一把 `default` key，**恒有且仅有一把有效**；只提供**复制 / 轮换**，没有新建、吊销、启用禁用。
- key 是**项目级**的，覆盖该项目下全部资产，不按资产隔离。
- **轮换后旧 key 立即失效**，同一项目全部资产同时切到新 key，没有新旧并存过渡。
- key 固定、不随版本滚动；`version_scope` 是资产允许的最高版本（上限，不是精确版本）。
- 项目不想要 key 时用「禁用项目」；禁用后该项目所有设备地址 404、`/agent` 写操作 409。

### 6.2 按批次分发：按批次拆项目

本项目不支持设备身份绑定（设计决策 D14：不做设备管理、不做 OTA 编排），不能按单台设备吊销。要控制泄漏影响面，做法是把设备**按批次拆成多个项目**，每项目一把 key：

| 目标 | 做法 |
|---|---|
| 一个批次泄漏只停一批 | 每批次一个项目，各有一把 key；轮换 / 禁用只影响本项目 |
| 某个资产临时不可下载 | 禁用该资产（该资产 manifest / latest / 精确版本一律 404，版本文件不删，可再启用） |
| 整批停摆 | 禁用项目（对外全 404，`/agent` 写操作 409） |

台账按 `项目 → 批次 → 设备清单` 记，不要指望在一个项目里塞多把 key 分批。

### 6.3 三个候选位置

| 位置 | 能不能改 | 轮换后怎么办 | 结论 |
|---|---|---|---|
| 固件只读区（rodata / ROM） | 不能，终身不变 | 旧 key 立即失效，这批设备一起停摆 | 不要放 key |
| APP 可写配置（NVS / 加密存储 / 配置文件） | 可以远程更新 | 下发新 key 写入即可 | **key 放这里** |
| 服务端 | — | 不能替设备保管，只能下发 | 不存放 |

- 固件里只写**基址 URL + 资产 slot**（用公网域名 `https://api.xl.codec.top/ui9hbnpb1x0izu4wkc`），key 放可写区。
- 设备侧要留「换 key」入口（配置包或管理命令）：轮换后不下发新 key，设备就会一直 404。
- 绝不要把 **Agent 令牌**放进设备——它能发任意版本，等于给攻击者一个投毒入口；设备只需要 download key。

## 7. 轮换与停用是止血手段，不是平滑过渡

新模型没有「新旧 key 并存过渡」，也没有两级 key 架构。换 key 与停用的流程：

1. key 泄漏或某批设备要停：对 `POST /agent/projects/:slug/keys/:id/rotate` 轮换（旧 key 立即失效），或 `POST /agent/projects/:slug/disable` 禁用项目 / 资产。
2. 轮换后立刻通过设备侧「换 key」通道把新 key 下发到可写区；没及时下发的设备下一次请求一律 404。
3. 重新启用后原地址恢复（项目 / 资产禁用不删版本文件）。

| 手段 | 影响范围 | 是否可恢复 | 设备端要求 |
|---|---|---|---|
| 轮换 key | 该项目全部资产，旧 key 立即失效 | 需换回新 key | 必须有换 key 通道 |
| 禁用资产 | 单个资产地址 404 | 可重新启用 | 无 |
| 禁用项目 | 该项目全部地址 404，`/agent` 写 409 | 可重新启用 | 无 |

**不要用「多建一把 key」做过渡**——没有新建 key 接口，也没有并存；规划时就把「换 key」做进设备端。

## 8. 客户端必须实现的三件事

| 能力 | 为什么 | 服务端接口 |
|---|---|---|
| `Range` 断点续传 | 连接中断后不用重下整个包 | 已支持 `Range` / `206` / `Accept-Ranges` |
| `If-None-Match` 检查更新 | 100 台每 10 分钟轮询从 GB 级降到 KB 级 | 已支持 `ETag` / `304` |
| sha256 校验 | 下完先验哈希再刷写，防止半包刷成砖 | manifest 带 `sha256`，响应头也带 |

网络抖动或链路中断随时可能发生，唯一兜底是设备端 `Range` 续传 + 退避重试。**OTA 不断的关键在客户端，不在服务端编排。**

### 能力边界：支持什么、不支持什么

| 能力 | 支持 | 说明 |
|---|---|---|
| 稳定 URL（资产 slot 不变） | 支持 | 发新版文件名变了也不影响 URL |
| 一个项目多资产 | 支持 | 每个资产独立版本序列、独立当前版本；key 项目内共用一把 |
| 资产管理 | 支持 | 必须先显式登记再发布；可改名、启用 / 禁用、删除（有版本时不能删）；已禁用资产不可发布 |
| 项目 / 资产停用 | 支持 | 停用后地址 404，作为止血手段 |
| 通道版本上限（`version_scope`） | 支持 | 分批升级的基础 |
| 检查更新 304 | 支持 | 几乎零带宽 |
| 断点续传 | 支持 | 服务端已就绪 |
| 单项目多把 key / 项目内按批次发 key | 不支持 | 恒有一把有效 key，要分批就拆成多个项目 |
| 新旧 key 并存 / 无缝轮换 | 不支持 | 轮换后旧 key 立即失效 |
| 按设备身份鉴权 | 不支持 | D14 明确不做，只能按 key |
| key 自动下发 | 不支持 | 要设备端实现换 key 通道 |
| 分批推送 / 灰度编排 | 不支持 | 项目只「放包」不「推包」；灰度靠 `version_scope` + 多项目 |

---

## 常见坑

| 坑 | 说明 |
|---|---|
| URL 里带上了 slug | 设备地址形如 `https://api.xl.codec.top/ui9hbnpb1x0izu4wkc/<key>/...`，没有项目 slug，带了就 404 |
| 以为生成的地址要带 `/r` | 管理端「全局设置」里的下载基址就是下载根，地址里不带 `/r`；直接用 `access` 返回或资产行复制的 `manifestUrl` / `latestUrl` |
| `baseUrlSource=request` 的地址写进固件 | 那是内网地址，公网设备用不了；只采用 `config` 来源返回的地址 |
| 把 `version_scope` 当「精确版本」用 | 它是**上限**：设备仍能检查更新、拿旧版，但看不到更高版本 |
| 一个项目里想放多把 key 分批 | 恒有一把有效 key；要按批次隔离就拆成多个项目 |
| 发布时随手传个新 `X-Slot` | 会返回 400；先登记资产再发布 |
| 想改资产 slot | slot 建后不可改（在设备 URL 里），只有 name 可改 |
| 还在找新建 key / 吊销 key / 启用禁用 key | 已移除；只留 `GET keys` / `reveal` / `rotate` |
| 以为 rotate 是「平滑换 key」 | 轮换后旧 key 立即失效，没有新旧并存过渡；先把「换 key」做进设备端 |
| 找 Agent 令牌的 `/rotate` | 令牌已去掉轮换，改为改名 / 启用 / 禁用 / 删除，且只在 Web 管理端 |
| 找「锁定」或把发布当成设为当前 | 没有锁定开关；`.../releases/:id/latest` 是「回滚到此版本」 |
| 禁用项目 / 资产后还去请求旧地址 | 一律 404；项目禁用时 `/agent` 写操作返回 409 |
| 把 `access` 当全部地址清单 | 只返回已启用资产的地址，禁用资产不出现 |
| internal 项目对外访问 | 一律 404（包括正确的 key），这是设计 |
| 401/404 分不清原因 | 不存在的 key、已吊销的 key、错路径全部 404，不泄露存在性；`/agent` 的 401 只是令牌不对 |
| 公网访问 `/admin` 或 `/agent` | 一律够不着，**这是设计**。操作只在 `100.64.0.88:13000` 内网做 |
| 把 key 当机密 | key 是控制面凭证（可限流、可轮换、可观测），不是保险柜；URL 流出去了照样能下 |
| 还在找 `/push` 或项目级发布 key | 已移除：`/push/*` 一律 404，发布只走 `/agent` + Agent 令牌 |
