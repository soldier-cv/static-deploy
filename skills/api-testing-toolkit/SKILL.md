---
name: api-testing-toolkit
description: Use when 前端未就绪时要由 AI 驱动接口测试：为项目初始化接口测试包（tools/api-testing 脚手架、鉴权链、docs 参考），或在已初始化项目里跑回归/冒烟/story 测试、造数验证、探索新接口、缺陷定位与修复闭环。触发词：接口测试、测试包初始化、跑回归、跑冒烟、story 测试、造数验证、tools/api-testing。
version: 1.0.0
---

# 接口测试工具包 (api-testing-toolkit)

> 思想: 无前端时, 由 AI 按 story 驱动, 完成「登录 → 调接口 → 查库验证 → 造数 → 报告」闭环。
> 实现: 项目内 `tools/api-testing`(MCP server + story runner + docs + cases), 由本技能脚手架初始化。

## Hard Gate

- 项目内**已存在 `tools/api-testing`** → 可直接执行测试工作流(下文 B/C/D)。
- 项目内**不存在**且用户要求初始化/搭测试能力 → 执行初始化工作流(下文 A)。
- 都不满足(临时 HTTP 调试、其他项目) → 不使用本技能。

## A. 初始化工作流(每个项目一次性)

1. **摸清事实**(只读): 技术栈、路由清单与路径前缀、鉴权方式(token 传递头/登录接口/mock 能力)、
   统一响应体(HTTP 状态码优先 or `code==0` 包装)、数据库类型与连接(.env, 端口常非默认)、日志落盘与否。
2. **复制脚手架**: 将本技能目录下 `scaffold/` 整体复制为 `<project>/tools/api-testing/`（内容见 `references/scaffold-mcp-server.md` 与 `references/scaffold-project.md`，按节还原）
   (PowerShell: `Copy-Item -Recurse`)。
3. **写 `mcp-server/env.example.json`**: 按摸清的事实填 baseUrl/healthPath/auth 链/db 连接/writeTables 白名单/fixtures。
   再复制为 `local/mcp-env.json` 填真实凭据(`local/` 已 gitignore, 凭据严禁入库)。
4. **生成 docs/**: `controllers-overview.md`(全量端点清单)、`api-reference.md`(调用知识: 鉴权/headers/响应约定/枚举/坑)、
   `db-reference.md`(库连接说明、表分组、数据约定)。依据路由源码生成, 不臆测。
5. **安装与自检**: `cd tools/api-testing/mcp-server && npm install && npm run check`(token+db+health 探针)。
6. **登记**: 在 `cases/README.md` 写入首个模块; 提交边界见 scaffold README。

### env 配置要点(通用内核的三个可配置面)

- `auth.mode`: `"static"`(api.token 直接用) 或 `"chain"`(多步登录链: steps 数组, 每步 save 点路径取值,
  支持 `{{var}}` 模板、`optional:true` 失败跳过、`once:true` 已有值则跳过——用于幂等建家/建租户)。
- 响应成功判定: 默认 HTTP<400 即成功; Java 式 `{code,msg,data}` 项目加 `api.codeField:"code"` + `api.okValue:0`。
- `db.driver`: `"postgres"` 或 `"mysql"`, 其余连接字段同名。

## B. 回归测试(默认, 快且稳)

```bash
cd tools/api-testing/mcp-server && npm run test        # regression:true 的模块
npm run test:smoke                                      # 各模块 smoke 子集
node src/run-tests.js --module auth,family --smoke      # 组合冒烟(新功能开工先跑)
node src/run-tests.js --case 需求标题                    # 单条需求链
node src/run-tests.js --story X-01,X-02                 # 定点回归
node src/run-tests.js --list                            # 列出全部链
```

退出码: `0`=全过, `1`=有 FAIL, `2`=环境阻塞(ENV_BLOCKED, 先查服务/DB 是否启动, 不是代码缺陷)。
报告写在各需求目录 `report/latest.md`(带时间戳历史最多 5 份)。

## C. 探索新接口(AI + MCP)

顺序: `health` → `fixture`(取现成业务数据) → `api` + `wait_until` + `sql`(断言)。
500/异常时看服务端输出(tail_log 仅当项目配置了 log.dir)。**不要**让 AI 逐步重跑已固化 story。

```text
对 AI 说: "按 cases/<日期-标题>/story.md 探索 XX 功能, 完成后写成 stories.js 并 --case 回归"
```

## D. 新增功能测试

复制 `cases/_template` → `cases/<YYYY-MM-DD>-<中文标题>/`, 写 `story.md`(场景表)+ `stories.js`(可执行断言),
`node src/run-tests.js --case <中文标题>` 验证。要进日常回归给模块设 `regression:true`。

story 模块格式:

```js
export const module = { id: "xxx", title: "功能名", smoke: ["X-01"], regression: true };
export const stories = [
  { id: "X-01", fn: storyX01, endpoints: ["POST /api/xxx"], tags: ["core"] },
];
// story fn 收到 ctx: ctx.api(method,path,{query,body,headers}) / ctx.get/post/put/patch/del /
// ctx.sql(text,params 只读) / ctx.waitUntilApi(...) / ctx.assert(cond,msg,detail?) / ctx.info(msg)
```

## 方法论(5 步, 缺一不可)

| # | 步骤 | 产物 |
|---|---|---|
| 1 | 数据库信息 | `docs/db-reference.md` |
| 2 | 接口全貌 | `docs/controllers-overview.md` + `docs/api-reference.md` |
| 3 | 场景串成 story | `cases/<日期-中文标题>/story.md` + `stories.js` |
| 4 | 结论与缺陷(PASS/FAIL/定位) | 该链 `report/latest.md` + `defects.json`(open→fixed→verified/wontfix) |
| 5 | 优化回写(下次怎么做更好) | 本技能/scaffold README 演进记录 |

## 断言与数据约定(必读)

- 成功判定以项目响应约定为准(Hono 系: HTTP 状态码 + `{code,message}` 错误体; Java 系: codeField)。
- 数字精度: Long/雪花 ID 若序列化为字符串, 等值断言一律 `Number(x)===Number(y)`; 金额字符串同理。
- 逻辑删除表: DB 断言手动加 `deleted=0`(或项目等价字段)。
- 时间: 比较用相对差, 不做绝对编码比对。
- **造数原则**: ①先用接口/fixture 取现成数据复用; ②造数前先 sql 查重; ③必须新建时名称用
  **`AT-中文业务语义`**(如 `AT-邀请码加入-建家`), 严禁机读码/时间戳尾巴/无语义缩写; 一次造数多用例共享;
  ④默认不删测试数据(留库追溯), 用户明确要求才删, **严禁动真实业务数据**。
- 下单/建资源所需数据走接口(fixture/api), `sql` 仅用于断言验证与查重。

## 安全红线

- 凭据只在 `tools/api-testing/local/mcp-env.json`(gitignore), 严禁写入 story/docs/报告/提交。
- `sql_exec`: 仅 INSERT/UPDATE 且表必须在 `dbSafety.writeTables` 白名单; UPDATE 必须带 WHERE;
  DELETE/DROP/TRUNCATE 一律禁止(可选开 `allowSafeDdl` 放行 ALTER/CREATE)。
- 报告中 token 一律掩码(工具自动处理, 不要手工粘贴完整 token)。
- 测试后 `git status` 复核: 只允许预期用例/文档改动; report/local/node_modules 不入库。

## 禁止事项(Anti-patterns)

- ❌ 手动 sleep 循环轮询异步状态(用 `wait_until`)
- ❌ 不跑 `health` 就开始业务断言(环境问题会被误判为代码缺陷)
- ❌ 用 AI 逐步重跑已固化的全套 story(用 `npm run test`)
- ❌ 查库取下单/造数所需业务数据(走接口 fixture)
- ❌ 未授权删库、白名单外表写入、凭据入库

## 随附资产对照（分发通道只放行 Markdown）

| 原始路径 | 技能包内位置 |
|---|---|
| `scaffold/mcp-server/env.example.json` | `references/scaffold-mcp-server.md`（`## scaffold/mcp-server/env.example.json` 节） |
| `scaffold/mcp-server/package.json` | `references/scaffold-mcp-server.md`（`## scaffold/mcp-server/package.json` 节） |
| `scaffold/mcp-server/src/index.js` | `references/scaffold-mcp-server.md`（`## scaffold/mcp-server/src/index.js` 节） |
| `scaffold/mcp-server/src/run-tests.js` | `references/scaffold-mcp-server.md`（`## scaffold/mcp-server/src/run-tests.js` 节） |
| `scaffold/mcp-server/src/lib/auth.js` | `references/scaffold-mcp-server.md`（`## scaffold/mcp-server/src/lib/auth.js` 节） |
| `scaffold/mcp-server/src/lib/config.js` | `references/scaffold-mcp-server.md`（`## scaffold/mcp-server/src/lib/config.js` 节） |
| `scaffold/mcp-server/src/lib/db.js` | `references/scaffold-mcp-server.md`（`## scaffold/mcp-server/src/lib/db.js` 节） |
| `scaffold/mcp-server/src/lib/harness.js` | `references/scaffold-mcp-server.md`（`## scaffold/mcp-server/src/lib/harness.js` 节） |
| `scaffold/mcp-server/src/lib/http.js` | `references/scaffold-mcp-server.md`（`## scaffold/mcp-server/src/lib/http.js` 节） |
| `scaffold/mcp-server/src/lib/log.js` | `references/scaffold-mcp-server.md`（`## scaffold/mcp-server/src/lib/log.js` 节） |
| `scaffold/mcp-server/src/lib/report.js` | `references/scaffold-mcp-server.md`（`## scaffold/mcp-server/src/lib/report.js` 节） |
| `scaffold/README.md` | `references/scaffold-project.md`（`## scaffold/README.md` 节） |
| `scaffold/defects.json` | `references/scaffold-project.md`（`## scaffold/defects.json` 节） |
| `scaffold/cases/README.md` | `references/scaffold-project.md`（`## scaffold/cases/README.md` 节） |
| `scaffold/cases/_template/stories.js` | `references/scaffold-project.md`（`## scaffold/cases/_template/stories.js` 节） |
| `scaffold/cases/_template/story.md` | `references/scaffold-project.md`（`## scaffold/cases/_template/story.md` 节） |
| `scaffold/docs/api-reference.template.md` | `references/scaffold-project.md`（`## scaffold/docs/api-reference.template.md` 节） |
| `scaffold/docs/db-reference.template.md` | `references/scaffold-project.md`（`## scaffold/docs/db-reference.template.md` 节） |

> 本技能不含可执行文件：脚手架各文件以 Markdown 形式随包，落地时按 `## 路径` 写回磁盘。

## 更新与升级（统一走 skillctl）

更新源：`http://100.64.0.88:8088/.well-known/skills/index.json`

```bash
./skillctl.py list                                  # 本地各技能版本 vs 注册表
./skillctl.py update --to <你的技能目录>             # 默认只检测
./skillctl.py update --to <你的技能目录> --apply     # 确认后升级（逐文件 sha256 校验）
```
