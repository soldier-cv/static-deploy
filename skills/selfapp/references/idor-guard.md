# 越权防护（idor-guard）

> 本文件是技能包内可执行资产的 Markdown 转写 —— 分发通道只放行 `SKILL.md` 与 `references/*.md`。
> 落地方法：按各节标题里的路径原样写回磁盘，代码块内容与原文件一致。

## `references/idor-guard.ts`

```typescript
/**
 * @file idor-guard.ts
 * @author xudong.hua,gemini
 * @since 2026-08-24 17:35 星期一
 * @description 多租户防越权守卫（IDOR Defense）与双 Token 鉴权中间件范式
 * 
 * 设计意图：
 * 1. 统一提取与校验 Header（Authorization 与 X-Tenant-Id / X-Family-Id）；
 * 2. 严格校验当前登录用户是否属于该租户/家庭空间，杜绝参数遍历越权；
 * 3. 向请求上下文 context 自动注入 userId, tenantId, memberRole，供业务控制器与 DB 层直接使用。
 */

import { Context, Next } from 'hono';
import { HTTPException } from 'hono/http-exception';
import jwt from 'jsonwebtoken';
import { env } from './env-schema.js';

export interface UserJwtPayload {
  userId: number;
  openId?: string;
  iat: number;
  exp: number;
}

export interface TenantContext {
  userId: number;
  tenantId: number;
  role: 'OWNER' | 'ADMIN' | 'MEMBER' | 'GUEST';
}

/**
 * 1. 用户登录认证中间件 (requireAuth)
 */
export async function requireAuth(c: Context, next: Next) {
  const authHeader = c.req.header('Authorization');
  if (!authHeader || !authHeader.startsWith('Bearer ')) {
    throw new HTTPException(401, {
      message: JSON.stringify({ error: { code: 'AUTH_REQUIRED', message: '请先登录' } })
    });
  }

  const token = authHeader.slice(7);
  try {
    const decoded = jwt.verify(token, env.JWT_SECRET) as UserJwtPayload;
    c.set('userId', decoded.userId);
    await next();
  } catch (err: any) {
    if (err.name === 'TokenExpiredError') {
      throw new HTTPException(401, {
        message: JSON.stringify({ error: { code: 'TOKEN_EXPIRED', message: '登录已过期，请刷新令牌' } })
      });
    }
    throw new HTTPException(401, {
      message: JSON.stringify({ error: { code: 'INVALID_TOKEN', message: '无效的身份令牌' } })
    });
  }
}

/**
 * 2. 多租户/家庭空间防越权守卫 (requireTenant / requireFamily)
 * 依赖 DB 检查用户与租户的绑定关系
 */
export function createTenantGuard(checkUserInTenant: (userId: number, tenantId: number) => Promise<{ isMember: boolean; role?: string } | null>) {
  return async function requireTenant(c: Context, next: Next) {
    const userId = c.get('userId') as number;
    if (!userId) {
      throw new HTTPException(401, { message: JSON.stringify({ error: { code: 'AUTH_REQUIRED', message: '未授权' } }) });
    }

    const tenantHeader = c.req.header('X-Tenant-Id') || c.req.header('X-Family-Id');
    if (!tenantHeader) {
      throw new HTTPException(400, {
        message: JSON.stringify({ error: { code: 'TENANT_REQUIRED', message: '缺少租户标识头 (X-Tenant-Id)' } })
      });
    }

    const tenantId = parseInt(tenantHeader, 10);
    if (isNaN(tenantId) || tenantId <= 0) {
      throw new HTTPException(400, {
        message: JSON.stringify({ error: { code: 'INVALID_TENANT_ID', message: '非法的租户标识' } })
      });
    }

    // 核心 IDOR 校验：检查当前用户是否属于该租户
    const member = await checkUserInTenant(userId, tenantId);
    if (!member || !member.isMember) {
      throw new HTTPException(403, {
        message: JSON.stringify({ error: { code: 'NOT_TENANT_MEMBER', message: '您不是该空间成员，无权访问' } })
      });
    }

    // 注入上下文，后续 DB 操作强制附加 WHERE tenant_id = c.get('tenantId')
    c.set('tenantId', tenantId);
    c.set('tenantRole', member.role || 'MEMBER');

    await next();
  };
}
```
