---
name: desktop-release-ci-playbook
description: Use when 桌面应用发版 CI 出问题（Tauri 打包/签名/latest.json/自动更新），或要接 GitHub→Gitee 双通道同步、写 Woodpecker 部署流水线。
version: 1.0.0
author: 程序员（coding）
license: MIT
platforms: [linux, macos, windows]
triggers:
  - Tauri 打包成功但签名失败 / .sig 取不到 / 客户端装了新版起不来
  - latest.json 生成或上传失败、客户端提示有新版但下载 404
  - GitHub Actions 发版流水线红叉（403/502/not a git repository）
  - 要把 GitHub 仓库同步到 Gitee（源码镜像 + Release 安装包 + 下载地址校验）
  - 写/调 Woodpecker CI 流水线（compose 本机发布、secrets、tag 触发）
metadata:
  hermes:
    tags: [ci, github-actions, gitee, woodpecker, tauri, release]
    related_skills: [tauri-desktop-release-pipeline, woodpecker-ci-pipelines, coding-dispatch]
---

# 桌面应用发版 CI 全链路（GitHub Actions + Gitee 镜像 + Woodpecker）

一条流水线真正要交付的东西只有一件：**用户点"检查更新"能装上**。编译绿、job 全绿都不算。
本手册按「编译 → 签名 → 分发 → 部署」四段拆解，每段给出失败分类、可用写法与验收命令。
实证来源：`soldier-cv/desk-alarm`（Tauri v2 桌面提醒，Windows exe + macOS app/dmg，
GitHub Actions 6 job + Gitee 双通道 + Woodpecker compose 本机部署）。

## When to Use

- Tauri/Electron 桌面应用打包、签名、`latest.json`、自动更新任一处失败
- GitHub Actions 发版流水线红叉，需要判断是「编译」「签名」「权限」还是「网络」
- 要给一个 GitHub 仓库接 Gitee 镜像（源码分支 + tag + Release 附件 + 下载地址自检）
- 要写 Woodpecker 流水线做「推镜像 + compose 本机发布 + 健康验证」
- 想复刻本项目整套 CI 骨架到新项目

## 第一性原理：先分段，再修

发版链路是**串联**的，任一段断了后面的全部无效。修之前先定位在哪一段，不要看到红叉就去改代码：

| 段 | 产出 | 失败的典型信号 | 判定依据 |
|---|---|---|---|
| ① 编译 | 安装包 + `.sig` | 代码/依赖错 | 日志里有没有 `Finished N bundles at:` |
| ② 签名 | 可用签名（`.sig` 非空、能验签） | `Invalid symbol 10`、`No such file` | 打包器 `Finished 1 updater signature at:` 的路径 |
| ③ 分发 | Release 附件 + `latest.json` + 镜像地址 200 | 403、502、404 | `gh release view` / `curl -sI` |
| ④ 部署 | 容器/服务跑的是新版本 | 健康检查失败、端口占用 | `docker inspect` 的 image digest 与 health |

核心判据：**`Finished N bundles at:` 一出现，①②的编译部分就排除了**——后面所有报错都是签名/路径/权限/网络，
按关键词归类即可（`Invalid symbol`=格式，`No such file`=路径，`403`=权限，`502`=网络）。四类修法完全不同，混着改无法归因。

## 骨架一：GitHub Actions 发版（Tauri 版，6 job）

```
plan        # 解析版本号 + publish 开关（唯一版本真源）
checks      # PR/推送的快速编译检查（不跑真打包）
windows     # 真打包 + 签名 + 上传 Release（permissions: contents: write）
macos       # 同上（不同 runner，产物不共享）
latest-json # 从 Release 回取两个 .sig → 生成 latest.json → 上传
gitee-release # 等以上全完 → 推 tag + 搬附件到 Gitee + 校验下载地址
```

三条骨架级规则：

1. **版本号只在一个 job 里解析**，用 `outputs` 传给其它 job。push 用 `github.ref_name`，
   `workflow_dispatch` 用 `inputs.tag`，统一补 `v` 前缀并做 `^v[0-9]+\.[0-9]+\.[0-9]+` 校验。
2. **顶层 `permissions: contents: read`，凡上传附件/建 Release 的 job 必须 job 级声明 `contents: write`**。
   漏了只有那个 job 403，其它 job 正常——极具迷惑性。
3. **两个平台的产物不在同一台 runner**，所以「合并两个平台产物的 job」（latest.json / 镜像同步）
   一律 `needs: [plan, windows, macos]` 并从 **Release 回取**，不要试图用 artifact 硬拼。

细节写法（plan 门、重试封装、附件命名、手动触发复用旧 tag）见 `references/github-actions.md`。

## 骨架二：签名三坑（Tauri v2）

1. **私钥 Secret 多了末尾换行** → `failed to decode base64 key: Invalid symbol 10, offset 348`。
   `10` = 换行，`348` = 密钥文件字节数。密钥是**单行纯 base64**，Secret 里粘贴整份文件就多了一个换行。
   防复发：打包前加预检步骤（`tr -d '[:space:]'` 后与原文比较 + `base64 -d` 试解码），别让 6~8 分钟编译白跑。
   ⚠️ 绝不为了"让流水线过"重新生成密钥对——公钥已在客户端 `tauri.conf.json` 里发布，换钥 = 所有在装客户端验签失败。
2. **macOS 的 `.sig` 不在 `bundle/dmg/`**：Tauri 签的是 updater 产物 `.app.tar.gz`，落在 `bundle/macos/`；
   `dmg` 本身不带签名。用 dmg 配 tar.gz 的签名 → sha256 不同 → 客户端必然装不上。
   因此 `latest.json` 的 macOS `url` 也必须指向 `.app.tar.gz`，dmg 只留给人手动下载。
3. **`.sig` 从 Release 回取，不要跨 job 传文件**；取不到就 `exit 1`——发一个"看起来有新版但装不上"的
   `latest.json` 比不发更糟。

## 骨架三：GitHub → Gitee 双通道（国内可用性）

分两段互不越界，**避免两个 workflow 同时往 Gitee 推而互相覆盖**：

| workflow | 负责 | 触发 | 关键点 |
|---|---|---|---|
| `sync-gitee.yml` | 源码分支镜像（main/master） | push 分支 / 手动 | `concurrency` 分组 + `cancel-in-progress`，`--force` 推送 |
| `build.yml` 的 `gitee-release` job | tag + Release 附件 + 下载地址校验 | 发版时 | 等 `latest-json` 完成，`needs` 全列上 |

Gitee 侧四条硬约束（都踩过）：

1. **API 用 multipart form（`-F`），不要 `application/json`**：Gitee 对 JSON POST 有概率被 WAF 拦成 400；
   form 还顺手解决中文正文换行编码问题。
2. **同名附件上传会 400**：先列 `attach_files` 删同名再传；每个文件重试 3 次。
3. **建 Release 不返回 id 不代表失败**（可能已存在，补包重跑）：要按 `releases/tags/<tag>` 查回来复用；
   查不到 id 就 `exit 1` —— 留下"有 Release 无附件"的空壳比没有更糟。
4. **`latest.json` 里 URL 指向 Gitee，就必须校验 Gitee 上真的 200**：清单传上去、包没传上去时，
   客户端判定有新版、点下去 404，比"没有更新"难查得多。逐个 `curl -L -o /dev/null -w '%{http_code}'`。

镜像 job 用 `continue-on-error: true` 是**刻意**的：GitHub Release 此时已可用，镜像失败不该让发版显示红；
代价是失败不进 job 状态 → 脚本内部对关键失败一律 `echo ::error::` + `exit 1`，日志里必须看得见。
完整写法（token 检查、tag force push、附件搬运、并发冲突）见 `references/gitee-mirror.md`。

## 骨架四：Woodpecker v3 部署流水线（compose 本机发布）

```yaml
when:
  - event: tag
    ref: refs/tags/v*
  - event: manual
steps:
  - resolve-tag      # 版本落共享卷文件（step 间不共享环境变量）
  - verify-server    # 类型检查 + 编译，失败就别碰生产
  - build-and-deploy # build 双 tag → push → 清旧容器 → compose up → 健康验证
```

必守写法（每条都对应一次真实事故，完整清单见 `references/woodpecker-compose.md`）：

- **v3 没有 step 级 `secrets: [...]`**，只有 `environment.X.from_secret`；照抄 v2 教程必编译失败。
- **Secret 不存在 = 整条 pipeline 编译 error**（不是 warning）；secret 的 `events` 必须覆盖 `tag/release/manual/cron`。
- **命令里的 `$` 要写成 `$$`**（`$${VAR}`、`$$(cat file)`），否则被 CI 先做变量替换；
  含 `key: value` 的命令用 `>-` 折叠块承载，避免 YAML 当成映射。
- **跨 step 传值只能落共享卷文件**（如 `.release_tag`），环境变量不跨容器。
- **挂宿主目录/`docker.sock` 需要 repo `trusted.volumes=true`**，否则每条 pipeline 都 `Insufficient trust level`。
- **双 tag 同 digest**：一次 `docker build -t img:ver -t img:latest` 再分别 push；分两次 build digest 会不同。
- **部署前删旧容器**：`docker rm -f <旧名>`，`compose up` 不会带走 compose 文件里已改名的老容器，它会继续占端口。
- **健康验证看容器 healthcheck**（`docker inspect -f '{{.State.Health.Status}}'` 轮询到 healthy），
  别只看 `compose up` 退出码。

## 验收：发版到底成没成

```bash
TAG=v0.2.3
# ①② 产物与签名成对
gh release view "$TAG" --json assets -q '.assets[] | "\(.name)  \(.size)B"'
# ③ 清单内容与 url 匹配
curl -fsSL "https://github.com/<owner>/<repo>/releases/download/$TAG/latest.json" | jq .
# ③ 镜像地址逐个 200（-L 跟随 302）
jq -r '.platforms[].url' latest.json | while read -r u; do
  echo "$(curl -sS -o /dev/null -w '%{http_code}' -L --max-time 30 "$u")  $u"; done
# ④ 部署跑的是不是新版本（digest 比对，不是 latest==running）
docker inspect <container> --format '{{.Image}}'; docker images --digests | grep <img> 
```

必验四项：**每平台都有安装包 + 非空 `.sig`**、**`latest.json` 的 url 与 signature 成对**、
**镜像地址真的 200**、**运行容器 digest == 版本 tag digest**（`latest == running` 恒真，无证明力）。

## 排障表（症状 → 根因）

| 症状 | 根因 | 处置 |
|---|---|---|
| `Invalid symbol 10, offset 348` | Secret 尾部多换行 | 重贴单行 base64；加打包前预检 |
| `cp: .../bundle/dmg/*.sig: No such file` | macOS 签名在 `bundle/macos/` | 改路径，并把 latest.json 的 mac url 改成 `.app.tar.gz` |
| `failed to run git: fatal: not a git repository` | 纯脚本 job 没 checkout，`gh` 推断不出仓库 | job 开头加 `actions/checkout@v4` |
| `HTTP 403 Resource not accessible by integration` | job 继承顶层 `contents: read` | 该 job 补 `permissions: contents: write`（重试对 403 无效） |
| `HTTP 502` 偶发 | GitHub 侧瞬时故障 | 上传点包指数退避（5→10→20→40s），`::warning::` 留痕，末次才 `::error::` |
| Gitee Release 建了没附件 | 创建返回无 id 后直接跳过 | 按 tag 查 id；仍无 → exit 1，不留空壳 |
| Gitee 附件上传 400 | 同名附件已存在 | 先列 attach_files 删同名再传 |
| Gitee JSON POST 400 | WAF 拦 JSON | 改 `-F` multipart |
| 客户端提示新版但下载 404 | latest.json 先于附件生效 / url 指错文件 | 镜像 job 里逐个 URL 校验 200 再收工 |
| Woodpecker 每条 pipeline `Insufficient trust level` | repo `trusted.volumes` 未开 | PATCH repo trusted 开 volumes/security |
| Woodpecker step 秒退 exit 2 / `parameter not set` | step 脚本裸引用未注入变量 | 一律 `$${VAR:-}` + 存在性判断 |
| 新容器起不来、端口被占 | 旧容器名变了但没被删 | `docker rm -f <旧名>` 后再 `compose up` |
| 构建成功但版本 tag 指向 latest | manual 变量大小写没接住，落回 `latest` | 大小写都认（`deploy_tag`/`DEPLOY_TAG`），验收查双 tag digest |

## 移植到新项目（变量表）

| 位置 | 需替换 |
|---|---|
| `build.yml` | `github.repository == '<owner>/<repo>'` 守卫、产物名/`productName`、`TAURI_SIGNING_PRIVATE_KEY`/`_PASSWORD` secret |
| `sync-gitee.yml` + `gitee-release` job | `GITEE_OWNER`/`GITEE_REPO`、`GITEE_TOKEN` secret（Gitee 私人令牌，需 projects/releases 权限） |
| `latest.json` | 平台键（`windows-x86_64` / `darwin-aarch64` / `linux-x86_64`）、附件命名 |
| `.woodpecker.yaml` | `registry_host/user/pass` secrets、镜像名、部署目录、健康检查容器名 |

原则：**路径、仓库名、镜像名全部参数化，凭据只走 Secrets/`from_secret`**；文档里不留 token 与内网地址。

## 分发与安装（给其它 agent）

本技能的公开发布位（去掉本机特有路径即为通用版）：

```bash
BASE=http://<发布机>:8088/.well-known/skills/desktop-release-ci-playbook
DEST=~/.hermes/skills/devops/desktop-release-ci-playbook
mkdir -p "$DEST/references"
curl -fsSL "$BASE/SKILL.md" -o "$DEST/SKILL.md"
for f in github-actions gitee-mirror woodpecker-compose; do
  curl -fsSL "$BASE/references/$f.md" -o "$DEST/references/$f.md"
done
```

装完让 agent 读一遍 `SKILL.md` 即可按段排障；它的 `references/` 是可直接抄的完整 yml 片段。

## 边界

- 本手册只覆盖「桌面应用 + GitHub/Gitee + Woodpecker 部署」。k3s/GitOps/ArgoCD 发布见 `k3s-gitops-onboarding`，
  Woodpecker 服务端运维（PAT、sqlite、forge timeout）见 `woodpecker-ci-pipelines`。
- 不改 CI 的触发策略与权限边界属于产品决策：push 不触发打包、只在 tag 发版，是刻意的成本选择。
