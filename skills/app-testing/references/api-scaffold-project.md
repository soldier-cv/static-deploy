# 测试包脚手架：案例目录、缺陷台账与文档模板

> 本文件是技能包内可执行资产的 Markdown 转写 —— 分发通道只放行 `SKILL.md` 与 `references/*.md`。
> 落地方法：按各节标题里的路径原样写回磁盘，代码块内容与原文件一致。

## `scaffold/README.md`

````markdown
# 接口测试工具包 (tools/api-testing)

> 无前端时由 AI 按 story 驱动: 登录 → 调接口 → 查库验证 → 造数(留库) → 报告。
> 由全局技能 **app-testing** 的脚手架初始化; 方法论/约定详见该技能, 本 README 记录本项目特有事实与演进。

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
| (init) | 由 app-testing 脚手架初始化 | — |
````

## `scaffold/defects.json`

```json
{
  "$comment": "缺陷生命周期单源。状态机: open(已知缺陷, 报告标 known 不算回归红) -> fixed(待回归) -> verified(回归通过) / wontfix。origin: history=历史存量 | requirement=本次需求发现",
  "defects": []
}
```

## `scaffold/cases/README.md`

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

## `scaffold/cases/_template/stories.js`

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

## `scaffold/cases/_template/story.md`

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

## `scaffold/docs/api-reference.template.md`

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

## `scaffold/docs/db-reference.template.md`

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
