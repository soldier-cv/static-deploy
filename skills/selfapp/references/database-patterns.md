# 数据表设计模式（database-patterns）

> 本文件是技能包内可执行资产的 Markdown 转写 —— 分发通道只放行 `SKILL.md` 与 `references/*.md`。
> 落地方法：按各节标题里的路径原样写回磁盘，代码块内容与原文件一致。

## `references/database-patterns.ts`

```typescript
/**
 * @file database-patterns.ts
 * @author xudong.hua,gemini
 * @since 2026-08-24 17:35 星期一
 * @description Drizzle ORM 数据表设计黄金范式库
 * 
 * 设计准则：
 * 1. 【时区规范】：全量时间戳统一采用 timestamp with time zone (timestamptz)，避免夏令时与跨时区数据混乱；
 * 2. 【多租户隔离】：所有业务表必须包含 tenant_id / family_id 外键与索引；
 * 3. 【合规审计】：签署日志等法定举证表采用只增不改设计（Append-only）；
 * 4. 【软删除回收站】：业务实体删除时采用快照入库 + FIFO 上限阈值控制。
 */

import { pgTable, serial, varchar, text, boolean, integer, jsonb, timestamp, uniqueIndex, index } from 'drizzle-orm/pg-core';

// ==========================================
// 1. 基础用户与会话体系范式
// ==========================================
export const users = pgTable('users', {
  id: serial('id').primaryKey(),
  phone: varchar('phone', { length: 20 }),
  nickname: varchar('nickname', { length: 50 }).notNull().default('用户'),
  avatarUrl: text('avatar_url'),
  createdAt: timestamp('created_at', { withTimezone: true }).notNull().defaultNow(),
  updatedAt: timestamp('updated_at', { withTimezone: true }).notNull().defaultNow()
});

export const refreshSessions = pgTable('refresh_sessions', {
  id: serial('id').primaryKey(),
  userId: integer('user_id').notNull().references(() => users.id, { onDelete: 'cascade' }),
  tokenHash: varchar('token_hash', { length: 128 }).notNull().unique(),
  deviceInfo: varchar('device_info', { length: 150 }).notNull().default('未知设备'),
  expiresAt: timestamp('expires_at', { withTimezone: true }).notNull(),
  revokedAt: timestamp('revoked_at', { withTimezone: true }),
  createdAt: timestamp('created_at', { withTimezone: true }).notNull().defaultNow()
}, (table) => ({
  userIdIdx: index('idx_refresh_sessions_user').on(table.userId)
}));

// ==========================================
// 2. 协议字典、版本快照与用户签署审计表
// ==========================================
export const agreements = pgTable('agreements', {
  id: varchar('id', { length: 32 }).primaryKey(), // 'user_terms' / 'privacy_policy' / 'data_security'
  title: varchar('title', { length: 64 }).notNull(),
  isRequired: boolean('is_required').notNull().default(true),
  createdAt: timestamp('created_at', { withTimezone: true }).notNull().defaultNow()
});

export const agreementVersions = pgTable('agreement_versions', {
  id: serial('id').primaryKey(),
  agreementId: varchar('agreement_id', { length: 32 }).notNull().references(() => agreements.id),
  version: varchar('version', { length: 32 }).notNull(), // 'v1.0.0' 或 '2026.08.v1'
  contentUrl: text('content_url'),                       // S3/CDN 静态托管地址
  contentHash: varchar('content_hash', { length: 64 }).notNull(), // SHA256 防篡改举证
  isMajor: boolean('is_major').notNull().default(false), // 重大变更触发全员强制弹窗
  summary: text('summary'),                              // 变更摘要
  effectiveAt: timestamp('effective_at', { withTimezone: true }).notNull(),
  createdAt: timestamp('created_at', { withTimezone: true }).notNull().defaultNow()
}, (table) => ({
  agreementVersionUq: uniqueIndex('uq_agreement_version').on(table.agreementId, table.version)
}));

export const userConsents = pgTable('user_consents', {
  id: serial('id').primaryKey(),
  userId: integer('user_id').notNull().references(() => users.id, { onDelete: 'cascade' }),
  agreementId: varchar('agreement_id', { length: 32 }).notNull().references(() => agreements.id),
  version: varchar('version', { length: 32 }).notNull(),
  clientPlatform: varchar('client_platform', { length: 16 }).notNull(), // 'weapp' / 'android' / 'ios' / 'web'
  clientVersion: varchar('client_version', { length: 32 }).notNull().default('1.0.0'),
  clientIp: varchar('client_ip', { length: 64 }),
  agreedAt: timestamp('agreed_at', { withTimezone: true }).notNull().defaultNow()
}, (table) => ({
  userAgreementIdx: index('idx_user_consents_lookup').on(table.userId, table.agreementId)
}));

// ==========================================
// 3. 通用回收站快照表（FIFO 阈值管理）
// ==========================================
export const trashItems = pgTable('trash_items', {
  id: serial('id').primaryKey(),
  tenantId: integer('tenant_id').notNull(), // 租户空间 ID
  entityType: varchar('entity_type', { length: 30 }).notNull(), // 'gift' / 'event' / 'milestone'
  title: varchar('title', { length: 200 }).notNull(),
  sub: varchar('sub', { length: 300 }),
  payload: jsonb('payload').notNull(), // 原始实体的全量 JSON 快照，恢复时还原
  deletedAt: timestamp('deleted_at', { withTimezone: true }).notNull().defaultNow()
}, (table) => ({
  tenantIdx: index('idx_trash_tenant').on(table.tenantId)
}));
```
