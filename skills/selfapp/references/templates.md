# 项目模板：API 测试包（templates/api-testing）

> 本文件是技能包内可执行资产的 Markdown 转写 —— 分发通道只放行 `SKILL.md` 与 `references/*.md`。
> 落地方法：按各节标题里的路径原样写回磁盘，代码块内容与原文件一致。

## `templates/api-testing/README.md`

````markdown
# 接口测试工具包 (tools/api-testing)

> 无前端时由 AI 按 story 驱动: 登录 → 调接口 → 查库验证 → 造数(留库) → 报告。
> 由全局技能 **api-testing-toolkit** 的脚手架初始化; 方法论/约定详见该技能, 本 README 记录本项目特有事实与演进。

## 目录

```
tools/api-testing/
├── README.md            # 本文: 项目特有说明 + 演进记录
├── docs/                # 稳定参考(接口清单/调用知识/库参考)
├── cases/               # 全部测试链(唯一用例来源), _template 为模板
│   └── <YYYY-MM-DD-中文标题>/   # story.md + stories.js + report/(gitignore)
├── mcp-server/          # MCP server + story runner(node src/index.js / run-tests.js)
├── local/               # 凭据与会话缓存(gitignore, 每人自备)
└── defects.json         # 缺陷生命周期单源(open -> fixed -> verified/wontfix)
```

## 快速开始(新人)

```bash
cd tools/api-testing/mcp-server && npm install
cp ../env.example.json ../local/mcp-env.json    # 填真实凭据
npm run check                                    # 自检(token+db+health)
npm run test                                     # 日常回归(regression:true)
node src/run-tests.js --list                     # 列出全部测试链
```

## 在 MCP 客户端注册(任意客户端)

- 启动: `node tools/api-testing/mcp-server/src/index.js`(以项目根为工作目录)
- 环境: `MCP_ENV_FILE=tools/api-testing/local/mcp-env.json`

## 提交边界

入库: `cases/**/story.md + stories.js`、`docs/`、`defects.json`、mcp-server 源码、本 README。
不入库(local/.gitignore): `local/`(凭据)、`**/report/`(执行报告)、node_modules。

## 演进记录(第 5 步: 持续改进)

| 日期 | 优化点 | 结果 |
|---|---|---|
| (init) | 由 api-testing-toolkit 脚手架初始化 | — |
````

## `templates/api-testing/package.json`

```json
{
  "name": "@selfapp/api-testing",
  "version": "1.0.0",
  "description": "自动化 API 契约与全链路冒烟测试套件",
  "type": "module",
  "scripts": {
    "test": "node runner.mjs",
    "test:watch": "node runner.mjs --watch"
  },
  "dependencies": {
    "dotenv": "^16.4.7"
  }
}
```

## `templates/api-testing/runner.mjs`

```javascript
/**
 * @file runner.mjs
 * @author xudong.hua,gemini
 * @since 2026-08-24 17:35 星期一
 * @description 自动化 API 故事流与契约测试执行引擎
 */

import fs from 'node:fs';
import path from 'node:path';

const BASE_URL = process.env.API_BASE_URL || 'http://localhost:3000';

class ApiTestContext {
  constructor(baseUrl) {
    this.baseUrl = baseUrl;
    this.tokens = { accessToken: '', refreshToken: '' };
    this.headers = { 'Content-Type': 'application/json' };
    this.state = {};
  }

  setToken(token) {
    this.tokens.accessToken = token;
    this.headers['Authorization'] = `Bearer ${token}`;
  }

  setTenant(tenantId) {
    this.headers['X-Tenant-Id'] = String(tenantId);
    this.headers['X-Family-Id'] = String(tenantId);
  }

  async request(method, pathUrl, body = null, customHeaders = {}) {
    const url = `${this.baseUrl}${pathUrl}`;
    const headers = { ...this.headers, ...customHeaders };
    const opts = { method, headers };
    if (body) opts.body = JSON.stringify(body);

    const start = Date.now();
    const res = await fetch(url, opts);
    const durationMs = Date.now() - start;
    const text = await res.text();
    let data;
    try { data = JSON.parse(text); } catch { data = text; }

    return {
      status: res.status,
      ok: res.ok,
      data,
      durationMs,
      headers: res.headers
    };
  }

  get(url, headers) { return this.request('GET', url, null, headers); }
  post(url, body, headers) { return this.request('POST', url, body, headers); }
  put(url, body, headers) { return this.request('PUT', url, body, headers); }
  patch(url, body, headers) { return this.request('PATCH', url, body, headers); }
  delete(url, headers) { return this.request('DELETE', url, null, headers); }
}

async function runTestSuite(storiesFile) {
  console.log(`\n🚀 [API-TEST] 正在加载测试套件: ${storiesFile}`);
  const ctx = new ApiTestContext(BASE_URL);
  
  const stories = (await import(`file:///${path.resolve(storiesFile).replace(/\\/g, '/')}`)).stories;
  let passCount = 0;
  let failCount = 0;

  for (const story of stories) {
    console.log(`\n--- 🧪 故事用例: ${story.name} ---`);
    for (const step of story.steps) {
      try {
        await step(ctx);
        console.log(`  ✅ ${step.name || '步骤通过'}`);
        passCount++;
      } catch (err) {
        console.error(`  ❌ [失败] ${step.name || '步骤失败'}: ${err.message}`);
        failCount++;
        if (story.stopOnFail) break;
      }
    }
  }

  console.log(`\n📊 [测试报告] 总步骤: ${passCount + failCount} | 成功: ${passCount} | 失败: ${failCount}`);
  if (failCount > 0) process.exit(1);
}

const targetStories = process.argv[2] || './cases/stories.js';
if (fs.existsSync(targetStories)) {
  runTestSuite(targetStories);
} else {
  console.log(`未找到指定故事用例文件: ${targetStories}`);
}
```

## `templates/api-testing/stories.example.js`

```javascript
/**
 * @file stories.example.js
 * @author xudong.hua,gemini
 * @since 2026-08-24 17:35 星期一
 * @description 标准全链路 API 冒烟与状态机测试用例模板
 */

import assert from 'node:assert';

export const stories = [
  {
    name: '01. 用户认证与协议签署全流程',
    stopOnFail: true,
    steps: [
      async function 获取全局轻量心跳配置(ctx) {
        const res = await ctx.get('/api/app/config');
        assert.strictEqual(res.status, 200, '获取配置应返回 200');
        assert.ok(Array.isArray(res.data.agreements), '应包含协议列表');
        ctx.state.agreements = res.data.agreements;
      },
      async function 模拟用户微信登录(ctx) {
        const res = await ctx.post('/api/auth/wechat/login', { code: 'mock_code_test_01' });
        assert.strictEqual(res.status, 200, '登录应成功返回 200');
        assert.ok(res.data.tokens.accessToken, '应返回 Access Token');
        ctx.setToken(res.data.tokens.accessToken);
        ctx.state.user = res.data.user;
      },
      async function 提交用户协议签署日志(ctx) {
        const consents = ctx.state.agreements.map(a => ({ agreementId: a.id, version: a.version }));
        const res = await ctx.post('/api/agreements/consent', {
          consents,
          clientPlatform: 'weapp',
          clientVersion: '1.0.0'
        });
        assert.strictEqual(res.status, 200, '签署日志记录应返回 200');
        assert.strictEqual(res.data.ok, true, '签署状态应为 ok');
      }
    ]
  },
  {
    name: '02. 多租户防越权与数据隔离测试',
    stopOnFail: false,
    steps: [
      async function 尝试未带租户头访问资源_拦截400(ctx) {
        // 清空租户头
        delete ctx.headers['X-Tenant-Id'];
        delete ctx.headers['X-Family-Id'];
        const res = await ctx.get('/api/contacts');
        assert.strictEqual(res.status, 400, '未提供租户头应返回 400');
      },
      async function 尝试越权访问他人租户_拦截403(ctx) {
        ctx.setTenant(999999); // 构造不存在或未加入的非法租户 ID
        const res = await ctx.get('/api/contacts');
        assert.strictEqual(res.status, 403, '越权访问应返回 403 NOT_TENANT_MEMBER');
      }
    ]
  }
];
```

## `templates/api-testing/defects.json`

```json
{
  "$comment": "缺陷生命周期单源。状态机: open(已知缺陷, 报告标 known 不算回归红) -> fixed(待回归) -> verified(回归通过) / wontfix。origin: history=历史存量 | requirement=本次需求发现",
  "defects": []
}
```

## `templates/api-testing/cases/README.md`

````markdown
# 测试链总览 (cases/)

每个需求一条链: `cases/<YYYY-MM-DD>-<中文标题>/`(复制 `_template`), 内含:

- `story.md`: 场景表 + 测试数据约定(人读)
- `stories.js`: 可执行断言(机器跑), 报告写在本目录 `report/latest.md`

## 执行

```bash
cd tools/api-testing/mcp-server && node src/run-tests.js --case <标题片段>
node src/run-tests.js --module a,b --smoke   # 组合冒烟
npm run test                                  # regression:true 日常回归
```

## 现有链

| 目录 | 模块 id | 说明 | regression |
|---|---|---|---|
| _(待登记)_ | | | |
````

## `templates/api-testing/cases/_template/stories.js`

```javascript
/**
 * <需求标题> — story 模块模板
 * ctx 能力: ctx.api(method,path,{query,body}) / get/post/put/patch/del /
 *          ctx.sql(text,params 只读) / ctx.waitUntilApi(...) / ctx.assert(cond,msg,detail?) / ctx.eq / ctx.info
 * 断言基准以项目响应约定为准(Hono 系看 HTTP 状态码; codeField 项目看 bizOk)。
 */
export const module = {
    id: "xxx",              // 模块 id(--module 用)
    title: "需求标题",
    smoke: ["X-01"],        // 冒烟子集
    regression: false,      // true 才进日常回归(npm run test)
};

export const stories = [
    {
        id: "X-01",
        title: "示例: 健康检查可达",
        endpoints: ["GET /healthz"],
        tags: ["core"],
        async fn(ctx) {
            const r = await ctx.api("GET", "/healthz");
            ctx.assert(r.status === 200, "healthz 应返回 200", { status: r.status, body: r.body });
        },
    },
];
```

## `templates/api-testing/cases/_template/story.md`

```markdown
# <需求标题>

> 目录: `cases/<YYYY-MM-DD>-<需求标题中文>/`
> 执行: `cd tools/api-testing/mcp-server && node src/run-tests.js --case <需求标题>`
> 冒烟: 同上加 `--smoke`

## 需求背景

- 需求:
- 涉及模块/路由文件:
- 接口前缀:
- 相关文档: `docs/api-reference.md`、`docs/db-reference.md`

## Story

| ID | 场景 | 接口 |
|---|---|---|
| AUTH | 登录/会话 | (登录链, 见 env auth.steps) |
| X-01 | | |

## 测试数据约定

- 造数命名: `AT-<中文业务场景>`(如 `AT-XX功能-建单`)
- 可复用的现成数据(fixture/接口取数)先查再用, 不要每条用例新建一份
```

## `templates/api-testing/docs/api-reference.template.md`

```markdown
# 接口调用知识 (api-reference)

> 只放"怎么调"的稳定知识: 鉴权 / headers / 响应规范 / 枚举 / 参数来源 / 坑。缺陷结论放 defects.json。

## 鉴权

- 登录链(env auth.steps):
- token 传递:

## 请求头约定

| 头 | 取值 | 说明 |
|---|---|---|

## 响应规范

- 成功判定:
- 错误体结构 / 常见错误码:

## 分页 / 枚举 / 参数来源

## 已知坑
```

## `templates/api-testing/docs/db-reference.template.md`

````markdown
# 数据库参考 (db-reference)

> 连接凭据只在 local/mcp-env.json, 此处不重复。只放表分组、数据约定、查询模板。

## 连接概要

- driver/host/port/database: 见 env(掩码)
- ORM/迁移方式:

## 表分组

| 分组 | 表 | 说明 |
|---|---|---|
| 用户/租户 | | |
| 核心业务 | | |

## 数据约定

- 多租户字段/逻辑删除/时间格式:

## 常用查询模板

```sql
-- 查重(造数前)
select * from <table> where name like 'AT-%' order by id desc limit 5;
```
````

## `templates/api-testing/mcp-server/env.example.json`

```json
{
  "$comment": "复制本文件到 tools/api-testing/local/mcp-env.json 并填写真实值(local/ 已 gitignore)。可用环境变量 MCP_ENV_FILE 指定其他路径。auth.mode: static=直接用 api.token | chain=多步登录链。step 字段: method/path/query/body/save(响应点路径->变量)/optional(失败跳过)/once(变量已有值则跳过, 配合 local 会话缓存实现幂等建租户)。headers 支持 {{var}} 模板。",
  "api": {
    "baseUrl": "http://127.0.0.1:8080",
    "timeoutMs": 15000,
    "healthPath": "/healthz",
    "token": "",
    "codeField": "",
    "okValue": 0
  },
  "auth": {
    "mode": "chain",
    "steps": [
      { "method": "POST", "path": "/api/auth/login", "body": { "username": "", "password": "" }, "save": { "accessToken": "tokens.accessToken" } }
    ],
    "headers": {
      "Authorization": "Bearer {{accessToken}}"
    }
  },
  "headers": {},
  "db": {
    "driver": "postgres",
    "host": "127.0.0.1",
    "port": 5432,
    "user": "",
    "password": "",
    "database": "",
    "connectTimeoutMs": 5000,
    "connectionLimit": 5
  },
  "dbSafety": {
    "allowSafeDdl": false,
    "writeTables": []
  },
  "fixtures": {},
  "log": {
    "dir": "",
    "pattern": "*.log"
  }
}
```

## `templates/api-testing/mcp-server/package.json`

```json
{
  "name": "api-testing-mcp-server",
  "private": true,
  "type": "module",
  "version": "1.0.0",
  "engines": { "node": ">=20" },
  "scripts": {
    "start": "node src/index.js",
    "check": "node src/index.js --self-check",
    "test": "node src/run-tests.js",
    "test:smoke": "node src/run-tests.js --all --smoke",
    "test:all": "node src/run-tests.js --all"
  },
  "dependencies": {
    "@modelcontextprotocol/sdk": "^1.12.1",
    "mysql2": "^3.11.0",
    "pg": "^8.14.0"
  }
}
```

## `templates/api-testing/mcp-server/src/index.js`

```javascript
#!/usr/bin/env node
/**
 * 通用接口测试 MCP server (stdio)
 * 工具: status/health/login/api/sql/sql_exec/schema/sample/wait_until/fixture/tail_log
 * 自检: node src/index.js --self-check
 */
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { CallToolRequestSchema, ListToolsRequestSchema } from "@modelcontextprotocol/sdk/types.js";

import { loadEnvConfig, maskConfig, renderTemplate, getPath } from "./lib/config.js";
import * as db from "./lib/db.js";
import { createClient } from "./lib/http.js";
import { login, ensureLogin, clearCache } from "./lib/auth.js";
import { tailLog } from "./lib/log.js";

const envCfg = loadEnvConfig();
const session = { vars: {}, authHeaders: {}, mode: null, loggedInAt: null };

function text(result) {
    return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
}

async function healthProbe() {
    const out = {};
    const path = envCfg.api?.healthPath;
    if (!path) {
        out.http = { skipped: true };
    } else {
        try {
            const client = createClient(envCfg, null);
            const r = await client.get(path);
            out.http = { ok: r.status < 400, status: r.status, body: typeof r.body === "object" ? r.body : String(r.body).slice(0, 200) };
        } catch (e) {
            out.http = { ok: false, error: e.message, code: e.code || "" };
        }
    }
    if (!envCfg.db?.driver) {
        out.db = { skipped: true };
    } else {
        try {
            await db.ping(envCfg);
            out.db = { ok: true, driver: envCfg.db.driver, database: envCfg.db.database };
        } catch (e) {
            out.db = { ok: false, error: e.message };
        }
    }
    out.envBlocked = (out.http && out.http.ok === false) || (out.db && out.db.ok === false);
    return out;
}

const TOOLS = [
    {
        name: "status",
        description: "查看当前配置摘要(token/密码已掩码)与会话状态。排查配置问题先用它。",
        inputSchema: { type: "object", properties: {} },
        handler: async () => ({
            config: maskConfig(envCfg),
            session: { mode: session.mode, loggedInAt: session.loggedInAt, vars: session.vars },
        }),
    },
    {
        name: "health",
        description: "环境探针: HTTP 健康端点 + 数据库连通性。业务 FAIL 前先跑, 用于区分环境阻塞与代码缺陷。",
        inputSchema: { type: "object", properties: {} },
        handler: async () => healthProbe(),
    },
    {
        name: "login",
        description: "执行鉴权(static 校验 / chain 登录链)并刷新会话。fresh=true 清空本地缓存变量重跑全链(如重建家庭/租户)。",
        inputSchema: {
            type: "object",
            properties: { fresh: { type: "boolean", description: "清空缓存变量后重新执行完整登录链" } },
        },
        handler: async (a) => login(envCfg, session, { fresh: !!a.fresh }),
    },
    {
        name: "api",
        description: "带鉴权调用接口。返回 {status, ok(HTTP), bizOk(业务成功判定), body}。",
        inputSchema: {
            type: "object",
            required: ["method", "path"],
            properties: {
                method: { type: "string", enum: ["GET", "POST", "PUT", "PATCH", "DELETE"] },
                path: { type: "string" },
                query: { type: "object", additionalProperties: true },
                body: {},
                headers: { type: "object", additionalProperties: { type: "string" } },
            },
        },
        handler: async (a) => {
            await ensureLogin(envCfg, session);
            return await createClient(envCfg, session).request(a.method, a.path, { query: a.query, body: a.body, headers: a.headers });
        },
    },
    {
        name: "sql",
        description: "只读查询(SELECT/WITH/SHOW/EXPLAIN)。写库用 sql_exec。用于断言验证与造数查重。",
        inputSchema: {
            type: "object",
            required: ["query"],
            properties: { query: { type: "string" }, params: { type: "array" } },
        },
        handler: async (a) => ({ rows: await db.sqlQuery(envCfg, a.query, a.params || []) }),
    },
    {
        name: "sql_exec",
        description: `受控写库: 仅 INSERT/UPDATE 且表必须在 writeTables 白名单; UPDATE 必须带 WHERE; DELETE/DROP/TRUNCATE 一律禁止${envCfg.dbSafety?.allowSafeDdl ? "; 已放行安全 DDL(ALTER TABLE/CREATE)" : ""}。测试数据默认不删。`,
        inputSchema: { type: "object", required: ["sql"], properties: { sql: { type: "string" } } },
        handler: async (a) => db.sqlExec(envCfg, a.sql),
    },
    {
        name: "schema",
        description: "查询表结构(列/类型/可空/默认值)。",
        inputSchema: { type: "object", required: ["table"], properties: { table: { type: "string" } } },
        handler: async (a) => ({ columns: await db.tableSchema(envCfg, a.table) }),
    },
    {
        name: "sample",
        description: "取表样例行(默认 3 行), 用于构造真实入参。",
        inputSchema: {
            type: "object",
            required: ["table"],
            properties: { table: { type: "string" }, limit: { type: "number", maximum: 50 } },
        },
        handler: async (a) => ({ rows: await db.sampleRows(envCfg, a.table, a.limit) }),
    },
    {
        name: "wait_until",
        description: "轮询直到条件满足(异步状态/自动履约等)。kind=api 时 until 基于 ctx{status,body}; kind=sql 时基于 ctx{rows,value=rows[0]}。禁止手动 sleep 循环。",
        inputSchema: {
            type: "object",
            required: ["kind", "until"],
            properties: {
                kind: { type: "string", enum: ["api", "sql"] },
                method: { type: "string" }, path: { type: "string" },
                query: { type: "object", additionalProperties: true }, body: {},
                query_sql: { type: "string" },
                until: { type: "string", description: 'JS 表达式, 如 "body.state === 1" 或 "Number(rows[0].count) > 0"' },
                timeoutMs: { type: "number" }, intervalMs: { type: "number" },
            },
        },
        handler: async (a) => {
            const timeoutMs = Math.min(a.timeoutMs || 30000, 120000);
            const intervalMs = Math.max(a.intervalMs || 1000, 250);
            const start = Date.now();
            let last = null;
            for (;;) {
                try {
                    last = a.kind === "api"
                        ? await (await ensureLogin(envCfg, session), createClient(envCfg, session)).request(a.method || "GET", a.path, { query: a.query, body: a.body })
                        : { rows: await db.sqlQuery(envCfg, a.query_sql) };
                    last.value = last.rows ? last.rows[0] : undefined;
                    const fnCtx = last;
                    const ok = new Function("ctx", `with(ctx) { return Boolean((${a.until})); }`)(fnCtx);
                    if (ok) return { satisfied: true, elapsedMs: Date.now() - start, snapshot: sanitize(last) };
                } catch { /* 轮询期间错误视为未满足 */ }
                if (Date.now() - start > timeoutMs) throw new Error(`wait_until 超时(${timeoutMs}ms): 最后快照 ${JSON.stringify(sanitize(last)).slice(0, 600)}`);
                await new Promise((r) => setTimeout(r, intervalMs));
            }
            function sanitize(x) { return x && x.rows ? { rows: x.rows.slice(0, 5), value: x.value } : x; }
        },
    },
    {
        name: "fixture",
        description: "按 env 配置的 fixtures 取现成业务数据(走接口, 不查库)。未命名时列出全部可用 fixture。",
        inputSchema: { type: "object", properties: { name: { type: "string" } } },
        handler: async (a) => {
            const fx = envCfg.fixtures || {};
            if (!a.name) return { available: Object.keys(fx) };
            const conf = fx[a.name];
            if (!conf) throw new Error(`未知 fixture "${a.name}", 可用: ${Object.keys(fx).join(", ") || "(无)"}`);
            await ensureLogin(envCfg, session);
            const client = createClient(envCfg, session);
            const r = await client.request(conf.method || "GET", renderTemplate(conf.path, session.vars), {
                query: conf.query ? renderTemplate(conf.query, session.vars) : undefined,
            });
            return { status: r.status, bizOk: r.bizOk, data: conf.pick ? getPath(r.body, conf.pick) : r.body };
        },
    },
    {
        name: "tail_log",
        description: "尾读服务端日志(需配置 log.dir); 可 grep 过滤。500 根因通常只在服务端日志。",
        inputSchema: {
            type: "object",
            properties: { lines: { type: "number" }, grep: { type: "string" } },
        },
        handler: async (a) => tailLog(envCfg, a),
    },
];

const server = new Server({ name: "api-testing-mcp", version: "1.0.0" }, { capabilities: { tools: {} } });

server.setRequestHandler(ListToolsRequestSchema, async () => ({
    tools: TOOLS.map(({ name, description, inputSchema }) => ({ name, description, inputSchema })),
}));

server.setRequestHandler(CallToolRequestSchema, async (req) => {
    const { name, arguments: args } = req.params;
    const tool = TOOLS.find((t) => t.name === name);
    if (!tool) throw new Error(`未知工具: ${name}`);
    try {
        const result = await tool.handler(args || {});
        return text(result === undefined ? {} : result);
    } catch (e) {
        const payload = { error: e.message, code: e.code || (String(e.message).includes("ENV_BLOCKED") ? "ENV_BLOCKED" : "") };
        if (process.env.API_TEST_DEBUG) payload.stack = e.stack;
        return text(payload);
    }
});

async function selfCheck() {
    console.log(`[check] 配置: ${JSON.stringify(maskConfig(envCfg))}`);
    const h = await healthProbe();
    console.log(`[check] http: ${JSON.stringify(h.http)}`);
    console.log(`[check] db:   ${JSON.stringify(h.db)}`);
    if (h.envBlocked) {
        console.log("[check] 结果: ENV_BLOCKED (先启动服务/数据库)");
        process.exitCode = 2;
        return;
    }
    try {
        const r = await login(envCfg, session);
        const shown = Object.fromEntries(Object.entries(r.vars).map(([k, v]) => [k, k.toLowerCase().includes("token") ? `${String(v).slice(0, 6)}****` : v]));
        console.log(`[check] 鉴权: OK (${session.mode}) vars=${JSON.stringify(shown)}${r.warnings.length ? ` warnings=${JSON.stringify(r.warnings)}` : ""}`);
        console.log("[check] 结果: PASS");
    } catch (e) {
        console.log(`[check] 鉴权: FAIL - ${e.message}`);
        process.exitCode = 1;
    }
}

if (process.argv.includes("--self-check")) {
    await selfCheck();
    await db.closeAll();
} else {
    await server.connect(new StdioServerTransport());
}
```

## `templates/api-testing/mcp-server/src/run-tests.js`

```javascript
#!/usr/bin/env node
/**
 * story runner CLI
 * 用法:
 *   node src/run-tests.js --list                     列出全部测试链
 *   node src/run-tests.js                            跑 regression:true 模块
 *   node src/run-tests.js --all                      全部链(含非回归)
 *   node src/run-tests.js --module a,b [--smoke]     按模块(可组合), --smoke 只跑各模块 smoke 子集
 *   node src/run-tests.js --case <中文标题|目录名片段>  单条需求链
 *   node src/run-tests.js --story X-01,X-02          定点
 *   --skip-health                                    跳过环境探针
 * 退出码: 0=全过 1=有 FAIL 2=环境阻塞
 */
import { readdirSync, mkdirSync, writeFileSync, existsSync, readFileSync, unlinkSync } from "node:fs";
import { join, resolve, dirname } from "node:path";
import { pathToFileURL, fileURLToPath } from "node:url";
import { loadEnvConfig } from "./lib/config.js";
import { createClient } from "./lib/http.js";
import { login } from "./lib/auth.js";
import { createContext } from "./lib/harness.js";
import { renderReportMd } from "./lib/report.js";
import { ping as dbPing, closeAll as dbCloseAll } from "./lib/db.js";

const args = process.argv.slice(2);
const has = (f) => args.includes(f);
const val = (f) => { const i = args.indexOf(f); return i >= 0 ? args[i + 1] : undefined; };

const SERVER_DIR = dirname(fileURLToPath(import.meta.url));            // <mcp-server>/src
const ROOT = resolve(SERVER_DIR, "..", "..");                           // tools/api-testing/
const CASES_DIR = join(ROOT, "cases");

function parseArgs() {
    const filters = {
        all: has("--all"),
        modules: (val("--module") || "").split(",").map((s) => s.trim()).filter(Boolean),
        caseName: val("--case") || "",
        storyIds: new Set((val("--story") || "").split(",").map((s) => s.trim()).filter(Boolean)),
        smoke: has("--smoke"),
        list: has("--list"),
        skipHealth: has("--skip-health"),
    };
    return filters;
}

async function discoverCases() {
    if (!existsSync(CASES_DIR)) throw new Error(`cases 目录不存在: ${CASES_DIR}`);
    const dirs = readdirSync(CASES_DIR, { withFileTypes: true })
        .filter((e) => e.isDirectory() && !e.name.startsWith("_") && !e.name.startsWith("."))
        .map((e) => e.name)
        .sort();
    const chains = [];
    for (const name of dirs) {
        const storiesFile = join(CASES_DIR, name, "stories.js");
        if (!existsSync(storiesFile)) continue;
        const mod = await import(pathToFileURL(storiesFile).href);
        if (!mod.module?.id || !Array.isArray(mod.stories)) {
            console.warn(`[warn] ${name}/stories.js 缺少 module/stories 导出, 已跳过`);
            continue;
        }
        chains.push({ dirName: name, mod });
    }
    return chains;
}

function selectChains(chains, f) {
    if (f.caseName) {
        const hit = chains.filter((c) => c.dirName.includes(f.caseName) || c.mod.module.title?.includes(f.caseName));
        if (!hit.length) throw new Error(`未找到匹配 "--case ${f.caseName}" 的测试链 (可用: ${chains.map((c) => c.dirName).join(", ")})`);
        return hit;
    }
    if (f.modules.length) return chains.filter((c) => f.modules.includes(c.mod.module.id));
    if (!f.all) return chains.filter((c) => c.mod.module.regression === true);
    return chains;
}

async function healthGate(envCfg) {
    const problems = [];
    const client = createClient(envCfg, null);
    try {
        const r = await client.get(envCfg.api?.healthPath || "/healthz");
        if (r.status >= 400) problems.push(`health 端点 HTTP ${r.status}`);
    } catch (e) {
        problems.push(`服务不可达(${envCfg.api?.baseUrl}): ${e.message}`);
    }
    if (envCfg.db?.driver) {
        try { await dbPing(envCfg); } catch (e) { problems.push(`数据库不可达: ${e.message}`); }
    }
    return problems;
}

function loadDefects() {
    const file = join(ROOT, "defects.json");
    if (!existsSync(file)) return [];
    try {
        const data = JSON.parse(readFileSync(file, "utf-8"));
        return Array.isArray(data.defects) ? data.defects : [];
    } catch { return []; }
}

function writeReport(chain, reportData) {
    const reportDir = join(CASES_DIR, chain.dirName, "report");
    mkdirSync(reportDir, { recursive: true });
    const ts = reportData.startedAt.replace(/[:.]/g, "-").slice(0, 19);
    writeFileSync(join(reportDir, "latest.md"), renderReportMd(reportData));
    writeFileSync(join(reportDir, "latest.json"), JSON.stringify(reportData.results, null, 2));
    writeFileSync(join(reportDir, `${ts}.json`), JSON.stringify(reportData.results, null, 2));
    // 只保留最近 5 份带时间戳历史
    const hist = readdirSync(reportDir).filter((f) => /^\d{4}-\d{2}-\d{2}T.*\.json$/.test(f)).sort().reverse();
    for (const f of hist.slice(5)) {
        try { unlinkSync(join(reportDir, f)); } catch { /* ignore */ }
    }
    return join(reportDir, "latest.md");
}

async function runChain(envCfg, chain, f, defects) {
    const { module: m } = chain.mod;
    let stories = [...chain.mod.stories];
    if (f.storyIds.size) stories = stories.filter((s) => f.storyIds.has(s.id));
    else if (f.smoke) {
        const ids = new Set(m.smoke || []);
        stories = stories.filter((s) => ids.has(s.id));
    }

    console.log(`\n=== [${m.id}] ${m.title} (${chain.dirName}) — ${stories.length} stories ===`);
    if (!stories.length) { console.log("(无匹配 story, 跳过)"); return { results: [], envBlocked: false }; }

    const session = { vars: {}, authHeaders: {}, mode: null, loggedInAt: null };
    let envBlocked = false;
    try {
        const r = await login(envCfg, session);
        if (r.warnings.length) console.log(`  (登录链警告: ${r.warnings.join("; ")})`);
        console.log(`  登录 OK (${session.mode}), vars=[${Object.keys(session.vars).join(", ")}]`);
    } catch (e) {
        console.error(`  ENV_BLOCKED: 鉴权失败 - ${e.message}`);
        return {
            results: stories.map((s) => ({ storyId: s.id, pass: false, durationMs: 0, error: `ENV_BLOCKED: ${e.message}` })),
            envBlocked: true,
        };
    }

    const openDefectStoryIds = new Set(defects.filter((d) => d.status === "open").map((d) => d.story));
    const results = [];
    for (const story of stories) {
        const ctx = createContext({ envCfg, session });
        const t0 = Date.now();
        const entry = { storyId: story.id, title: story.title || "", pass: false, durationMs: 0 };
        let timeoutTimer;
        try {
            await Promise.race([
                Promise.resolve(story.fn(ctx)),
                new Promise((_, rej) => {
                    timeoutTimer = setTimeout(() => rej(new Error(`story 超时(${process.env.STORY_TIMEOUT_MS || 120000}ms)`)), Number(process.env.STORY_TIMEOUT_MS) || 120000);
                }),
            ]);
            entry.pass = true;
            console.log(`  PASS ${story.id}${story.title ? ` - ${story.title}` : ""} (${Date.now() - t0}ms)`);
        } catch (e) {
            entry.pass = false;
            entry.known = openDefectStoryIds.has(story.id);
            entry.error = e.message;
            if (e.detail) entry.detail = e.detail;
            console.log(`  ${entry.known ? "FAIL(known)" : "FAIL"} ${story.id} - ${e.message} (${Date.now() - t0}ms)`);
            if (ctx._infos.length) entry.infos = ctx._infos;
        } finally {
            clearTimeout(timeoutTimer);
        }
        entry.durationMs = Date.now() - t0;
        if (!entry.pass && String(entry.error || "").includes("ENV_BLOCKED")) envBlocked = true;
        results.push(entry);
    }
    return { results, envBlocked };
}

async function main() {
    const envCfg = loadEnvConfig();
    const f = parseArgs();
    const chains = await discoverCases();

    if (f.list) {
        console.log("可用测试链:");
        for (const c of chains) {
            const { id, title, regression, smoke } = c.mod.module;
            console.log(`  [${id}]${regression ? " (regression)" : ""} ${title} — ${c.dirName} — stories: ${c.mod.stories.map((s) => s.id).join(", ")} | smoke: ${(smoke || []).join(",") || "-"}`);
        }
        return;
    }

    const selected = selectChains(chains, f);
    if (!selected.length) {
        console.log("没有选中的测试链(--all / --module / --case / 默认 regression:true)");
        return;
    }
    if (!f.skipHealth) {
        const problems = await healthGate(envCfg);
        if (problems.length) {
            console.error(`ENV_BLOCKED: 环境自检未通过:\n  - ${problems.join("\n  - ")}\n(先启动服务/数据库; 调试可用 --skip-health)`);
            process.exitCode = 2;
            return;
        }
    }

    const defects = loadDefects();
    const startedAt = new Date();
    const allResults = [];
    let anyEnvBlocked = false;
    for (const chain of selected) {
        const { results, envBlocked } = await runChain(envCfg, chain, f, defects);
        allResults.push(...results);
        anyEnvBlocked = anyEnvBlocked || envBlocked;
        if (results.length) {
            const mdPath = writeReport(chain, {
                title: `${chain.mod.module.title}`,
                startedAt: startedAt.toISOString(),
                durationMs: results.reduce((a, b) => a + b.durationMs, 0),
                envBlocked, results,
            });
            console.log(`  报告: ${mdPath}`);
        }
    }

    const fail = allResults.filter((r) => !r.pass && !r.known).length;
    console.log(`\n汇总: 共 ${allResults.length}, 通过 ${allResults.filter((r) => r.pass).length}, 失败 ${fail}(已知缺陷另计 ${allResults.filter((r) => !r.pass && r.known).length})`);
    await dbCloseAll();
    process.exitCode = fail > 0 ? 1 : anyEnvBlocked ? 2 : 0;
}

main().catch(async (e) => {
    console.error(e.stack || e.message);
    await dbCloseAll().catch(() => {});
    process.exitCode = 1;
});
```

## `templates/api-testing/mcp-server/src/lib/auth.js`

```javascript
import { existsSync, readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { serverDir, getPath, renderTemplate } from "./config.js";
import { createClient } from "./http.js";

function cacheFile() {
    return resolve(serverDir(), "..", "local", "session-cache.json");
}

export function createSession() {
    return { vars: {}, authHeaders: {}, mode: null, loggedInAt: null };
}

/** 从 local/session-cache.json 预载变量(跨会话幂等, 如 familyId) */
export function preloadCache(session) {
    const f = cacheFile();
    if (!existsSync(f)) return {};
    try {
        const cached = JSON.parse(readFileSync(f, "utf-8"));
        Object.assign(session.vars, cached.vars || {});
        return cached.vars || {};
    } catch {
        return {};
    }
}

export function saveCache(session) {
    try {
        const f = cacheFile();
        mkdirSync(dirname(f), { recursive: true });
        writeFileSync(f, JSON.stringify({ vars: session.vars, savedAt: new Date().toISOString() }, null, 2));
    } catch { /* 缓存失败不阻塞 */ }
}

export function clearCache() {
    const f = cacheFile();
    if (existsSync(f)) { try { writeFileSync(f, "{}"); } catch { /* ignore */ } }
}

/**
 * 执行鉴权:
 * - static 模式: vars.token = api.token
 * - chain 模式: 逐步执行 steps, save 点路径取值进 vars; 支持 {{var}} 模板/optional/once
 * 成功后按 cfg.auth.headers 模板解析出会话鉴权头。
 */
export async function login(envCfg, session, { fresh = false } = {}) {
    session.mode = envCfg.auth?.mode || "static";
    if (fresh) {
        for (const k of Object.keys(session.vars)) delete session.vars[k];
        clearCache();
    }
    preloadCache(session);

    if (session.mode === "static") {
        const token = envCfg.api?.token;
        if (!token) throw new Error("static 模式需要配置 api.token");
        session.vars.accessToken = token;
    } else {
        // 链内客户端: 宽松渲染鉴权头(后续步骤可用前序步骤产出的 token/familyId)
        const client = createClient(envCfg, { vars: session.vars, authHeaders: envCfg.auth?.headers || {}, lenientAuth: true });
        const warnings = [];
        for (const [i, step] of (envCfg.auth?.steps || []).entries()) {
            const label = step.label || `#${i + 1} ${step.method} ${step.path}`;
            // once: 检查"变量名"是否已有值(缓存幂等), 而非响应点路径
            if (step.once && Object.keys(step.save || {}).every((varName) => session.vars[varName] !== undefined)) {
                continue;
            }
            try {
                const body = step.body ? renderTemplate(step.body, session.vars) : undefined;
                const query = step.query ? renderTemplate(step.query, session.vars) : undefined;
                const r = await client.request(step.method, renderTemplate(step.path, session.vars), { body, query });
                if (!r.bizOk) throw new Error(`HTTP ${r.status} / ${JSON.stringify(r.body).slice(0, 300)}`);
                for (const [varName, dotPath] of Object.entries(step.save || {})) {
                    const v = getPath(r.body, dotPath);
                    if (v !== undefined) session.vars[varName] = v;
                }
            } catch (e) {
                if (step.optional) { warnings.push(`${label}: ${e.message}`); continue; }
                throw new Error(`登录链步骤失败 ${label}: ${e.message}${warnings.length ? ` | 前序警告: ${warnings.join("; ")}` : ""}`);
            }
        }
        session.warnings = warnings;
    }

    session.authHeaders = envCfg.auth?.headers || {};
    // 立即校验模板可渲染(缺变量尽早报错)
    resolvedOrThrow(session);
    session.loggedInAt = new Date().toISOString();
    saveCache(session);
    return { vars: { ...session.vars }, warnings: session.warnings || [] };
}

function resolvedOrThrow(session) {
    for (const [k, v] of Object.entries(session.authHeaders)) {
        try { renderTemplate(v, session.vars); } catch (e) {
            throw new Error(`鉴权头 ${k} 渲染失败: ${e.message}${session.warnings?.length ? ` | 登录链警告: ${session.warnings.join("; ")}` : ""}`);
        }
    }
}

export async function ensureLogin(envCfg, session) {
    if (!session.loggedInAt) await login(envCfg, session);
    return session;
}
```

## `templates/api-testing/mcp-server/src/lib/config.js`

```javascript
import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

// 本文件位于 <mcp-server>/src/lib/, SERVER_DIR 指向 <mcp-server> 根目录
export const SERVER_DIR = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");

export function serverDir() {
    return SERVER_DIR;
}

export function defaultEnvFile() {
    return process.env.MCP_ENV_FILE
        ? resolve(process.cwd(), process.env.MCP_ENV_FILE)
        : resolve(SERVER_DIR, "..", "local", "mcp-env.json");
}

export function loadEnvConfig(envFile = defaultEnvFile()) {
    if (!existsSync(envFile)) {
        throw new Error(`配置不存在: ${envFile} (参考 mcp-server/env.example.json, 复制到 ../local/mcp-env.json 并填写)`);
    }
    return JSON.parse(readFileSync(envFile, "utf-8"));
}

export function maskToken(token) {
    const s = String(token || "");
    if (s.length <= 10) return s ? "***" : "(空)";
    return `${s.slice(0, 6)}****${s.slice(-4)}`;
}

/** 深拷贝并掩码敏感字段 */
export function maskConfig(cfg) {
    const clone = JSON.parse(JSON.stringify(cfg));
    if (clone.api?.token) clone.api.token = maskToken(clone.api.token);
    if (clone.auth?.mode === "chain") {
        delete clone.auth?.steps;
        clone.auth.steps = `(${cfg.auth?.steps?.length || 0} steps)`;
    }
    if (clone.db?.password) clone.db.password = "***";
    return clone;
}

/** 点路径取值: "a.b[0].c" */
export function getPath(obj, dotPath) {
    const parts = String(dotPath).split(".").flatMap((p) => {
        const m = p.match(/^(\w+)\[(\d+)\]$/);
        return m ? [m[1], Number(m[2])] : [p];
    });
    let cur = obj;
    for (const p of parts) {
        if (cur == null) return undefined;
        cur = cur[p];
    }
    return cur;
}

/** "{{var}}" 模板渲染 */
export function renderTemplate(value, vars) {
    if (typeof value === "string") {
        const filled = value.replace(/\{\{(\w+)\}\}/g, (_, k) => {
            const v = vars[k];
            if (v === undefined) throw new Error(`模板变量未定义: {{${k}}} (可用: ${Object.keys(vars).join(", ") || "无"})`);
            return String(v);
        });
        // 纯单变量替换保持原类型(数字 id 等)
        const pure = value.match(/^\{\{(\w+)\}\}$/);
        if (pure) {
            const v = vars[pure[1]];
            if (v !== undefined) return v;
        }
        return filled;
    }
    if (Array.isArray(value)) return value.map((v) => renderTemplate(v, vars));
    if (value && typeof value === "object") {
        const out = {};
        for (const [k, v] of Object.entries(value)) out[k] = renderTemplate(v, vars);
        return out;
    }
    return value;
}
```

## `templates/api-testing/mcp-server/src/lib/db.js`

```javascript
import mysql from "mysql2/promise";
import pg from "pg";

const pools = new Map(); // driver -> pool

function cfgOf(envCfg) {
    const db = envCfg.db || {};
    if (!db.driver) throw new Error("配置缺少 db.driver (postgres | mysql)");
    return db;
}

function ident(name) {
    if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(String(name))) throw new Error(`非法表名/列名: ${name}`);
    return name;
}

async function getPool(envCfg) {
    const db = cfgOf(envCfg);
    let pool = pools.get(db.driver);
    if (pool) return pool;
    if (db.driver === "postgres") {
        pool = new pg.Pool({
            host: db.host, port: db.port, user: db.user, password: db.password, database: db.database,
            connectionTimeoutMillis: db.connectTimeoutMs || 5000, max: db.connectionLimit || 5,
        });
    } else if (db.driver === "mysql") {
        pool = mysql.createPool({
            host: db.host, port: db.port, user: db.user, password: db.password, database: db.database,
            connectTimeout: db.connectTimeoutMs || 5000, connectionLimit: db.connectionLimit || 5,
        });
    } else {
        throw new Error(`不支持的 db.driver: ${db.driver} (仅 postgres | mysql)`);
    }
    pools.set(db.driver, pool);
    return pool;
}

/** 原生查询(内部用), 返回行数组 */
async function rawQuery(envCfg, text, params = []) {
    const p = await getPool(envCfg);
    const driver = cfgOf(envCfg).driver;
    if (driver === "postgres") return (await p.query(text, params)).rows;
    const [rows] = await p.query(text, params);
    return rows;
}

const READ_ONLY_RE = /^(select|with|show|explain|desc|describe)\b/i;

function stripComments(sql) {
    return String(sql).replace(/--[^\n]*\n?/g, "\n").replace(/\/\*[\s\S]*?\*\//g, " ");
}

/** 只读查询(sql 工具与 story ctx 用), 返回行数组 */
export async function sqlQuery(envCfg, text, params = []) {
    const s = stripComments(text).trim();
    if (!READ_ONLY_RE.test(s)) throw new Error("sql 只读, 仅允许 SELECT/WITH/SHOW/EXPLAIN; 写库走 sql_exec 且受白名单限制");
    return rawQuery(envCfg, s, params);
}

function extractTable(sql, re) {
    const m = sql.match(re);
    return m ? m[1].replace(/[`"']/g, "").toLowerCase() : null;
}

/** 受控写库: 仅 INSERT/UPDATE(表须在白名单; UPDATE 必须带 WHERE); DELETE/DROP/TRUNCATE 一律禁止 */
export async function sqlExec(envCfg, text) {
    const s = stripComments(text).trim().replace(/;\s*$/, "");
    if (/;/.test(s)) throw new Error("仅允许单条语句");
    const whitelist = (envCfg.dbSafety?.writeTables || []).map((t) => t.toLowerCase());
    const allowDdl = !!envCfg.dbSafety?.allowSafeDdl;

    if (READ_ONLY_RE.test(s)) throw new Error("查询请用 sql 工具");
    if (/\b(delete|drop|truncate)\b/i.test(s)) throw new Error("DELETE/DROP/TRUNCATE 一律禁止");

    const isDml = /^(insert|update)\b/i.test(s);
    const isSafeDdl = allowDdl && /^(alter\s+table|create\s+(table|unique\s+)?index)\b/i.test(s);
    if (!isDml && !isSafeDdl) {
        throw new Error("sql_exec 仅允许 INSERT/UPDATE" + (allowDdl ? " 与安全 DDL(ALTER TABLE / CREATE)" : ""));
    }
    if (!whitelist.length) throw new Error("dbSafety.writeTables 为空, 已禁止写库");

    const table = isDml
        ? extractTable(s, /^insert\s+into\s+[`"']?(\w+)/i) || extractTable(s, /^update\s+[`"']?(\w+)/i)
        : extractTable(s, /^(?:alter\s+table|create\s+(?:unique\s+)?index\s+\S+\s+on)\s+[`"']?(\w+)/i);
    if (!table) throw new Error("无法解析目标表名");
    if (!whitelist.includes(table)) throw new Error(`表 ${table} 不在写白名单 (${whitelist.join(",")}), 拒绝执行`);
    if (/^update\b/i.test(s) && !/\bwhere\b/i.test(s)) throw new Error("UPDATE 必须带 WHERE 条件");

    const p = await getPool(envCfg);
    const driver = cfgOf(envCfg).driver;
    if (driver === "postgres") {
        const res = await p.query(s);
        return { affected: res.rowCount ?? 0 };
    }
    const [res] = await p.query(s);
    return { affected: res.affectedRows ?? 0 };
}

export async function tableSchema(envCfg, table) {
    ident(table);
    const driver = cfgOf(envCfg).driver;
    if (driver === "postgres") {
        return rawQuery(envCfg, `select column_name, data_type, is_nullable, column_default
            from information_schema.columns
            where table_schema = current_schema() and table_name = $1 order by ordinal_position`, [table]);
    }
    return rawQuery(envCfg, `select column_name, data_type, is_nullable, column_default
        from information_schema.columns where table_schema = database() and table_name = ?
        order by ordinal_position`, [table]);
}

export async function sampleRows(envCfg, table, limit = 3) {
    ident(table);
    const n = Math.max(1, Math.min(Number(limit) || 3, 50));
    return rawQuery(envCfg, `select * from ${ident(table)} limit ${n}`, []);
}

export async function ping(envCfg) {
    const rows = await rawQuery(envCfg, "select 1 as ok", []);
    return rows.length > 0;
}

export async function closeAll() {
    for (const pool of pools.values()) { try { await pool.end(); } catch { /* ignore */ } }
    pools.clear();
}
```

## `templates/api-testing/mcp-server/src/lib/harness.js`

```javascript
import { sqlQuery } from "./db.js";
import { createClient } from "./http.js";

/**
 * story 执行上下文。
 * ctx.api(method,path,{query,body,headers}) -> {status,ok,bizOk,body}
 * ctx.get/post/put/patch/del 快捷方法
 * ctx.sql(text, params) 只读查询
 * ctx.assert(cond, msg, detail?) 断言失败抛 AssertionError(带 detail 证据)
 * ctx.waitUntilApi(method, path, opts, predicateFn) 轮询直到条件满足(禁手动 sleep)
 * ctx.info(msg) 记录信息到报告
 */
export function createContext({ envCfg, session }) {
    const client = createClient(envCfg, session);
    const infos = [];

    const ctx = {
        client,
        vars: session.vars,
        info: (msg) => infos.push(String(msg)),
        assert(cond, msg, detail) {
            if (!cond) {
                const e = new Error(`断言失败: ${msg}`);
                if (detail !== undefined) e.detail = detail;
                throw e;
            }
        },
        eq(actual, expected, label = "") {
            ctx.assert(Number(actual) === Number(expected), `${label || "值"} 应为 ${expected}, 实际 ${actual}`, { actual, expected });
        },
        async waitUntilApi(method, path, opts, predicate, { timeoutMs = 30000, intervalMs = 1000 } = {}) {
            const start = Date.now();
            let last = null;
            for (;;) {
                try {
                    last = await client.request(method, path, opts);
                    if (predicate(last)) return last;
                } catch (e) {
                    last = { error: e.message };
                }
                if (Date.now() - start > timeoutMs) {
                    throw new Error(`wait_until 超时(${timeoutMs}ms): 最后快照 ${JSON.stringify(last).slice(0, 500)}`);
                }
                await new Promise((r) => setTimeout(r, intervalMs));
            }
        },
        async waitUntilSql(sqlText, params, predicate, opt) {
            return ctx.waitUntilApiLike(async () => {
                const rows = await sqlQuery(envCfg, sqlText, params);
                return { rows };
            }, predicate, opt);
        },
        _infos: infos,
    };
    ctx.waitUntilApiLike = async (produce, predicate, { timeoutMs = 30000, intervalMs = 1000 } = {}) => {
        const start = Date.now();
        let last = null;
        for (;;) {
            try {
                last = await produce();
                if (predicate(last)) return last;
            } catch { /* 轮询期间错误视为未满足 */ }
            if (Date.now() - start > timeoutMs) throw new Error(`wait_until 超时(${timeoutMs}ms)`);
            await new Promise((r) => setTimeout(r, intervalMs));
        }
    };
    for (const m of ["get", "post", "put", "patch", "del"]) {
        ctx[m] = client[m];
    }
    ctx.api = (method, path, opts) => client.request(method, path, opts);
    ctx.sql = (text, params) => sqlQuery(envCfg, text, params);
    return ctx;
}
```

## `templates/api-testing/mcp-server/src/lib/http.js`

```javascript
import { renderTemplate } from "./config.js";

/**
 * 通用 HTTP 客户端: 合并 静态 headers + 会话鉴权 headers(支持 {{var}} 模板) + 调用级覆盖。
 * 成功判定: HTTP < 400 且 (未配置 codeField 或 body[codeField] === okValue)。
 */
export function isBizOk(status, json, envCfg) {
    if (status >= 400) return false;
    const codeField = envCfg.api?.codeField;
    if (!codeField) return true;
    return json && typeof json === "object" && json[codeField] === (envCfg.api?.okValue ?? 0);
}

export function createClient(envCfg, session) {
    async function request(method, path, { query, body, headers, raw } = {}) {
        const url = new URL(path, envCfg.api.baseUrl);
        for (const [k, v] of Object.entries(query || {})) {
            if (v !== undefined && v !== null) url.searchParams.set(k, String(v));
        }
        const merged = {
            ...envCfg.headers,
            ...resolvedAuthHeaders(session),
            ...headers,
        };
        const timeoutMs = envCfg.api?.timeoutMs || 15000;
        const init = { method: method.toUpperCase(), headers: merged, signal: AbortSignal.timeout(timeoutMs) };
        if (body !== undefined) {
            init.body = typeof body === "string" ? body : JSON.stringify(body);
            if (!merged["Content-Type"] && !merged["content-type"]) merged["Content-Type"] = "application/json";
        }
        let res, text;
        try {
            res = await fetch(url, init);
            text = await res.text();
        } catch (e) {
            const err = new Error(`请求失败 ${method} ${path}: ${e.message} (服务是否启动? baseUrl=${envCfg.api.baseUrl})`);
            err.code = "ENV_BLOCKED";
            throw err;
        }
        let json = null;
        try { json = text ? JSON.parse(text) : null; } catch { /* 非 JSON 响应 */ }
        const result = { status: res.status, ok: res.status < 400, bizOk: isBizOk(res.status, json, envCfg), body: json ?? text };
        if (!raw) return result;
        return { ...result, res };
    }
    return {
        request,
        get: (p, o) => request("GET", p, o),
        post: (p, body, o) => request("POST", p, { ...o, body }),
        put: (p, body, o) => request("PUT", p, { ...o, body }),
        patch: (p, body, o) => request("PATCH", p, { ...o, body }),
        del: (p, o) => request("DELETE", p, o),
    };
}

function resolvedAuthHeaders(session) {
    if (!session) return {};
    const tpl = session.authHeaders || {};
    const out = {};
    for (const [k, v] of Object.entries(tpl)) {
        try {
            out[k] = renderTemplate(v, session.vars);
        } catch (e) {
            // 登录链中间步骤允许部分鉴权头暂缺(lenientAuth); 正常业务请求由 ensureLogin 保证可解析
            if (session.lenientAuth) continue;
            throw e;
        }
    }
    return out;
}
```

## `templates/api-testing/mcp-server/src/lib/log.js`

```javascript
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

/** 尾读最新日志文件(按 mtime 取最新匹配), 可 grep 过滤; 未配置日志时给出明确说明 */
export function tailLog(envCfg, { lines = 80, grep = "" } = {}) {
    const dir = envCfg.log?.dir;
    const pattern = envCfg.log?.pattern || "*.log";
    if (!dir || !existsSync(dir)) {
        return { available: false, message: `未配置日志目录(log.dir="${dir || ""}")。该项目可能只输出 stdout/docker logs; 请用对应方式查看服务端日志。` };
    }
    const re = new RegExp("^" + pattern.replace(/[.+^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*") + "$");
    const files = readdirSync(dir)
        .filter((f) => re.test(f))
        .map((f) => join(dir, f))
        .filter((f) => statSync(f).isFile())
        .sort((a, b) => statSync(b).mtimeMs - statSync(a).mtimeMs);
    if (!files.length) return { available: false, message: `目录 ${dir} 无匹配 ${pattern} 的日志文件` };
    const file = files[0];
    const content = readFileSync(file, "utf-8");
    let out = content.split(/\r?\n/).slice(-lines);
    if (grep) out = out.filter((l) => l.includes(grep));
    return { available: true, file, lines: out };
}
```

## `templates/api-testing/mcp-server/src/lib/report.js`

```javascript
/** 报告渲染: markdown 汇总 + JSON 明细(写入需求目录 report/) */

export function renderReportMd({ title, startedAt, durationMs, envBlocked, results }) {
    const pass = results.filter((r) => r.pass).length;
    const known = results.filter((r) => !r.pass && r.known).length;
    const fail = results.filter((r) => !r.pass && !r.known).length;
    const lines = [];
    lines.push(`# 测试报告: ${title}`);
    lines.push("");
    lines.push(`- 时间: ${startedAt} | 总耗时 ${(durationMs / 1000).toFixed(1)}s`);
    lines.push(`- 结果: **${fail === 0 ? "PASS" : "FAIL"}** — 共 ${results.length}, 通过 ${pass}, 失败 ${fail}${known ? `(含已知缺陷 ${known})` : ""}${envBlocked ? ", 环境阻塞" : ""}`);
    lines.push("");
    lines.push("| Story | 结果 | 耗时 | 说明 |");
    lines.push("|---|---|---|---|");
    for (const r of results) {
        const mark = r.pass ? "PASS" : r.known ? "FAIL(known)" : "**FAIL**";
        lines.push(`| ${r.storyId} | ${mark} | ${r.durationMs}ms | ${escapeCell(r.error || r.title || "")} |`);
    }
    for (const r of results.filter((x) => x.infos?.length || x.error)) {
        lines.push("");
        lines.push(`## ${r.storyId}`);
        for (const i of r.infos || []) lines.push(`- ℹ️ ${i}`);
        if (r.error) {
            lines.push(`- ❌ ${r.error}`);
            if (r.detail) lines.push(`  - evidence: \`${truncate(JSON.stringify(r.detail), 800)}\``);
        }
    }
    lines.push("");
    return lines.join("\n");
}

function escapeCell(s) { return String(s).replace(/\|/g, "\\|").replace(/\n/g, " "); }
function truncate(s, n) { return s.length > n ? s.slice(0, n) + "…(截断)" : s; }
```
