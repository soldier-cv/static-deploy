---
name: project-repo-standards
description: Use when 新建仓库或补 CI、README、AGENTS.md 等文件；版本纪律（SemVer 大小版本判定）、git 提交规范、CHANGELOG 规范、技能升级感知也用它。
version: 1.5.0
author: Hermes coding agent
license: MIT
metadata:
  hermes:
    tags: [repo, scaffolding, woodpecker, github-actions, agents-md, gitee, gitignore]
    related_skills: [woodpecker-ci-pipelines, github-workflow, k3s-gitops-onboarding, open-source-upgrade-patrol, server-deployment-standards]
---

# 项目仓库规范：初始化、CI 选型、文档与升级

> 适用：新仓库开工，或给已有仓库补 CI / 文档 / 忽略规则。
> 目标：**每个文件都有存在理由**。没理由的不要建，建了的要能被验证。

## When to Use

在以下任一情形加载本技能：

- 新建项目仓库，要在建代码前定下 README / .gitignore / AGENTS.md / CI 的最小集
- **按本技能干活前，先跑「更新与版本」一节的版本比对命令**（约 1 秒），落后就先升级再动手
- 已有仓库缺 CI、CI 写错了、或两套流水线并存互相打架
- 要判断这个项目该用 Woodpecker（内网部署）还是 GitHub Actions（对外发布）
- 要给公开项目接 Gitee 镜像，让国内能下载安装包
- AGENTS.md 太长/跑题/混进了别的项目内容，需要重写

不适用：单纯的依赖升级排障（用 `open-source-upgrade-patrol`）、k3s 首次接入集群（用 `k3s-gitops-onboarding`）、Woodpecker 服务端自身故障（用 `woodpecker-ci-pipelines`）。

## 更新与版本

本文件会持续修订。**升级前先查版本号，不要用旧版规则指导新项目。**

| 项 | 值 |
|---|---|
| 当前版本 | 见本文件 frontmatter 的 `version` |
| 更新源（唯一权威） | `http://100.64.0.88:8088/.well-known/skills/index.json` |
| 安装根 | `http://100.64.0.88:8088/.well-known/skills/project-repo-standards/` |

**检查是否有新版**（比对 frontmatter 里的 version）：

```bash
curl -s http://100.64.0.88:8088/.well-known/skills/index.json | python3 -c "
import json,sys
s=[x for x in json.load(sys.stdin)['skills'] if x['name']=='project-repo-standards'][0]
print(s['version'], s['updated_at'])
print('files:', ', '.join(s['files']))
"
```

**升级到最新版**（覆盖本地副本，含 references）：

```bash
BASE=http://100.64.0.88:8088/.well-known/skills/project-repo-standards
DEST=<你的技能目录>/project-repo-standards
mkdir -p "$DEST/references"
for f in SKILL.md references/ci-coexistence.md references/upgrade-by-delivery-type.md; do
  curl -fsSL "$BASE/$f" -o "$DEST/$f" || { echo "下载失败: $f"; exit 1; }
done
echo "已升级到 $(grep -m1 '^version:' "$DEST/SKILL.md")"
```

**校验完整性**（index.json 里有每个文件的 sha256，下载后建议对一下）：

```bash
cd "$DEST" && curl -s http://100.64.0.88:8088/.well-known/skills/index.json | python3 -c "
import json,sys,hashlib,os
s=[x for x in json.load(sys.stdin)['skills'] if x['name']=='project-repo-standards'][0]
bad=[f for f,h in s['sha256'].items() if hashlib.sha256(open(f,'rb').read()).hexdigest()!=h]
print('OK 全部一致' if not bad else 'MISMATCH: '+', '.join(bad))
"
```

**版本语义**（决定你要不要重读全文）：

- `patch`（1.2.x）：修错别字、补充说明，结论不变，无需重读
- `minor`（1.x.0）：新增章节或规则，原有结论不变，建议看新增部分
- `major`（2.0.0）：**推翻既有结论**（如 CI 选型原则变更），必须重读全文

### agent 怎么知道该升级（惰性腿 + 兜底腿）

现状：**没有任何生态能向 agent 推送技能更新**。Claude Code 插件市场是会话启动后随机延迟拉一次 marketplace（运行中会话保持旧版）；skills.sh / `gh skill` 全靠人手动跑 update；裸 md 装完就彻底失联。所以只能自己补两条腿：

1. **惰性腿（agent 自查，零常驻成本）**：agent 按本技能干活前，先跑一次上面的「检查是否有新版」命令（约 1 秒）。版本落后 → 先按升级命令更新，再执行任务。这条写进了本技能的 When to Use，加载即生效。
2. **兜底腿（巡检 cron，静默契约）**：各 profile 配每日低频巡检，比对本地已装技能文件的 sha256 与 index.json 中的 sha256，**不一致才发卡，一致 stdout 留空**。防的是「agent 忘了跑惰性腿」。coding profile 已有现成实现：`/home/xl/.hermes/profiles/coding/scripts/skill_version_patrol.py`（no_agent cron，可直接复制到其它 profile 改路径复用）。

**维护约定**：`version` 只写在 SKILL.md 的 frontmatter，index.json 里的 version/sha256/updated_at 全部由 `skills/sync_index.py` 从磁盘提取，**不要手改 index.json**。

## 0. 开工先判三件事（不要先动手建文件）

1. **怎么部署？** 自托管内网（k3s / docker / systemd）→ Woodpecker；对公众发布产物（开源项目、桌面客户端）→ GitHub Actions。
2. **代码托管在哪？** 只有 GitHub；还是 GitHub 为主 + Gitee 镜像方便国内下载？
3. **谁消费这个仓库？** 只有自己 / 有 AI agent 参与开发 / 有外部用户和贡献者。

三个答案决定下面 90% 的文件要不要建。

### 判定表（照这个选，别两种 CI 都上）

| 场景 | `.woodpecker.yml` | `.github/workflows` | Gitee 镜像 | `.gitignore` | `README` | `AGENTS.md` |
|---|---|---|---|---|---|---|
| 内网服务，k3s/docker 部署 | ✅ 必须 | ⭕ 仅当有客户端/对外交付物时 | ❌ | ✅ | ✅ | ✅（有 AI 参与） |
| 服务端 + 客户端同仓（客户端要对外发） | ✅ 管服务端 | ✅ 管客户端 | ✅ | ✅ | ✅ | ✅ |
| 开源项目 / 公开仓库，发 Release | ⭕ 仅当内网也部署时 | ✅ 必须 | ✅ 推荐 | ✅ | ✅ | ⭕ |
| 桌面客户端（Tauri/Electron） | ❌ | ✅ 多平台构建 + Release | ✅（国内下载） | ✅ | ✅ | ⭕ |
| 纯库 / 文档站 | ❌ | ⭕ 只跑测试 | ❌ | ✅ | ✅ | ❌ |
| 一次性脚本 / 实验 | ❌ | ❌ | ❌ | ✅ | ⭕ | ❌ |

**核心原则：按「交付物」分工，不按「项目」一刀切。**

一个仓库有多个交付物是常态：服务端镜像走 Woodpecker 推内网 registry，客户端安装包走 GitHub Actions 发 Release——这是合理分工，不是重复建设。

真正要避免的只有一种：**同一个交付物挂了两条流水线**（服务端镜像两边都构建、安装包两边都上传），那才会出现「两个 registry 的 digest 不一样，不知道哪个是线上版本」。

共存时守四条：① 按目录隔离（`server/**` vs `client/**`）；② 触发条件互斥且写进两个文件的头注释；③ 版本号只认 git tag；④ 发布产物目标不同、互不覆盖。

完整规则见 `references/ci-coexistence.md`。

## 1. 每个文件干什么（建不建看判据）

| 文件 | 作用 | 必须建的情况 | 不建会怎样 |
|---|---|---|---|
| `.gitignore` | 挡住构建产物/凭据/缓存 | **永远** | 密钥泄露、仓库膨胀、diff 全是噪音 |
| `README.md` | 给人看的入口：是什么/怎么跑/怎么部署 | **永远** | 三个月后自己看不懂怎么启动 |
| `AGENTS.md` | 给 AI 编码助手的仓库级上下文 | 有 AI 参与开发 | agent 每次重猜结构，改错地方 |
| `.woodpecker.yml` | 自托管 CI：构建镜像 → 推 registry → 更新 GitOps | 内网部署 | 手动 docker build，版本漂移 |
| `.github/workflows/*.yml` | 公开 CI：测试、构建、发 Release、同步 Gitee | 对外发布 | 没有可下载的产物 |
| `LICENSE` | 法律授权 | 公开仓库 | 别人不能合法使用 |
| `.gitattributes` | 行尾/LFS/语言统计 | 跨平台客户端、含二进制 | Windows 检出后脚本带 CRLF 全挂 |
| `.editorconfig` | 缩进/编码统一 | 多人或跨编辑器 | 无意义的格式化 diff |
| `CHANGELOG.md` | 版本变更记录 | 有版本号发布 | 用户不知道升级改了什么 |
| `favicon.ico` + 图标链 | 浏览器标签/收藏夹/分享卡片的身份标识 | **有 Web UI 的项目** | 标签页显示默认地球图标，分享出去像模板站，观感掉一档 |
| `SECURITY.md` | 漏洞上报渠道 | 公开且有服务端 | 安全问题公开在 issue 里 |
| `CONTRIBUTING.md` | 外部贡献流程 | 接受外部 PR | 收到不合规 PR |

### 1.1 `.gitignore` 判据

按技术栈挑，**不要复制几 KB 的万能清单**——会把你本该入库的文件也忽略掉，且没人敢删。最小充分集：

- 语言级：`__pycache__/`、`*.pyc`、`.venv/`、`node_modules/`、`dist/`、`target/`
- 构建产物：`build/`、`*.log`、`.DS_Store`
- **凭据（最重要）**：`.env`、`.env.*`、`*.pem`、`*.key`、`credentials.json`、`*.token`
- 例外保留：`!.env.example`（模板必须入库）
- 项目特有：数据库文件、上传目录、缓存目录

自查：`git ls-files | grep -E '\.env$|\.pem$|\.key$'` 必须为空。

### 1.1.1 favicon 判据（有 Web UI 就必须有）

- 最小集：`favicon.ico`（32×32）+ HTML 里 `<link rel="icon" ...>`；有 PWA/移动端入口的再加 `apple-touch-icon`（180×180）与 `manifest.json` 的 icons。
- 图标放 `static/` 或根目录并入库（`.gitignore` 别挡它）；SPA 别只在 `index.html` 写外链——离线/内网环境要能加载。
- 自查：项目起服务后 `curl -sI http://127.0.0.1:<port>/favicon.ico` 返回 200。

### 1.2 `README.md` 最小结构（5 段，别写成流水账）

```markdown
# 项目名（一句话说清是什么）

## 是什么 / 解决什么问题
## 快速开始（三条命令内跑起来）
## 部署（生产入口、端口、依赖服务）
## 配置（环境变量表：名字、必填、默认值、说明）
## 已知限制 / 故障排查
```

不写：空泛的「采用先进架构」、复制自框架文档的长教程、会过期的截图。

## 2. `AGENTS.md` 铁律（最容易写坏的文件）

**唯一判据：这句话换到别的仓库还成立吗？成立就删掉。**

它会被 agent 每轮读进上下文，写废话等于持续烧 token 并误导决策。

**第二判据（范围划分）：AGENTS.md 只放「每次会话都必须知道的最小事实集」，场景性内容一律下沉项目技能（`<repo>/skills/<name>/`）。** 大项目常见的错误是把排障手册、环境加载步骤、部署流程全塞进 AGENTS.md——这些是**按场景触发**的内容，写进技能（带触发词 description），agent 遇到对应任务才加载；写进 AGENTS.md 等于每轮对话都背着排障手册跑。

| 放 AGENTS.md（常驻，每轮烧 token） | 放项目技能（按触发词加载） |
|---|---|
| 项目定位一句话、关键路径/端口/凭据位置 | 排障手册（症状→原因→命令） |
| 硬红线（禁止 X，3~5 条封顶） | 环境加载 / 构建 / 部署步骤 |
| 开工 pull、改完必跑的测试命令 | 历史坑详解、验收案例 |
| 指针：「排障见 skills/<name>」 | 需求台账细则 |

### 2.1 反模式清单（逐条禁）

| ❌ 反模式 | 为什么错 | 正确做法 |
|---|---|---|
| 通用编码规范（「要写单元测试」「代码要清晰」「遵循 SOLID」） | 任何项目都成立，等于没说 | 删；真要约束就写本仓库的验证命令 |
| 从别的项目复制的架构说明 | 直接误导 agent 改错目录 | 只写本仓库真实路径 |
| 模型/工具自述（「你是一个资深工程师…」） | 不是仓库知识，换模型就失效 | 删 |
| 会过期的数据（版本号、成员名单、日期） | 一周后就是错的 | 写「版本以 `git describe` 为准」 |
| 大段复制 README | 两处维护必然不同步 | 引用：「部署见 README §部署」 |
| 无验证方式的规则（「必须保证高可用」） | 不可执行 = 不可验收 | 写命令：「改完跑 `pytest -q`，0 failed」 |
| 长篇历史沿革 / 需求讨论过程 | 上下文噪音 | 结论进台账，过程留在 issue |

### 2.2 该写什么（六节骨架）

```markdown
# <项目名> — Agent 工作规约

## 0. 项目定位（一句话 + 仓库地址 + 分支）
## 1. 运行环境事实（端口、路径、数据库名、依赖真源、生产入口）
## 2. 硬规则（不许做什么，为什么）
## 3. 开发与验证流程（开工第一步：`git fetch && git pull --ff-only` 拉齐远端，多环境并行开发必须先同步再动工；改完必跑的命令）
## 4. 已知坑（踩过的，别再踩）
## 5. 需求台账 / 决策日志（只记结论与日期）
```

写「运行环境事实」的标准：**路径全用绝对路径，端口要能 `curl` 验证，凭据只说在哪、不说值**。

### 2.3 写完自检

- 每个专有名词问一遍：「这是本仓库的吗？」有一个不是就删。
- `grep -n "<别的项目名>" AGENTS.md` 必须 0 命中。
- 每条硬规则后面问：「违反了我怎么发现？」答不出就补检测方式或删掉。

## 3. Woodpecker CI：真实踩过的坑

### 3.1 语法与执行模型

| 坑 | 现象 | 正确写法 |
|---|---|---|
| **变量写两个 `$`** | `$VAR` 被 Woodpecker 当自己的插值吃掉，运行时为空 | `$$VAR`、`$${VAR}` |
| **每 step 独立容器** | 上一步 `cd`、`/tmp` 文件、`export` 全丢 | 每步自带 `working-directory`，或用 `volumes` 挂宿主目录传值 |
| **step 之间不共享 shell** | `set -e` 只管当前 step | 每条命令自己判错：`cmd \|\| exit 1` |
| **默认每次 push 都跑** | 每次提交都构建，浪费且版本号混乱 | 显式 `when: event: [tag, manual]` |
| **挂载宿主目录时 clone 覆盖** | 把旧代码 clone 进挂载点 | `skip_clone: true` |
| **secret 未声明** | `$SECRET` 为空但不报错 | `environment: X: from_secret: name` + 命令里判空 |
| **SSH push 回仓库** | 内网 DNS/fake-ip 干扰，间歇失败 | 走 HTTPS + token（`x-access-token`） |
| **manual 变量大小写** | 页面填 `deploy_tag`，脚本读 `DEPLOY_TAG` 取到空 | 两种都认，都空则显式报错退出 |

### 3.2 最小可用模板（内网 docker 部署）

```yaml
# 触发：只认 tag 与 manual，日常 push 不构建
when:
  - event: tag
    ref: refs/tags/v*
  - event: manual

steps:
  - name: build-and-push
    image: docker:26
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
    environment:
      REGISTRY_USER:
        from_secret: registry_user
      REGISTRY_PASS:
        from_secret: registry_pass
    commands:
      # 注意 $$：留给 shell 展开
      - RELEASE_TAG=$${CI_COMMIT_TAG:?tag 触发必须带 vX.Y.Z}
      - docker build -t "$$REGISTRY/$${CI_REPO_NAME}:$$RELEASE_TAG" .
      - echo "$$REGISTRY_PASS" | docker login "$$REGISTRY" -u "$$REGISTRY_USER" --password-stdin
      - docker push "$$REGISTRY/$${CI_REPO_NAME}:$$RELEASE_TAG"
```

要点：`${VAR:?msg}` 让变量缺失时立刻失败，而不是推出一个叫 `:latest` 的坏 tag。

### 3.3 密钥管理

- secret 只在 Woodpecker 服务端配置（仓库 Settings → Secrets），绝不写进 yml。
- 命名小写下划线：`registry_user` / `registry_pass` / `git_push_token`。
- 换 token 时同时更新 Woodpecker secret 与 GitOps 等引用点，否则流水线半通。

## 4. GitHub Actions：真实踩过的坑

| 坑 | 现象 | 正确做法 |
|---|---|---|
| 用过时的 action 版本 | `actions/checkout@v3` / `setup-node@v3`（Node16 已废弃） | `@v4` / `@v5` 起 |
| 忘记写权限 | 发 Release 403 | `permissions: contents: write` |
| 缺 `fetch-depth: 0` | `git describe` / 打 tag 失败 | checkout 时显式设置 |
| 并发触发互相覆盖 | 两次 push 同时发 Release，后者覆盖前者产物 | `concurrency: {group: ..., cancel-in-progress: true}` |
| secret 缺失静默失败 | `git push` 卡住等密码到超时 | `export GIT_TERMINAL_PROMPT=0` + 判空 `exit 1` |
| token 泄露到日志 | URL 里的 token 被 `set -x` 打印 | 避免 `set -x`；用 `::add-mask::` |
| `gh release upload` 偶发 502 | 单次失败整条流水线红 | 重试 3 次 + 退避 |
| fork 上跑发布 | fork 的 PR 尝试推送主仓库，403 | 判断 `github.repository` 不是主仓库就跳过 |
| 缓存 key 不带 lockfile hash | 依赖升级后仍用旧缓存 | `key: ...-${{ hashFiles('**/package-lock.json') }}` |

### 4.2 发布流水线骨架（tag → 构建 → Release）

```yaml
name: Release
on:
  push:
    tags: ['v*']
permissions:
  contents: write
concurrency:
  group: release-${{ github.ref_name }}
  cancel-in-progress: false
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: actions/setup-node@v4
        with:
          node-version: '22'
          cache: npm
      - run: npm ci && npm run build
      - uses: softprops/action-gh-release@v2
        with:
          files: dist/**
          generate_release_notes: true
```

## 5. GitHub → Gitee 镜像（对外分发）

目的：源码与产物在国内可下载。**两件事分开做，避免并发打架**：

1. **分支镜像**：一个 workflow，只同步 `main/master` 源码。
2. **Release 附件**：由发布 workflow 在创建 GitHub Release 后单独推 Gitee。

两者用不同 `concurrency` group，绝不能在同一个 job 里既推分支又推 Release。

### 5.1 分支镜像模板（实测可用）

```yaml
name: Sync to Gitee
on:
  push:
    branches: [main, master]
  workflow_dispatch:
concurrency:
  group: sync-gitee-branch
  cancel-in-progress: true
jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - name: Push to Gitee
        env:
          GITEE_TOKEN: ${{ secrets.GITEE_TOKEN }}
        run: |
          export GIT_TERMINAL_PROMPT=0
          if [ -z "$GITEE_TOKEN" ]; then
            echo "::error::缺少 GITEE_TOKEN secret"; exit 1
          fi
          # 只在主仓库执行，fork 跳过
          if [ "${{ github.repository }}" != "<owner>/<repo>" ]; then
            echo "非主仓库，跳过"; exit 0
          fi
          git remote add gitee "https://<gitee-user>:${GITEE_TOKEN}@gitee.com/<gitee-user>/<repo>.git"
          git fetch origin main
          git checkout -B main origin/main
          git push -u gitee main:main --force
```

注意：
- `--force` 在这条链路上是**必要**的（镜像要绝对一致），但只对 gitee 这个远端。
- Gitee 需先在网页端建同名空仓库，否则 push 404。
- token 用 Gitee「私人令牌」，权限勾 `projects`。

## 6. 脚本编写经验（CI 与本机运维脚本通用）

1. **bash 开头固定**：`set -euo pipefail`。少 `-u`，未定义变量就静默变空串。
2. **破坏性操作默认 dry-run**，加 `--apply` 才真跑，输出说清「即将删除 N 项」。
3. **退出码即契约**：`0` 成功且静默（cron/no-agent 场景），非 0 才输出原因。stdout 非空会被当消息发出去。
4. **幂等**：重复执行结果一致。删除用 `rm -f`、建库用 `IF EXISTS`、写文件用「临时文件 + `mv`」。
5. **原子写**：`tmp=$(mktemp -p $(dirname $f))` → 写完 `fsync` → `mv`。直接 `>` 覆盖，中途失败留半截文件。
6. **加锁**：并发写同一资源用 `flock`，拿不到锁要超时退出而不是死等。
7. **绝对路径**：CI 里 `cd` 上下文不可靠；用绝对路径或 `$(dirname $0)` 解析。
8. **判空再拼**：`${VAR:?message}` 让缺变量立刻失败，避免生成 `https://:token@` 这种坏串。
9. **日志带时间戳并落文件**：`echo "[$(date '+%F %T')] msg" | tee -a $LOG`。容器 stdout 会被轮转丢掉。
10. **危险动作前验前置条件**：删目录先确认名字匹配白名单（`case $d in /data/*) ;; *) exit 1;; esac`）。

反例（真实事故）：一个清理脚本认可 `--days 1` 却不做 dry-run、不校验库名，直接在生产库执行，清掉近 2 万行数据且无备份可恢复。**凡是「删」的逻辑，必须先在非生产目标上跑通。**

## 7. 项目升级规范（按交付形态分层）

**Web 服务、桌面客户端、安卓 App、嵌入式固件、浏览器扩展的「升级」是五个不同的问题**，混在一起谈必然写出谁都用不上的废话。判据一句话：**代码跑在谁的机器上、谁能决定它什么时候更新。**

| 形态 | 版本在谁手里 | 升级靠什么 | 最容易做错的 |
|---|---|---|---|
| Web 服务 | 你的服务器 | 部署即生效 | 以为要「客户端升级」；实际要的是**回滚点**+数据库迁移可逆 |
| 桌面客户端 | 用户电脑 | latest.json + 自动更新 | 版本清单与 Release 附件不一致；没签名 |
| 安卓 App | 用户设备 | 应用内检查/商店 | `versionCode` 不递增（客户端看不到更新）；换签名密钥（全员卸载重装） |
| 嵌入式固件 | 设备板子 | OTA / 烧录 | 没有 A/B 分区（断电变砖）；不能降级；版本不上报 |
| 浏览器扩展 | 浏览器 | 商店 / update_url | 加权限当普通改动；旧版本长期存在 |

核心提醒：**代码离你越远，升级机制越要在写第一行业务代码前就设计好。** Web 可以事后补，固件不行——固件升不上去就要拆机上门。

详细机制、闸门清单、真实事故点见 `references/upgrade-by-delivery-type.md`。

### 7.1 依赖升级

1. 先读上游 CHANGELOG 的 breaking changes，不要看版本号猜。
2. 小版本/补丁批量升，大版本单独一条 PR + 完整回归。
3. 升级前后各跑一次全量测试，记录失败数（基线对比，不允许新增失败）。
4. 锁定文件必须一起提交（`package-lock.json` / `uv.lock` / `poetry.lock`）。

### 7.2 运行时/镜像升级

- 镜像 tag 改动前确认 CI 与部署端支持新格式（`v1.3.8` vs `sha-abc123`）。
- **重建镜像前先给旧镜像打回滚 tag**（containerd 会 GC 未打 tag 的旧镜像，顺序反了就回滚不了）。

### 7.3 版本纪律（SemVer：什么时候发大版本、什么时候发小版本）

版本号跟着**发布动作**走，不跟着提交走——攒一批相关改动一次发布，禁止每个 commit 都 bump 版本。

| 变更类型 | 版本 | 判据 |
|---|---|---|
| 破坏性变更 | **major** | 对外接口/数据模型/配置格式/CLI 参数不兼容、删功能、部署方式变更需人工迁移 |
| 向后兼容新能力 | **minor** | 新接口/新端点/新文档章节；依赖大版本升级但行为兼容 |
| 修复与内部改动 | **patch** | bug 修复、文案、内部重构、依赖小版本升级 |

- 0.x 阶段接口允许不稳定，minor 即可含破坏性，但 CHANGELOG 里必须标 `BREAKING`。
- **禁止用 patch 夹带破坏性变更**——消费方按 patch 自动升级会直接挂。
- 破坏性变更发布前先发预告版（如 `-rc.1`）或至少提前在 CHANGELOG 的 Unreleased 段标注。
- tag 命名 `vX.Y.Z`，**不带日期后缀**；镜像 latest 仅作便捷别名，部署引用固定版本 tag。

### 7.4 git 提交规范（Conventional Commits）

- 格式：`<type>(<scope>): 中文描述`。type 取 `feat/fix/docs/refactor/test/chore/ci`。
- 破坏性变更：`feat!:` 或 body 里写 `BREAKING CHANGE: <说明与迁移方式>`。
- **一次提交只干一件事**；技能/文档改动与对应代码改动放**同一个提交**（回滚时不留半截）。
- 提交信息写「为什么」，diff 已经写了「是什么」。

### 7.5 CHANGELOG 规范（Keep a Changelog）

- 人工维护，不用工具自动生成 commit 罗列——条目面向使用者写**行为变化**，不写内部过程。
- 顶部常设 `## Unreleased` 段收集改动，发版时改成 `## vX.Y.Z - YYYY-MM-DD`。
- 分类用 `Added / Changed / Deprecated / Removed / Fixed / Security`；破坏性条目置顶并加 `**BREAKING**` 前缀，附迁移说明。
- 无外部消费者的内部项目可简化为「版本号 + 日期 + 一段话」，但**不许只有 tag 没有 CHANGELOG**。

### 7.6 发版清单

- 语义化版本 + tag（`vX.Y.Z`）+ CHANGELOG 条目，缺一不可。
- 发版前确认三处回滚点：代码 commit、镜像 tag、GitOps manifest。
- 发版后验证**外部可用入口**（NodePort/域名），不要只看 pod Ready。

### 7.7 与上游的关系要显式决策

fork 或引用开源项目时，把「跟 / 不跟 / 手动跟」写进 AGENTS.md，否则 agent 每次自作主张。

## 8. 初始化流程

```bash
mkdir -p myproj && cd myproj && git init
printf '%s\n' '__pycache__/' '.venv/' '.env' '!.env.example' '*.log' > .gitignore
# 写 README（§1.2）与 AGENTS.md（§2.2）
# 按判定表选 CI：内网 → .woodpecker.yml（§3.2）；对外 → .github/workflows/release.yml（§4.2）
# 凭据只放 .env.example 的键名，真值进 .env（已忽略）
git ls-files | grep -E '\.env$|\.pem$|\.key$' && echo '❌ 凭据入库' || echo '✅ 干净'
```

## 9. 发布前自检清单

- [ ] `.gitignore` 覆盖 `.env` / 构建产物 / 缓存
- [ ] `git ls-files` 里没有凭据文件
- [ ] README 快速开始能在干净环境三条命令跑通
- [ ] AGENTS.md 没有其他项目名、没有通用套话
- [ ] CI 只有一套，触发条件明确（tag/manual）
- [ ] 凭据只在 secret 里，yml 无明文
- [ ] 有回滚路径（旧镜像 tag / 上一个 release）
- [ ] 版本号、tag、CHANGELOG 三处一致

## 10. 已知边界

- 本技能给判据与模板，registry 地址、namespace、域名要按项目替换，不要照抄占位符上线。
- Woodpecker `when` 语法跨大版本有差异（旧版用 `pipeline:` 段），写前确认服务端版本。
- Gitee 同步是**单向镜像**（GitHub → Gitee），Gitee 上的 PR/issue 不会回流。

## 11. 扩展阅读

- `references/ci-coexistence.md` —— Woodpecker 与 GitHub Actions 共存时怎么分工（按交付物，不是按项目）
- `references/upgrade-by-delivery-type.md` —— Web / 桌面 / 安卓 / 固件 / 扩展 五种形态的升级机制与必备闸门

## 12. 技能文档随仓库走（skills/ 真源 + 分发链路）

给外部 agent 用的技能说明书，不要只活在某个 agent 的 profile 里：**真源放进项目仓库**，代码改了就在同一个提交里改技能，分发链路指过去。

```text
<repo>/skills/<name>/SKILL.md                         ← 唯一真源，跟代码一起 review / 回滚
/opt/code/static-deploy/skills/<name>    → 符号链接   ← 对外分发（git 里存 120000）
~/.hermes/profiles/<p>/skills/.../<name> → 同一链接   ← 本机 agent 读到的就是真源
```

四步落地：

1. 真源放 `<repo>/skills/<name>/SKILL.md`，frontmatter 写 `version`；同时在该仓库 `AGENTS.md` 加一条「改接口 / 数据模型 / 部署方式时，同一提交里改技能」。
2. 分发目录与 profile 目录都用 `ln -s` 指过去。**容器必须能解析同一个绝对路径**——nginx 的 `alias` 会跟随符号链接，但目标不在容器里就一律 404，所以给容器补一条**同路径**的 `:ro` bind mount。
3. `index.json`（version / sha256 / files）由分发仓库的 `sync_index.py` 从磁盘重算，**不要手改**；重算前先 `--check`，只有真不一致才写——否则每次都改顶层 `updated_at`，每次提交都产生噪音 diff。
4. 自动触发两条腿：仓库 `.githooks/post-commit` + `post-merge`（需 `git config core.hooksPath .githooks` 才生效），加宿主 systemd `path` 单元监听该文件（在服务器上直接编辑也能同步）。两处可能同时触发，脚本里用 `flock` 串行；推送失败只告警、不阻塞提交。

验收三件套（三处 sha256 必须一致）：

```bash
sha256sum <repo>/skills/<name>/SKILL.md
curl -s http://<dist>/<name>/SKILL.md | sha256sum
curl -s http://<dist>/index.json | python3 -c "import json,sys;s=[x for x in json.load(sys.stdin)['skills'] if x['name']=='<name>'][0];print(s['version'],s['sha256']['SKILL.md'])"
```

坑：

- **bind mount 挂子目录会被 git 操作打穿**：`rebase` / `checkout` 若删掉并重建该子目录，容器里的 mount 指向已删除的 inode，容器内目录变空、请求静默 404（重启容器才恢复）。挂**仓库根**或不会被整体删除的父目录。
- **改技能前先 `git fetch`，看远端是否领先**：本机工作区可能落后好几个提交（对方在别处开发完推上来了），直接 push 会被 non-fast-forward 拒掉；先 rebase 再继续，不要把本地当成最新。
- **同步前先判哪边是新的，别默认某一边落后**：profile、分发目录、项目仓库三处副本都可能各自演进。`diff` 两边 SKILL.md + 比对 frontmatter version，内容多/版本高的才是真源，从真源单向覆盖另一边；盲 cp 会把新改动冲掉。
- **技能内容要跟当前代码核对**（README + 路由/接口文件 + 实际 curl），不要照抄上一版；上游新增能力时按 minor 升版，并在「常见坑」表里补一条。
- 分发目录只放 `SKILL.md` 与 `references/*.md`：nginx 白名单只放行这两类，别指望从分发链路取脚本或其它文件。
