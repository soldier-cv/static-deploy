# Self-App 场景特有 API 测试模板（templates/api-testing）

> 本文件是技能包内可执行资产的 Markdown 转写 —— 分发通道只放行 `SKILL.md` 与 `references/*.md`。
> 落地方法：按各节标题里的路径原样写回磁盘，代码块内容与原文件一致。
> 
> 说明：`tools/api-testing` 的通用脚手架、MCP Server 完整实现、测试环境配置与用例生命周期管理，请参考 [api-testing-toolkit](../../api-testing-toolkit/SKILL.md) 技能包（及其 `references/scaffold-mcp-server.md` 与 `references/scaffold-project.md`）。
> 本文件仅收录 Self-App 场景特有的轻量执行引擎与用例模板（微信登录 Mock、双 Token 轮转、用户协议签署留痕、多租户 IDOR 防御）。

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
