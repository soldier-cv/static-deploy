# skillctl

单文件技能注册表客户端。机器上有 Python 3 就能跑，只用标准库（`urllib`、`hashlib`、`json`、`argparse`、`pathlib`）。

真源是注册表索引：

```text
http://100.64.0.88:8088/.well-known/skills/index.json
```

索引为 v2。线上文件的顶层字段是 `schema: 2`。客户端也接受顶层 `version: 2`。
技能文件从索引 URL 推导：`.../.well-known/skills/<技能名>/<文件>`。
本地 `<目录>/<技能名>/.skillctl-manifest.json` 只记录这次安装，版本和校验和以索引为准。

仓库里的脚本绝对路径：`/opt/code/static-deploy/skills-client/skillctl.py`

## 1. 下载

其它机器只拷这一个文件：

```bash
curl -fsSL -o /tmp/skillctl.py http://100.64.0.88:8088/client/skillctl.py
chmod +x /tmp/skillctl.py
```

这个 URL 要等 `skillctl.py` 被放进 `/client/` 之后才能用。当前 nginx 的 `/client/` 映射的是仓库 `client-mcp/`，本任务不改部署。在这台机器上直接用仓库绝对路径：

```bash
python3 /opt/code/static-deploy/skills-client/skillctl.py --help
```

## 2. 安装

`--to` 用绝对路径（`~` 会展开）。技能落到 `<to>/<技能名>/`，`references/` 子目录原样保留。每个文件先校验 sha256，通过后才写入。

```bash
python3 /opt/code/static-deploy/skills-client/skillctl.py install project-repo-standards --to /home/xl/.hermes/skills
```

目标已存在时会拒绝。升级用下一节的 `update --apply`。整目录重装加上 `--force`。

## 3. 更新

先检查，不改文件：

```bash
python3 /opt/code/static-deploy/skills-client/skillctl.py update --to /home/xl/.hermes/skills
```

一致时标准输出只有一行 `已是最新`，退出码 0。
有落后时列出 `技能 → 本地版本 → 远端版本`，退出码仍是 0。确认后加 `--apply` 才升级，旧文件备份为 `<文件名>.bak-<旧版本>`。

```bash
python3 /opt/code/static-deploy/skills-client/skillctl.py update --to /home/xl/.hermes/skills --apply
```

再跑一次同样的 `--apply`，已是最新时不会改文件，也不会多写备份。

查看注册表，并对照本地安装记录：

```bash
python3 /opt/code/static-deploy/skills-client/skillctl.py list
python3 /opt/code/static-deploy/skills-client/skillctl.py list --to /home/xl/.hermes/skills
```

换注册表地址时加 `--index`，放在子命令前或后都可以：

```bash
python3 /opt/code/static-deploy/skills-client/skillctl.py --index http://100.64.0.88:8088/.well-known/skills/index.json list
```

## 各 agent 的技能目录

下表是这台机器上的绝对路径，作为 `--to` 传入。客户端按 `<to>/<技能名>/SKILL.md` 落盘。Hermes 要放进分类目录时，把分类目录当作 `--to`，例如 `/home/xl/.hermes/skills/devops`。

| Agent | 绝对路径 |
| --- | --- |
| Hermes | `/home/xl/.hermes/skills` |
| Hermes profile | `/home/xl/.hermes/profiles/coding/skills` |
| Claude Code | `/home/xl/.claude/skills` |
| OpenCode | `/home/xl/.config/opencode/skills` |
| Codex | `/home/xl/.agents/skills` |
| Cursor | `/home/xl/.cursor/skills` |
| Grok | `/home/xl/.grok/skills` |

Hermes 读取其它目录时，把该绝对路径写进 `/home/xl/.hermes/config.yaml` 的 `skills.external_dirs`。

## 行为

- 索引不可达（超时、HTTP 4xx、连接失败）时报明确错误，退出码非 0。
- sha256 不一致时中止。技能目录不会被创建，临时文件会删掉。
- 技能名只允许 `^[a-z][a-z0-9_-]{0,127}$`。`../`、绝对路径、超长名字都会拒绝。
- 索引里的文件路径同样拒绝 `..`、绝对路径和符号链接。
- 本地文件被改过、版本号却没变时，`update` 用 sha256 报告漂移，默认不覆盖。

## 已知限制

- 只接受 index.json v2，不解析别的格式。
- 不做并发锁。升级过程中断后，下一次 `update --apply` 会按索引重新校验。
- 单个技能文件上限 8MiB，索引上限 2MiB。
- 注册表删掉的旧文件会留在本地，客户端不主动删除。
- 直连 `--index` 的地址，不走 `HTTP_PROXY`，也不跟随重定向。
- 同一次升级里，同名备份 `<文件>.bak-<旧版本>` 已存在时会被这次的旧内容替换。
