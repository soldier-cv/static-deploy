---
name: skill-ops
description: Use when 新建/修订一个供多个 agent 使用的通用技能并发布到 /.well-known/skills（static-deploy，端口 8088）；或用 skillctl 给客户端安装/升级技能。覆盖编写规范、发布流程、版本纪律与 skillctl 用法。触发词：skillctl、技能安装、技能升级、技能分发、bootstrap、.well-known/skills、发布技能、新建技能、技能规范、sync_index、版本纪律、技能修改。
version: 1.0.0
author: Hermes coding agent
license: MIT
metadata:
  hermes:
    tags: [skill, publishing, distribution, static-deploy, well-known, skillctl, versioning]
    related_skills: [app-testing, static-deploy-mcp, project-repo-standards]
---

# 技能运营：编写 / 发布 / 安装 / 升级（skill-ops）

> 版本记录：1.0.0 由 skill-publisher v1.3.0（编写规范、发布三步、版本纪律）与 skill-distribution v1.1.0（skillctl 用法、快速接入）合并首发。

> **相关技能**：
> - [app-testing](../app-testing/SKILL.md) — 应用全链路测试（接口 + E2E）
> - [static-deploy-mcp](../static-deploy-mcp/SKILL.md) — static-deploy 静态资源分发客户端
> - [project-repo-standards](../project-repo-standards/SKILL.md) — 项目工程规范与真源分发链接

## 快速接入（一行，agent 执行这一条即可完成全部自举）

```bash
curl -fsSL http://100.64.0.88:8088/.well-known/skillctl.py | python3 - bootstrap --to <本agent的技能目录绝对路径>
```

执行后本技能与 skillctl 副本已装到技能目录，之后所有用法（升级、装其它技能、发布新技能）都在本文件下文，无需再找任何文档。

---

## 版本与升级（统一走 skillctl）

更新源（唯一权威）：`http://100.64.0.88:8088/.well-known/skills/index.json`

```bash
# 首次：下载通用客户端（每台机器一次）
curl -fsSL http://100.64.0.88:8088/.well-known/skillctl.py -o skillctl.py && chmod +x skillctl.py

# 干活前惰性检查（约 1 秒）：落后就先升级，再动手
./skillctl.py list                                  # 本地各技能版本 vs 注册表
./skillctl.py update --to <你的技能目录>             # 默认只检测（--to 用绝对路径）
./skillctl.py update --to <你的技能目录> --apply     # 确认后才升级（逐文件 sha256 校验）
```

版本语义：`patch` 修错别字不改结论；`minor` 新增章节/接口；`major` 推翻既有结论（需重读全文）。

**版本纪律（华总 2026-11-12 定案，违反 = 打回）：**
- 技能版本**只反映技能内容本身的变更幅度**，禁止与外部服务版本对齐跳号（resource-mgr 技能曾因「跟服务大版本对齐」从 1.1.0 连跳 4.0.0，错误做法，已废弃）。
- 大版本要克制：`major` 仅当技能的核心结论/命令被推翻、读者必须重读全文时才允许；普通增改一律 minor/patch。
- 每次版本变更在文首「版本记录」注记一行（版本号 + 一句话改了什么），让人不看 diff 也能判断要不要重读。
- 禁止用 `patch` 夹带行为变更（消费方按 patch 自动升级会静默踩坑）。

---

## 第一章 编写规范

1. **目录结构**：`<name>/SKILL.md`（必须）+ `references/`、`scripts/`、`assets/`、`templates/` 子目录（可选）。
   **可分发扩展白名单**（nginx 与 sync_index.py 同步限定）：`md|py|sh|js|ps1|yaml|yml|json|txt|toml|bat|cmd`；
   路径穿越（`..`）、隐藏文件、白名单外扩展（如 .exe）、目录枚举一律 404。二进制与无扩展名文件不进技能包。
2. **frontmatter 必带**：`name`（小写连字符，与目录名一致）、`description`（Use when <触发场景>. 一句话行为）、
   `version`（SemVer 三段）。可选 `metadata.hermes.tags/related_skills`。
3. **description 是检索入口**：含触发关键词，不含「本技能介绍了…」这类自指废话。
4. **升级段落**：直接复制上面「版本与升级（统一走 skillctl）」整段进你的技能，不许自造 curl 升级命令
   （2026-11-12 已清理过一批各写各的历史遗留）。
5. **内容纪律**：写「怎么做 + 为什么 + 坑」，不写时间戳/事故流水账；路径用绝对路径，禁 `~` 展开歧义。
6. **只发自有技能**：分发体系只放我们自己编写/拥有的技能；第三方开源技能（哪怕 MIT）不进 /.well-known/skills 分发，需要用就只在本机安装（华总定案）。自有技能可引用第三方工具作工具链，但引用 ≠ 分发。

---

## 第二章 发布与同步流程

### 发布端规范

本技能是**发布 + 安装一体化规范**。凡是「这个技能/文档要让其它机器上的 agent（OpenCode、Claude Code 等）也能装」的场景，都按本规范执行。

真源原则：**技能内容随代码开发**——属于某项目的放该项目 repo（如 /opt/code/resource-mgr/skills/），
通用平台类技能直接放分发仓库。分发目录 `/opt/code/static-deploy/skills/` 里非平台技能用**符号链接**指回真源。

#### 发布三步（顺序固定，缺一不可）

```bash
# 1. 内容就位：写到真源，cp 或 ln -s 进分发目录 /opt/code/static-deploy/skills/<name>/
# 2. 重建注册表（version/sha256/updated_at 全自动，禁止手改 index.json）
cd /opt/code/static-deploy && python3 skills/sync_index.py
# 3. git add/commit/push（真源在别的 repo 的，那个 repo 也要 commit+push）
```

**CI 自动同步 GitHub 镜像**：push 到 static-deploy main 后，Woodpecker 流水线（`.woodpecker.skills.yaml`）会自动完成 `sync_index` 与镜像仓库同步，通常无需手动跑 `/opt/code/skills/sync_from_static_deploy.sh`。脚本保留为 CI 故障时的 fallback。

- 新建技能：`mkdir /opt/code/static-deploy/skills/<name>/` → 写 SKILL.md → 三步。
- 已有技能改版：bump frontmatter `version` → 同步真源/分发目录 → 三步。
- **index.json 由 sync_index.py 从磁盘生成**，任何手改都会在下次同步被覆盖。

### 远程 agent 怎么贡献

不在服务器上的 agent 不能直写 /opt/code：`git clone https://github.com/soldier-cv/static-deploy` →
按本章规范加技能 → push → 由服务器侧 agent `git pull --ff-only` + 跑 sync_index.py 收尾
（pull 后必须重跑 sync_index，保证 index 与磁盘一致）。

---

## 第三章 安装 / 升级端 skillctl 用法

体系闭环：**编写规范 + 发布流程 = 本文件上半部分**，**安装 / 升级 = skillctl**。做这类任务先读本文件前半部分了解规范，再用下半部分的 skillctl 操作。

### 客户端安装 / 升级（所有技能统一）

一行接入（在目标 agent 机器上执行，`<技能目录>` 换成该 agent 的技能目录绝对路径）：

```bash
curl -fsSL http://100.64.0.88:8088/.well-known/skillctl.py | python3 - bootstrap --to <技能目录>
```

bootstrap 会：自装 skillctl 副本到 `<技能目录>/.skillctl/skillctl.py`、安装 skill-ops（本技能）、打印后续指引。之后的日常操作都用自装副本：

```bash
<技能目录>/.skillctl/skillctl.py list                       # 本地各技能版本 vs 注册表
<技能目录>/.skillctl/skillctl.py install <name> --to <绝对路径>   # 逐文件 sha256 校验
<技能目录>/.skillctl/skillctl.py update --to <绝对路径> [--apply] # 默认只检测，--apply 才升级
```

- `--to` 只接受**绝对路径**，相对路径直接被拒。
- 新技能的升级段落一律复制本文件里「版本与升级」统一段，**禁止自造 curl 单文件升级命令**（历史上四个技能各写各的，已统一清理过一次；改动分发技能内容时顺手检查有没有旧式 curl 升级残留）。

### 交付纪律（华总定案）

- 给外部 agent 的任何机制，**交付形态 = 一行接入命令 + 用法全部写进技能文档**：agent 只会被给一条可粘贴的命令，后续怎么调用、怎么升级必须能在装好的 SKILL.md 里自己读到，不许依赖聊天记录或人转述。新机制落地时问自己一句「agent 装完这条命令后，不看聊天还知道怎么用吗」，不知道就把用法补进技能再交付。
- 改 bootstrap 默认安装集这类「一行命令的承诺」必须与技能文档同步——文档写了 bootstrap 装什么，代码就得真的装什么（文档与实现漂移会让 agent 按文档操作失败）。

### 硬约束

- 技能包 = 纯 md（SKILL.md + references/*.md）+ 白名单内的辅助文件；nginx 白名单放行 `md|py|sh|js|ps1|yaml|yml|json|txt|toml|bat|cmd`，其余 404。
- frontmatter 必带 name（=目录名）/description（Use when 触发场景）/version（SemVer）。
- 远程 agent 贡献：clone soldier-cv/static-deploy → push → 服务器侧 pull + 重跑 sync_index 收尾（pull 后必须重跑，保证 index 与磁盘一致）。

---

## 自检清单（发布前过一遍）

- [ ] frontmatter 有 name/version/description，目录名 = name
- [ ] 版本按 SemVer bump，major 变更在文首写明影响
- [ ] 升级段落是 skillctl 统一段，无自造 curl 命令
- [ ] 技能是自有的（第三方技能不分发）；无白名单外扩展名的文件；无 token/内网敏感地址（skillctl 地址 8088 属公开内网服务，可留）
- [ ] sync_index.py 输出新版本号；`curl http://100.64.0.88:8088/.well-known/skills/<name>/SKILL.md` 返回 200
- [ ] 客户端实测：`skillctl.py install <name> --to <绝对路径>` 落盘且 `update` 报「已是最新」
