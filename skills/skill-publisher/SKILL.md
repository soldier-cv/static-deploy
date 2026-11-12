---
name: skill-publisher
description: Use when 新建/修订一个供多个 agent 使用的通用技能并发布到 /​.well-known/skills 分发（static-deploy，端口 8088）；覆盖编写规范、发布三步、版本纪律与 skillctl 升级段模板。
version: 1.0.0
author: Hermes coding agent
license: MIT
metadata:
  hermes:
    tags: [skill, publishing, static-deploy, well-known, skillctl, versioning]
    related_skills: [project-repo-standards, static-deploy-mcp]
---

# 技能发布规范：写一个通用技能并发布到 /.well-known/skills

本技能是**发布端**的规范；**安装/升级端**是 skillctl（http://100.64.0.88:8088/.well-known/skillctl.py）。
凡是「这个技能/文档要让其它机器上的 agent（OpenCode、Claude Code 等）也能装」的场景，都按本规范发布。

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

## 一、编写规范

1. **目录结构**：`<name>/SKILL.md`（必须）+ `references/*.md`（可选）。技能包 = 纯文档；
   **不放可执行脚本**——nginx 白名单只放行 `.md`，`.py`/`.sh` 一律 404（skillctl.py 是 nginx 精确 location 的唯一例外）。
2. **frontmatter 必带**：`name`（小写连字符，与目录名一致）、`description`（Use when <触发场景>. 一句话行为）、
   `version`（SemVer 三段）。可选 `metadata.hermes.tags/related_skills`。
3. **description 是检索入口**：含触发关键词，不含「本技能介绍了…」这类自指废话。
4. **升级段落**：直接复制上面「版本与升级（统一走 skillctl）」整段进你的技能，不许自造 curl 升级命令
   （2026-11-12 已清理过一批各写各的历史遗留）。
5. **内容纪律**：写「怎么做 + 为什么 + 坑」，不写时间戳/事故流水账；路径用绝对路径，禁 `~` 展开歧义。

## 二、发布三步（顺序固定，缺一不可）

真源原则：**技能内容随代码开发**——属于某项目的放该项目 repo（如 /opt/code/resource-mgr/skills/），
通用平台类技能直接放分发仓库。分发目录 `/opt/code/static-deploy/skills/` 里非平台技能用**符号链接**指回真源。

```bash
# 1. 内容就位：写到真源，cp 或 ln -s 进分发目录 /opt/code/static-deploy/skills/<name>/
# 2. 重建注册表（version/sha256/updated_at 全自动，禁止手改 index.json）
cd /opt/code/static-deploy && python3 skills/sync_index.py
# 3. git add/commit/push（真源在别的 repo 的，那个 repo 也要 commit+push）
```

- 新建技能：`mkdir /opt/code/static-deploy/skills/<name>/` → 写 SKILL.md → 三步。
- 已有技能改版：bump frontmatter `version` → 同步真源/分发目录 → 三步。
- **index.json 由 sync_index.py 从磁盘生成**，任何手改都会在下次同步被覆盖。

## 三、远程 agent 怎么贡献

不在服务器上的 agent 不能直写 /opt/code：`git clone https://github.com/soldier-cv/static-deploy` →
按第一节规范加技能 → push → 由服务器侧 agent `git pull --ff-only` + 跑 sync_index.py 收尾
（pull 后必须重跑 sync_index，保证 index 与磁盘一致）。

## 四、自检清单（发布前过一遍）

- [ ] frontmatter 有 name/version/description，目录名 = name
- [ ] 版本按 SemVer bump，major 变更在文首写明影响
- [ ] 升级段落是 skillctl 统一段，无自造 curl 命令
- [ ] 无 .py/.sh 等非 md 文件；无 token/内网敏感地址（skillctl 地址 8088 属公开内网服务，可留）
- [ ] sync_index.py 输出新版本号；`curl http://100.64.0.88:8088/.well-known/skills/<name>/SKILL.md` 返回 200
- [ ] 客户端实测：`skillctl.py install <name> --to <绝对路径>` 落盘且 `update` 报「已是最新」
