# 环境变量模式（env-schema）

> 本文件是技能包内可执行资产的 Markdown 转写 —— 分发通道只放行 `SKILL.md` 与 `references/*.md`。
> 落地方法：按各节标题里的路径原样写回磁盘，代码块内容与原文件一致。

## `references/env-schema.ts`

```typescript
/**
 * @file env-schema.ts
 * @author xudong.hua,gemini
 * @since 2026-08-24 17:35 星期一
 * @description 生产级环境变量 Zod 强类型校验与加载模块范式
 * 
 * 设计意图：
 * 1. 杜绝在业务代码中直接读取不可靠、可能为 undefined 的 process.env.XXX；
 * 2. 在应用启动的第一毫秒执行全量校验，若缺失关键配置或格式不合法立即阻断启动并打印清晰指引；
 * 3. 对端口、布尔值、超时时间等字段进行安全类型转换（Transform/Coerce）。
 */

import { z } from 'zod';
import dotenv from 'dotenv';
import path from 'node:path';

// 优先加载 .env 文件
dotenv.config({ path: path.resolve(process.cwd(), '.env') });

export const envSchema = z.object({
  // 运行环境
  NODE_ENV: z.enum(['development', 'production', 'test']).default('development'),
  PORT: z.coerce.number().int().positive().default(3000),
  HOST: z.string().default('0.0.0.0'),

  // 数据库配置 (PostgreSQL 16)
  DATABASE_URL: z.string().url('DATABASE_URL 必须为合法的 PostgreSQL 连接串'),
  DB_MAX_CONNECTIONS: z.coerce.number().int().positive().default(20),

  // Redis 缓存与频控 (Redis 7)
  REDIS_URL: z.string().url('REDIS_URL 必须为合法的 Redis 连接串').default('redis://127.0.0.1:6379'),

  // JWT 与会话安全
  JWT_SECRET: z.string().min(32, 'JWT_SECRET 密钥长度不得低于 32 字符'),
  ACCESS_TOKEN_EXP_SECONDS: z.coerce.number().int().positive().default(900), // 15分钟
  REFRESH_TOKEN_EXP_DAYS: z.coerce.number().int().positive().default(15),     // 15天

  // 微信登录凭据
  WECHAT_APP_ID: z.string().min(1, 'WECHAT_APP_ID 必填'),
  WECHAT_APP_SECRET: z.string().min(1, 'WECHAT_APP_SECRET 必填'),
  WECHAT_MOCK_LOGIN: z.coerce.boolean().default(false), // 本地开发 Mock 开关

  // S3 / MinIO 对象存储 (预签名直传)
  S3_ENDPOINT: z.string().url('S3_ENDPOINT 必须为合法 URL'),
  S3_REGION: z.string().default('us-east-1'),
  S3_BUCKET: z.string().min(1, 'S3_BUCKET 存储桶名称必填'),
  S3_ACCESS_KEY: z.string().min(1, 'S3_ACCESS_KEY 必填'),
  S3_SECRET_KEY: z.string().min(1, 'S3_SECRET_KEY 必填'),
  S3_PUBLIC_DOMAIN: z.string().url('S3_PUBLIC_DOMAIN 必须为合法公开访问域名'),

  // 频控与并发防护阈值
  RATE_LIMIT_GLOBAL_WINDOW_SEC: z.coerce.number().int().positive().default(60),
  RATE_LIMIT_GLOBAL_MAX_REQUESTS: z.coerce.number().int().positive().default(120),
  RATE_LIMIT_SMS_MAX_PER_HOUR: z.coerce.number().int().positive().default(5)
});

export type Env = z.infer<typeof envSchema>;

export function parseEnv(): Env {
  const result = envSchema.safeParse(process.env);
  if (!result.success) {
    console.error('\n❌ [FATAL] 环境变量校验失败，应用终止启动:');
    result.error.issues.forEach((issue) => {
      console.error(`  - 字段 [${issue.path.join('.')}]: ${issue.message}`);
    });
    console.error('\n请检查 .env 配置文件并确保必填项齐全。\n');
    process.exit(1);
  }
  return result.data;
}

export const env = parseEnv();
```
