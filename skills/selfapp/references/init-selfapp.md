# 初始化脚本（init-selfapp.mjs）

> 本文件是技能包内可执行资产的 Markdown 转写 —— 分发通道只放行 `SKILL.md` 与 `references/*.md`。
> 落地方法：按各节标题里的路径原样写回磁盘，代码块内容与原文件一致。

## `scripts/init-selfapp.mjs`

```javascript
#!/usr/bin/env node
/**
 * @file init-selfapp.mjs
 * @author xudong.hua,gemini
 * @since 2026-08-24 17:35 星期一
 * @description 一键初始化自研独立应用（Self-App）标准骨架与规范文档套件
 * 
 * 用法:
 *   node init-selfapp.mjs <target-directory> --name=<project-slug> --title=<中文应用名称> --slogan=<品牌标语>
 * 示例:
 *   node init-selfapp.mjs D:/dev/agent-repos/myapp --name=myapp --title=我的应用 --slogan=让生活更美好
 */

import fs from 'node:fs';
import path from 'node:path';

const args = process.argv.slice(2);
const targetDir = args[0] ? path.resolve(args[0]) : process.cwd();

function getArg(key, def) {
  const prefix = `--${key}=`;
  const found = args.find(a => a.startsWith(prefix));
  return found ? found.slice(prefix.length) : def;
}

const name = getArg('name', path.basename(targetDir));
const title = getArg('title', name);
const slogan = getArg('slogan', '专业·高效·温情');

console.log(`\n🚀 [Self-App 脚手架] 正在初始化项目: ${title} (${name})`);
console.log(`📁 目标路径: ${targetDir}\n`);

// 1. 创建核心目录树
const dirs = [
  'packages/core/src/constants',
  'packages/core/src/schemas',
  'packages/core/src/types',
  'packages/server/src/config',
  'packages/server/src/db',
  'packages/server/src/lib',
  'packages/server/src/middleware',
  'packages/server/src/routes',
  'packages/client',
  'prototype/css',
  'prototype/js',
  'docs/legal',
  'tools/api-testing/cases'
];

for (const d of dirs) {
  const p = path.join(targetDir, d);
  if (!fs.existsSync(p)) fs.mkdirSync(p, { recursive: true });
}

// 2. 生成根目录 pnpm-workspace.yaml
fs.writeFileSync(path.join(targetDir, 'pnpm-workspace.yaml'), `packages:
  - 'packages/*'
  - 'tools/*'
`, 'utf8');

// 3. 生成根目录 turbo.json
fs.writeFileSync(path.join(targetDir, 'turbo.json'), `{
  "$schema": "https://turbo.build/schema.json",
  "tasks": {
    "build": {
      "dependsOn": ["^build"],
      "outputs": ["dist/**", "dist-browser/**", "dist-cjs/**"]
    },
    "dev": {
      "cache": false,
      "persistent": true
    },
    "type-check": {
      "dependsOn": ["^build"]
    }
  }
}
`, 'utf8');

// 4. 生成根目录 package.json
fs.writeFileSync(path.join(targetDir, 'package.json'), `{
  "name": "${name}-monorepo",
  "version": "1.0.0",
  "private": true,
  "scripts": {
    "dev": "turbo run dev",
    "build": "turbo run build",
    "type-check": "turbo run type-check"
  },
  "devDependencies": {
    "turbo": "^2.0.0",
    "typescript": "^5.5.0"
  }
}
`, 'utf8');

// 5. 生成标准环境变量模板 .env.example
fs.writeFileSync(path.join(targetDir, '.env.example'), `# 基础配置
NODE_ENV=development
PORT=3000
HOST=0.0.0.0

# 数据库 (PostgreSQL 16)
DATABASE_URL=postgres://postgres:postgres@localhost:5432/${name}_dev

# Redis 7
REDIS_URL=redis://127.0.0.1:6379

# JWT 安全密钥 (>=32 字符)
JWT_SECRET=replace_this_with_a_super_secret_key_at_least_32_chars_long

# 微信登录凭据
WECHAT_APP_ID=mock_appid
WECHAT_APP_SECRET=mock_secret
WECHAT_MOCK_LOGIN=true

# S3 / MinIO 对象存储
S3_ENDPOINT=http://localhost:9000
S3_REGION=us-east-1
S3_BUCKET=${name}
S3_ACCESS_KEY=minioadmin
S3_SECRET_KEY=minioadmin
S3_PUBLIC_DOMAIN=http://localhost:9000/${name}
`, 'utf8');

// 6. 生成标准 .gitignore
fs.writeFileSync(path.join(targetDir, '.gitignore'), `# Dependencies
node_modules/
.pnpm-store/

# Environment Variables & Secrets (CRITICAL)
.env
.env.*
!.env.example

# Build Outputs & Turborepo
dist/
dist-*/
build/
.turbo/

# uni-app & Mobile Artifacts
unpackage/
packages/client/dist/

# Logs & Observability
*.log
logs/
npm-debug.log*

# System & IDE
.DS_Store
Thumbs.db
.idea/
.vscode/*
!.vscode/extensions.json
!.vscode/settings.json
`, 'utf8');

// 7. 生成标准 .dockerignore (轻量镜像 & 凭据防泄漏)
fs.writeFileSync(path.join(targetDir, '.dockerignore'), `.git/
.gitignore
.env
.env.*
!.env.example
node_modules/
.pnpm-store/
.turbo/
dist/
build/
unpackage/
packages/client/
prototype/
docs/
tools/
*.log
*.md
`, 'utf8');

// 8. 生成 tools/api-testing/.gitignore
fs.writeFileSync(path.join(targetDir, 'tools/api-testing/.gitignore'), `# 本地私密凭据目录（严禁入库）
local/
mcp-server/local/
*.local.json

# 跑批临时报告与日志（避免海量脏 diff）
cases/**/report/
report/
*.log

# 依赖
node_modules/
`, 'utf8');

// 9. 生成基础工程文档骨架
const docs = [
  ['docs/01-产品需求规格说明书(PRD).md', `# 01 · 产品需求规格说明书（PRD）\n\n| 属性 | 内容说明 |\n| --- | --- |\n| 项目名称 | ${title} · ${name} |\n| 品牌标语 | ${slogan} |\n| 文档版本 | v1.0 |\n\n## 1. 产品概述\n\n## 2. 角色与权限矩阵\n\n## 3. 核心业务流程\n`],
  ['docs/02-系统架构与核心技术方案.md', `# 02 · 系统架构与核心技术方案\n\n| 属性 | 内容说明 |\n| --- | --- |\n| 项目名称 | ${title} |\n| 技术栈 | TypeScript Monorepo + Hono + Drizzle ORM + PostgreSQL 16 + Redis 7 + uni-app Vue3 |\n\n## 1. 架构总览\n\n## 2. 核心安全防御（双 Token、多租户 IDOR 防护、Redis IP 并发限频）\n\n## 3. 协议合规与客户端多级缓存架构\n\n## 4. 可观测性（Prometheus + PLG 链路追踪）\n`],
  ['docs/03-数据库设计与API接口契约.md', `# 03 · 数据库设计与 API 接口契约规范\n\n| 属性 | 内容说明 |\n| --- | --- |\n| 数据库选型 | PostgreSQL 16 |\n| ORM | Drizzle ORM |\n\n## 1. 实体关系模型 (ERD)\n\n## 2. 数据字典 (Schema)\n\n## 3. API 接口契约 (REST / Hono RPC)\n`],
  ['docs/04-视觉规范与UI-UX交互标准.md', `# 04 · 视觉规范与 UI-UX 交互标准\n\n| 属性 | 内容说明 |\n| --- | --- |\n| 视觉风格 | 典雅新中式 / 精美手账风 |\n| 符号规范 | 严格禁止在生产界面与提示语中使用 Emoji 符号，采用统一矢量 SVG 图标 |\n`],
  ['docs/05-工程协作与开发指南.md', `# 05 · 工程协作与开发指南\n\n## 1. 快速启动\n\n## 2. 数据库迁移\n\n## 3. API 自动化测试\n`],
  ['docs/06-uniapp客户端开发与验收工作法.md', `# 06 · uni-app 客户端开发与验收工作法\n\n| 属性 | 内容说明 |\n| --- | --- |\n| 视觉真理 | prototype/index.html |\n| 台账中心 | feature-hub (项目名: ${name}) |\n\n## 1. 四段闸门工作流 (接线 -> 扫清单 -> 确认骨架 -> 逐页还原验收)\n`]
];

for (const [docPath, content] of docs) {
  fs.writeFileSync(path.join(targetDir, docPath), content, 'utf8');
}

console.log(`✅ [完成] 项目 ${title} 目录结构、.gitignore、.dockerignore、规范文档与脚手架已成功初始化！`);
```
