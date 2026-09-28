# static-deploy: 局域网静态原型与生图展示中心

专为手机远程指挥本机 AI Agent 开发打造的局域网静态资产部署与总览平台。

解决核心痛点：手机上远程让 Agent 写前端原型或生图时，输出的都是本机路径无法查看。通过本系统，Agent 自动将原型或图片推送到内网服务器（88 服务器），并向手机端回复点击直达链接与二维码看板。

---

## 目录结构

```
static-deploy/
├── server/                    # 服务端组件（部署至 88 服务器 100.64.0.88）
│   ├── portal.html            # 移动端优先的总览看板（符合 taste-skill 规范，零 Emoji，零破折号）
│   ├── receiver.py            # 纯 Python 标准库接收、解包与远程 MCP 端点（零外部依赖）
│   ├── nginx.conf             # Nginx 静态直发、文档托管与反向代理配置
│   ├── docker-compose.yml     # 遵循 88 服务器规范（含日志限制、资源配额）
│   ├── .env.example           # 环境变量模板
│   ├── .env                   # 默认环境变量
│   └── OPERATIONS.md          # 88 服务器标准运维手册
├── client-mcp/                # 本机 stdio MCP（可选，用于传本地路径）
│   ├── mcp_server.py          # 标准 MCP Server（Stdio 协议，纯 Python 标准库）
│   ├── deploy_cli.py          # 本地命令行快速部署工具
│   ├── mcp_config_example.json# Cursor / Claude / Antigravity 配置示例
│   └── README.md              # 客户端接入详细文档
├── mcp/                       # 集中式 MCP 接入文档（由本服务 /docs/ 托管）
├── scripts/
│   └── deploy_to_88.ps1       # SSH 到 88 后 git pull 并拉起容器
├── tools/
│   └── selftest_mcp.py        # MCP 端点验收 harness
└── README.md
```

---

## 核心特性

1. **轻量与高性能**：
   * 服务端由 **Nginx 静态直发 + Python 标准库 API** 构成，**0 外部 SDK 安装**，总常驻内存约 **28MB**。
2. **符合 `taste-skill` 前端设计标准**：
   * 采用 Linear 风格冷灰科技暗黑主题（Zinc-950 底色 + 单一电光蓝强调色）；
   * **全站零 Emoji 符号、零破折号**，全面采用 14px 细致矢量 SVG 图标；
   * 严格防止窄屏文字垂直折行，手机端单列沉浸式浏览，桌面端自适应卡片网格。
3. **极速闭环体验**：
   * **支持原型目录打包**：本地多级 HTML/CSS/JS/图片一次性流式传输并服务端原子解包；
   * **支持单张设计生图**：自动识别图片格式，手机端点击全屏大图预览；
   * **离线二维码直达**：每个项目卡片内置离线纯 JS 二维码，手机直接扫码秒开。
4. **远程 MCP 零安装**：Agent 只填一个 URL 即可调用，局域网默认免鉴权。

---

## 快速上手

### 步骤一：在 88 服务器上更新并启动

代码目录：`/opt/code/static-deploy`  
数据目录：`/data/static-deploy`

```bash
cd /opt/code/static-deploy
git pull --ff-only
docker compose -f server/docker-compose.yml --env-file server/.env up -d
```

启动后即可直接访问：

* **总览看板**：`http://100.64.0.88:8088/`
* **API 健康检测**：`http://100.64.0.88:8088/api/health`
* **MCP 端点**：`http://100.64.0.88:8088/mcp`
* **MCP 接入文档**：`http://100.64.0.88:8088/docs/`

容器名：`static-deploy-web`、`static-deploy-api`。

### 步骤二：MCP 接入（推荐远程端点）

优先使用远程 MCP，Agent 只需配置一个 URL，零安装、免鉴权：

```json
{
  "mcpServers": {
    "static-deploy": {
      "url": "http://100.64.0.88:8088/mcp"
    }
  }
}
```

完整接入说明、工具参数与 FAQ 见：

* 文档中心：`http://100.64.0.88:8088/docs/`
* 本项目文档：`http://100.64.0.88:8088/docs/static-deploy.md`

本机 stdio 模式仅在需要传本地路径（`source_path` / `image_path`）时使用，详见 `client-mcp/README.md`。

### 步骤三：日常使用

在手机端指挥 Agent 编写原型：
> 请帮我做一个新的活动倒计时弹窗原型，并提交预览。

Agent 完成开发后将自动调用 `deploy_static_project` 工具，并在聊天框直接向您回复可在手机上点击打开的预览 URL。
