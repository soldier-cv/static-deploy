---
name: app-testing
description: Use when 需要对应用进行全链路测试验证：在前端未就绪时由 AI 驱动接口测试（tools/api-testing 脚手架、鉴权链、跑回归、跑冒烟、story 测试、造数验证与缺陷定位），或对本地 Web 应用做端到端功能测试、DOM 元素交互与行为调试（Playwright 测试、Web 功能测试、E2E 测试、DOM 交互、with_server 驱动多服务生命周期）。触发词：接口测试、测试包初始化、跑回归、跑冒烟、story 测试、tools/api-testing、Playwright 测试、Web 功能测试、E2E 测试、DOM 交互、with_server。
version: 1.0.0
author: Hermes coding agent
license: Apache-2.0
metadata:
  hermes:
    tags: [app-testing, api-testing, playwright, e2e, testing, browser-automation, webapp, mcp, story-testing, regression]
    related_skills: [ui-acceptance, selfapp, project-repo-standards]
---

# 应用测试套件 (app-testing)

> 版本记录：1.0.0 由 api-testing-toolkit v1.0.0 + webapp-testing v1.0.0 合并首发（2026-11-13）。

> **相关技能**：
> - [ui-acceptance](../ui-acceptance/SKILL.md) — 统一 UI 验收体系（截图比对、视觉回归与前端交付审查）
> - [selfapp](../selfapp/SKILL.md) — 自研全栈应用开发指南，包含 Self-App 场景特有的多租户 IDOR、微信登录与协议签署测试用例
> - [project-repo-standards](../project-repo-standards/SKILL.md) — 项目工程结构与 CI 规范

## 快速路由

根据当前开发阶段与测试诉求选择测试路径：

| 诉求与场景 | 推荐路径 | 核心手段 |
|---|---|---|
| 前端未就绪 / 纯接口测试 | **[第一章 接口测试](#第一章-接口测试)** | `tools/api-testing`（MCP server + story runner + docs + cases） |
| 页面交互 / Web E2E 测试 | **[第二章 Web 功能测试](#第二章-web-功能测试)** | Python Playwright、`with_server.py` 多服务生命周期管理、DOM 侦察与交互 |

---

## 第一章 接口测试

> 思想: 无前端时, 由 AI 按 story 驱动, 完成「登录 → 调接口 → 查库验证 → 造数 → 报告」闭环。
> 实现: 项目内 `tools/api-testing`(MCP server + story runner + docs + cases), 由本技能脚手架初始化。

### Hard Gate

- 项目内**已存在 `tools/api-testing`** → 可直接执行测试工作流(下文 B/C/D)。
- 项目内**不存在**且用户要求初始化/搭测试能力 → 执行初始化工作流(下文 A)。
- 都不满足(临时 HTTP 调试、其他项目) → 不使用本技能。

### A. 初始化工作流(每个项目一次性)

1. **摸清事实**(只读): 技术栈、路由清单与路径前缀、鉴权方式(token 传递头/登录接口/mock 能力)、
   统一响应体(HTTP 状态码优先 or `code==0` 包装)、数据库类型与连接(.env, 端口常非默认)、日志落盘与否。
2. **复制脚手架**: 将本技能目录下 `scaffold/` 整体复制为 `<project>/tools/api-testing/`（内容见 `references/api-scaffold-mcp-server.md` 与 `references/api-scaffold-project.md`，按节还原）
   (PowerShell: `Copy-Item -Recurse`)。
3. **写 `mcp-server/env.example.json`**: 按摸清的事实填 baseUrl/healthPath/auth 链/db 连接/writeTables 白名单/fixtures。
   再复制为 `local/mcp-env.json` 填真实凭据(`local/` 已 gitignore, 凭据严禁入库)。
4. **生成 docs/**: `controllers-overview.md`(全量端点清单)、`api-reference.md`(调用知识: 鉴权/headers/响应约定/枚举/坑)、
   `db-reference.md`(库连接说明、表分组、数据约定)。依据路由源码生成, 不臆测。
5. **安装与自检**: `cd tools/api-testing/mcp-server && npm install && npm run check`(token+db+health 探针)。
6. **登记**: 在 `cases/README.md` 写入首个模块; 提交边界见 scaffold README。

#### env 配置要点(通用内核的三个可配置面)

- `auth.mode`: `"static"`(api.token 直接用) 或 `"chain"`(多步登录链: steps 数组, 每步 save 点路径取值,
  支持 `{{var}}` 模板、`optional:true` 失败跳过、`once:true` 已有值则跳过——用于幂等建家/建租户)。
- 响应成功判定: 默认 HTTP<400 即成功; Java 式 `{code,msg,data}` 项目加 `api.codeField:"code"` + `api.okValue:0`。
- `db.driver`: `"postgres"` 或 `"mysql"`, 其余连接字段同名。

### B. 回归测试(默认, 快且稳)

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

### C. 探索新接口(AI + MCP)

顺序: `health` → `fixture`(取现成业务数据) → `api` + `wait_until` + `sql`(断言)。
500/异常时看服务端输出(tail_log 仅当项目配置了 log.dir)。**不要**让 AI 逐步重跑已固化 story。

```text
对 AI 说: "按 cases/<日期-标题>/story.md 探索 XX 功能, 完成后写成 stories.js 并 --case 回归"
```

### D. 新增功能测试

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

### 方法论(5 步, 缺一不可)

| # | 步骤 | 产物 |
|---|---|---|
| 1 | 数据库信息 | `docs/db-reference.md` |
| 2 | 接口全貌 | `docs/controllers-overview.md` + `docs/api-reference.md` |
| 3 | 场景串成 story | `cases/<日期-中文标题>/story.md` + `stories.js` |
| 4 | 结论与缺陷(PASS/FAIL/定位) | 该链 `report/latest.md` + `defects.json`(open→fixed→verified/wontfix) |
| 5 | 优化回写(下次怎么做更好) | 本技能/scaffold README 演进记录 |

### 断言与数据约定(必读)

- 成功判定以项目响应约定为准(Hono 系: HTTP 状态码 + `{code,message}` 错误体; Java 系: codeField)。
- 数字精度: Long/雪花 ID 若序列化为字符串, 等值断言一律 `Number(x)===Number(y)`; 金额字符串同理。
- 逻辑删除表: DB 断言手动加 `deleted=0`(或项目等价字段)。
- 时间: 比较用相对差, 不做绝对编码比对。
- **造数原则**: ①先用接口/fixture 取现成数据复用; ②造数前先 sql 查重; ③必须新建时名称用
  **`AT-中文业务语义`**(如 `AT-邀请码加入-建家`), 严禁机读码/时间戳尾巴/无语义缩写; 一次造数多用例共享;
  ④默认不删测试数据(留库追溯), 用户明确要求才删, **严禁动真实业务数据**。
- 下单/建资源所需数据走接口(fixture/api), `sql` 仅用于断言验证与查重。

### 安全红线

- 凭据只在 `tools/api-testing/local/mcp-env.json`(gitignore), 严禁写入 story/docs/报告/提交。
- `sql_exec`: 仅 INSERT/UPDATE 且表必须在 `dbSafety.writeTables` 白名单; UPDATE 必须带 WHERE;
  DELETE/DROP/TRUNCATE 一律禁止(可选开 `allowSafeDdl` 放行 ALTER/CREATE)。
- 报告中 token 一律掩码(工具自动处理, 不要手工粘贴完整 token)。
- 测试后 `git status` 复核: 只允许预期用例/文档改动; report/local/node_modules 不入库。

### 禁止事项(Anti-patterns)

- ❌ 手动 sleep 循环轮询异步状态(用 `wait_until`)
- ❌ 不跑 `health` 就开始业务断言(环境问题会被误判为代码缺陷)
- ❌ 用 AI 逐步重跑已固化的全套 story(用 `npm run test`)
- ❌ 查库取下单/造数所需业务数据(走接口 fixture)
- ❌ 未授权删库、白名单外表写入、凭据入库

### 随附资产对照（分发通道只放行 Markdown）

| 原始路径 | 技能包内位置 |
|---|---|
| `scaffold/mcp-server/env.example.json` | `references/api-scaffold-mcp-server.md`（`## scaffold/mcp-server/env.example.json` 节） |
| `scaffold/mcp-server/package.json` | `references/api-scaffold-mcp-server.md`（`## scaffold/mcp-server/package.json` 节） |
| `scaffold/mcp-server/src/index.js` | `references/api-scaffold-mcp-server.md`（`## scaffold/mcp-server/src/index.js` 节） |
| `scaffold/mcp-server/src/run-tests.js` | `references/api-scaffold-mcp-server.md`（`## scaffold/mcp-server/src/run-tests.js` 节） |
| `scaffold/mcp-server/src/lib/auth.js` | `references/api-scaffold-mcp-server.md`（`## scaffold/mcp-server/src/lib/auth.js` 节） |
| `scaffold/mcp-server/src/lib/config.js` | `references/api-scaffold-mcp-server.md`（`## scaffold/mcp-server/src/lib/config.js` 节） |
| `scaffold/mcp-server/src/lib/db.js` | `references/api-scaffold-mcp-server.md`（`## scaffold/mcp-server/src/lib/db.js` 节） |
| `scaffold/mcp-server/src/lib/harness.js` | `references/api-scaffold-mcp-server.md`（`## scaffold/mcp-server/src/lib/harness.js` 节） |
| `scaffold/mcp-server/src/lib/http.js` | `references/api-scaffold-mcp-server.md`（`## scaffold/mcp-server/src/lib/http.js` 节） |
| `scaffold/mcp-server/src/lib/log.js` | `references/api-scaffold-mcp-server.md`（`## scaffold/mcp-server/src/lib/log.js` 节） |
| `scaffold/mcp-server/src/lib/report.js` | `references/api-scaffold-mcp-server.md`（`## scaffold/mcp-server/src/lib/report.js` 节） |
| `scaffold/README.md` | `references/api-scaffold-project.md`（`## scaffold/README.md` 节） |
| `scaffold/defects.json` | `references/api-scaffold-project.md`（`## scaffold/defects.json` 节） |
| `scaffold/cases/README.md` | `references/api-scaffold-project.md`（`## scaffold/cases/README.md` 节） |
| `scaffold/cases/_template/stories.js` | `references/api-scaffold-project.md`（`## scaffold/cases/_template/stories.js` 节） |
| `scaffold/cases/_template/story.md` | `references/api-scaffold-project.md`（`## scaffold/cases/_template/story.md` 节） |
| `scaffold/docs/api-reference.template.md` | `references/api-scaffold-project.md`（`## scaffold/docs/api-reference.template.md` 节） |
| `scaffold/docs/db-reference.template.md` | `references/api-scaffold-project.md`（`## scaffold/docs/db-reference.template.md` 节） |

> 本技能不含可执行文件：脚手架各文件以 Markdown 形式随包，落地时按 `## 路径` 写回磁盘。

---

## 第二章 Web 功能测试

To test local web applications, write native Python Playwright scripts.

**Helper Scripts Available**:
- `references/web-with-server.md` - Manages server lifecycle (supports multiple servers)；按节还原为 `scripts/with_server.py` 后执行

**Always run scripts with `--help` first** to see usage. DO NOT read the source until you try running the script first and find that a customized solution is abslutely necessary. These scripts can be very large and thus pollute your context window. They exist to be called directly as black-box scripts rather than ingested into your context window.

### Decision Tree: Choosing Your Approach

```
User task → Is it static HTML?
    ├─ Yes → Read HTML file directly to identify selectors
    │         ├─ Success → Write Playwright script using selectors
    │         └─ Fails/Incomplete → Treat as dynamic (below)
    │
    └─ No (dynamic webapp) → Is the server already running?
        ├─ No → Run: python scripts/with_server.py --help
        │        Then use the helper + write simplified Playwright script
        │
        └─ Yes → Reconnaissance-then-action:
            1. Navigate and wait for networkidle
            2. Take screenshot or inspect DOM
            3. Identify selectors from rendered state
            4. Execute actions with discovered selectors
```

### Example: Using with_server.py

To start a server, run `--help` first, then use the helper:

**Single server:**
```bash
python scripts/with_server.py --server "npm run dev" --port 5173 -- python your_automation.py
```

**Multiple servers (e.g., backend + frontend):**
```bash
python scripts/with_server.py \
  --server "cd backend && python server.py" --port 3000 \
  --server "cd frontend && npm run dev" --port 5173 \
  -- python your_automation.py
```

To create an automation script, include only Playwright logic (servers are managed automatically):
```python
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True) # Always launch chromium in headless mode
    page = browser.new_page()
    page.goto('http://localhost:5173') # Server already running and ready
    page.wait_for_load_state('networkidle') # CRITICAL: Wait for JS to execute
    # ... your automation logic
    browser.close()
```

### Reconnaissance-Then-Action Pattern

1. **Inspect rendered DOM**:
   ```python
   page.screenshot(path='/tmp/inspect.png', full_page=True)
   content = page.content()
   page.locator('button').all()
   ```

2. **Identify selectors** from inspection results

3. **Execute actions** using discovered selectors

### Common Pitfall

❌ **Don't** inspect the DOM before waiting for `networkidle` on dynamic apps
✅ **Do** wait for `page.wait_for_load_state('networkidle')` before inspection

### Best Practices

- **Use bundled scripts as black boxes** - 先按 `references/web-with-server.md` / `references/web-examples.md` 把脚本落到 `scripts/`、`examples/`，再当作黑盒调用。 These scripts handle common, complex workflows reliably without cluttering the context window. Use `--help` to see usage, then invoke directly. 
- Use `sync_playwright()` for synchronous scripts
- Always close the browser when done
- Use descriptive selectors: `text=`, `role=`, CSS selectors, or IDs
- Add appropriate waits: `page.wait_for_selector()` or `page.wait_for_timeout()`

### Reference Files

- **examples/** - Examples showing common patterns:
  - `element_discovery.py` - Discovering buttons, links, and inputs on a page
  - `static_html_automation.py` - Using file:// URLs for local HTML
  - `console_logging.py` - Capturing console logs during automation

### 随附资产对照（分发通道只放行 Markdown）

| 原始路径 | 技能包内位置 |
|---|---|
| `scripts/with_server.py` | `references/web-with-server.md`（`## scripts/with_server.py` 节） |
| `examples/console_logging.py` | `references/web-examples.md`（`## examples/console_logging.py` 节） |
| `examples/element_discovery.py` | `references/web-examples.md`（`## examples/element_discovery.py` 节） |
| `examples/static_html_automation.py` | `references/web-examples.md`（`## examples/static_html_automation.py` 节） |
| `LICENSE.txt` | `references/web-license.md`（`## LICENSE.txt` 节） |

> 本技能原带 Python 脚本与示例，已转写为 Markdown；许可证全文见 `references/web-license.md`。

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
