# 日志中间件（logger-middleware）

> 本文件是技能包内可执行资产的 Markdown 转写 —— 分发通道只放行 `SKILL.md` 与 `references/*.md`。
> 落地方法：按各节标题里的路径原样写回磁盘，代码块内容与原文件一致。

## `references/logger-middleware.ts`

```typescript
/**
 * @file logger-middleware.ts
 * @author xudong.hua,gemini
 * @since 2026-08-24 17:48 星期一
 * @description 云原生可观测性结构化日志中间件（对齐 Prometheus + PLG 体系）
 * 
 * 核心能力：
 * 1. 【链路追踪】：自动生成或继承上游 `X-Request-Id`，并在响应头回写；
 * 2. 【结构化 JSON】：输出格式对齐 Promtail / Loki 日志解析规则；
 * 3. 【敏感脱敏】：自动屏蔽 password / token / secret / smsCode 等隐私参数；
 * 4. 【性能预警】：请求耗时超过 200ms 时自动提升日志级别为 WARN，标记慢响应。
 */

import { Context, Next } from 'hono';
import crypto from 'node:crypto';

// 敏感字段黑名单（自动脱敏）
const SENSITIVE_KEYS = new Set([
  'password', 'token', 'accessToken', 'refreshToken', 'secret',
  'appSecret', 'smsCode', 'code', 'credentialHash', 'authorization'
]);

function sanitize(obj: any): any {
  if (!obj || typeof obj !== 'object') return obj;
  if (Array.isArray(obj)) return obj.map(sanitize);
  
  const clean: Record<string, any> = {};
  for (const [k, v] of Object.entries(obj)) {
    if (SENSITIVE_KEYS.has(k)) {
      clean[k] = '***';
    } else if (typeof v === 'object') {
      clean[k] = sanitize(v);
    } else {
      clean[k] = v;
    }
  }
  return clean;
}

export interface StructuredLog {
  timestamp: string;
  level: 'INFO' | 'WARN' | 'ERROR';
  requestId: string;
  userId?: number;
  tenantId?: number;
  method: string;
  path: string;
  status: number;
  durationMs: number;
  clientIp: string;
  userAgent?: string;
  error?: {
    code?: string;
    message: string;
    stack?: string;
  };
}

export function createStructuredLogger() {
  return async function loggerMiddleware(c: Context, next: Next) {
    // 1. 提取或生成全局唯一的 Request ID
    const requestId = c.req.header('x-request-id') || `req_${crypto.randomBytes(8).toString('hex')}`;
    c.set('requestId', requestId);
    c.header('X-Request-Id', requestId);

    const start = Date.now();
    let caughtError: any = null;

    try {
      await next();
    } catch (err: any) {
      caughtError = err;
      throw err;
    } finally {
      const durationMs = Date.now() - start;
      const status = c.res ? c.res.status : (caughtError?.status || 500);

      // 提取客户端 IP
      const forwarded = c.req.header('x-forwarded-for');
      const clientIp = forwarded ? forwarded.split(',')[0].trim() : (c.req.header('x-real-ip') || '127.0.0.1');

      let level: 'INFO' | 'WARN' | 'ERROR' = 'INFO';
      if (status >= 500 || caughtError) {
        level = 'ERROR';
      } else if (status >= 400 || durationMs > 200) {
        level = 'WARN'; // 慢响应或客户端错误自动警告
      }

      const logPayload: StructuredLog = {
        timestamp: new Date().toISOString(),
        level,
        requestId,
        userId: c.get('userId'),
        tenantId: c.get('tenantId'),
        method: c.req.method,
        path: c.req.path,
        status,
        durationMs,
        clientIp,
        userAgent: c.req.header('user-agent')
      };

      if (caughtError) {
        logPayload.error = {
          code: caughtError.code || 'INTERNAL_ERROR',
          message: caughtError.message,
          stack: process.env.NODE_ENV === 'development' ? caughtError.stack : undefined
        };
      }

      // 输出标准单行 JSON，供 Promtail / Docker 守护进程直接采集进 Loki
      if (level === 'ERROR') {
        console.error(JSON.stringify(logPayload));
      } else if (level === 'WARN') {
        console.warn(JSON.stringify(logPayload));
      } else {
        console.log(JSON.stringify(logPayload));
      }
    }
  };
}
```
