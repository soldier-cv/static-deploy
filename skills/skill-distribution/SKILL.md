---
name: skill-distribution
description: Use when 发布通用技能到 /.well-known 或用 skillctl 给 agent 装/升级技能。
tags: [skill, distribution, static-deploy, skillctl]
version: 1.0.0
author: Hermes coding agent
license: MIT
metadata:
  hermes:
    tags: [skill, publishing, static-deploy, skillctl, well-known]
    related_skills: [skill-publisher, project-repo-standards]
---

# 技能分发：发布端 + 安装升级端（skillctl）

## When to Use

- 要给外部机器上的 agent（OpenCode、Claude Code 等）安装或升级技能（用 skillctl）
- 要新建/修订一个供多个 agent 使用的通用技能并发布到 /.well-known/skills（static-deploy :8088）
- 改动了符号链接进分发目录的技能本体（如 resource-mgr）之后
- **惰性自检**：按本技能干活前，先跑一次下面的 `update --to <技能目录>`（约 1 秒），落后就 `--apply` 升级再动手


体系闭环：**发布端规范 = skill-publisher**（对外 http://100.64.0.88:8088/.well-known/skills/skill-publisher/SKILL.md），**安装/升级端 = skillctl**。做这类任务先装/读 skill-publisher，按它的规范走，不要凭记忆重写规则。

## 发布一个技能（固定三步）

1. 内容进真源：项目技能放该项目 repo（如 /opt/code/resource-mgr/skills/），通用平台技能直接写 /opt/code/static-deploy/skills/<name>/；分发目录里非平台技能用符号链接指回真源。
2. `cd /opt/code/static-deploy && python3 skills/sync_index.py` —— version/sha256/updated_at 全自动重建，**禁止手改 index.json**（手改会被下次同步覆盖）。
3. git commit + push。**符号链接技能是双仓库**：改动落在本体 repo（如 resource-mgr），分发 repo 里 git status 看不到它——两个 repo 都要 commit+push 并各自核对 0/0，只推一个等于没备份。

## 客户端安装/升级（所有技能统一）

**一行接入**（在目标 agent 机器上执行，`<技能目录>` 换成该 agent 的技能目录绝对路径；装完即具备本技能全部能力）：

```bash
curl -fsSL http://100.64.0.88:8088/.well-known/skillctl.py | python3 - bootstrap --to <技能目录>
```

bootstrap 会：自装 skillctl 副本到 `<技能目录>/.skillctl/skillctl.py`、安装 skill-distribution（本技能）与 skill-publisher（发布规范）、打印后续指引。之后的日常操作都用自装副本：

```bash
<技能目录>/.skillctl/skillctl.py list                       # 本地各技能版本 vs 注册表
<技能目录>/.skillctl/skillctl.py install <name> --to <绝对路径>   # 逐文件 sha256 校验
<技能目录>/.skillctl/skillctl.py update --to <绝对路径> [--apply] # 默认只检测，--apply 才升级
```

- `--to` 只接受**绝对路径**，相对路径直接被拒。
- 新技能的升级段落一律复制 skill-publisher 里的 skillctl 统一段，**禁止自造 curl 单文件升级命令**（历史上四个技能各写各的，已统一清理过一次；改动分发技能内容时顺手检查有没有旧式 curl 升级残留）。

## 硬约束

- 技能包 = 纯 md（SKILL.md + references/*.md）；nginx 白名单只放行 .md，.py/.sh 一律 404。
- frontmatter 必带 name（=目录名）/description（Use when 触发场景）/version（SemVer）。
- 发布前自检清单见 skill-publisher 第四节，含「客户端实测 install + update 报已是最新」。
- 远程 agent 贡献：clone soldier-cv/static-deploy → push → 服务器侧 pull + 重跑 sync_index 收尾（pull 后必须重跑，保证 index 与磁盘一致）。
