# 滑动窗口限流（sliding-rate-limiter）

> 本文件是技能包内可执行资产的 Markdown 转写 —— 分发通道只放行 `SKILL.md` 与 `references/*.md`。
> 落地方法：按各节标题里的路径原样写回磁盘，代码块内容与原文件一致。

## `references/sliding-rate-limiter.ts`

```typescript
/**
 * @file sliding-rate-limiter.ts
 * @author xudong.hua,gemini
 * @since 2026-08-24 17:35 星期一
 * @description 基于 Redis 7 的高性能滑动窗口限频与 IP 并发防刷中间件
 * 
 * 设计意图：
 * 1. 传统固定窗口（Fixed Window）在窗口临界点存在 2 倍流量突刺漏洞；
 * 2. 采用 Redis ZSET 实现真正的毫秒级滑动窗口（Sliding Window），精准计算窗口内请求次数；
 * 3. 针对不同场景支持「按 IP 限频」（防恶意扫描/暴力撞库）与「按 User ID 限频」（防接口滥用）。
 */

import { Context, Next } from 'hono';
import { HTTPException } from 'hono/http-exception';
import type { Redis } from 'ioredis';

export interface RateLimitOptions {
  /** 窗口时间跨度（秒） */
  windowSec: number;
  /** 窗口内允许的最大请求数 */
  maxRequests: number;
  /** 限制维度：ip (客户端公网IP) 或 user (登录用户ID) */
  keyPrefix?: string;
  /** 自定义提取 Key 的函数 */
  keyGenerator?: (c: Context) => string;
}

/**
 * 获取客户端真实 IP
 */
export function getClientIp(c: Context): string {
  const forwarded = c.req.header('x-forwarded-for');
  if (forwarded) {
    const ips = forwarded.split(',').map((ip) => ip.trim());
    return ips[0] || '127.0.0.1';
  }
  const realIp = c.req.header('x-real-ip');
  if (realIp) return realIp.trim();
  return '127.0.0.1';
}

/**
 * 创建滑动窗口限流中间件
 */
export function createSlidingRateLimiter(redis: Redis, options: RateLimitOptions) {
  const { windowSec, maxRequests, keyPrefix = 'rate_limit' } = options;

  return async function rateLimiter(c: Context, next: Next) {
    const now = Date.now();
    const windowMs = windowSec * 1000;
    const clearBefore = now - windowMs;

    let identifier = '';
    if (options.keyGenerator) {
      identifier = options.keyGenerator(c);
    } else {
      identifier = getClientIp(c);
    }

    const redisKey = `${keyPrefix}:${identifier}`;

    // 使用 Redis Pipeline 执行原子事务操作
    const pipe = redis.pipeline();
    // 1. 移除窗口外的历史时间戳
    pipe.zremrangebyscore(redisKey, 0, clearBefore);
    // 2. 将当前请求时间戳作为 score 与 member 写入
    pipe.zadd(redisKey, now, `${now}-${Math.random().toString(36).substring(2, 7)}`);
    // 3. 统计当前窗口内剩余的总请求数
    pipe.zcard(redisKey);
    // 4. 设置整个 key 的生存时间（略大于窗口期）
    pipe.expire(redisKey, windowSec + 5);

    const results = await pipe.exec();
    if (!results) {
      // Redis 降级处理，保证可用性
      return await next();
    }

    const currentCount = results[2][1] as number;

    // 设置标准 HTTP 速率限制头
    c.header('X-RateLimit-Limit', String(maxRequests));
    c.header('X-RateLimit-Remaining', String(Math.max(0, maxRequests - currentCount)));
    c.header('X-RateLimit-Reset', String(Math.ceil((now + windowMs) / 1000)));

    if (currentCount > maxRequests) {
      throw new HTTPException(429, {
        message: JSON.stringify({
          error: {
            code: 'RATE_LIMIT_EXCEEDED',
            message: `请求过于频繁，请在 ${windowSec} 秒后重试`
          }
        })
      });
    }

    await next();
  };
}
```
