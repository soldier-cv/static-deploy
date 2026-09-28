# static-preview: 局域网静态原型与生图展示中心

专为**手机远程指挥 Windows AI Agent 开发**打造的局域网静态资产部署与总览平台。

解决核心痛点：手机上远程让 Agent 写前端原型或生图时，输出的都是 Windows 本地路径无法查看。通过本系统，Agent 自动将原型或图片推送到内网服务器（88 服务器），并向手机端回复点击直达链接与二维码看板。

---

## 目录结构

```
static_deploy/
├── server/                    # 服务端组件（部署至 88 服务器 100.64.0.88）
│   ├── portal.html            # 移动端优先的总览看板（符合 taste-skill 规范，零 Emoji，零破折号）
│   ├── receiver.py            # 纯 Python 标准库接收与解包程序（零外部依赖，常驻内存 < 20MB）
│   ├── nginx.conf             # OpenResty / Nginx 静态直发与反向代理配置
│   ├── docker-compose.yml     # 遵循 88 服务器规范（含日志限制、资源配额）
│   ├── .env.example           # 环境变量模板
│   ├── .env                   # 默认环境变量
│   └── OPERATIONS.md          # 88 服务器标准运维手册
├── client-mcp/                # 客户端 MCP（运行在 Windows 本机，供 AI Agent 调用）
│   ├── mcp_server.py          # 标准 MCP Server（Stdio 协议，纯 Python 标准库）
│   ├── deploy_cli.py          # 本地命令行快速部署工具
│   ├── mcp_config_example.json# Cursor / Claude / Antigravity 配置示例
│   └── README.md              # 客户端接入详细文档
├── scripts/
│   └── deploy_to_88.ps1       # 一键向 88 服务器发布上线的 PowerShell 自动化脚本
└── README.md
```

---

## 核心特性

1. **轻量与高性能 (Ultra-low Resource)**：
   * 服务端由 **Nginx 静态直发 + Python 标准库 API** 构成，**0 外部 SDK 安装**，总常驻内存仅 **~28MB**，无额外负担。
2. **符合 `taste-skill` 前端设计标准**：
   * 采用 Linear 风格冷灰科技暗黑主题（Zinc-950 底色 + 单一电光蓝强调色）；
   * **全站零 Emoji 符号、零破折号**，全面采用 14px 细致矢量 SVG 图标；
   * 严格防止窄屏文字垂直折行，手机端单列沉浸式浏览，桌面端自适应卡片网格。
3. **极速闭环体验**：
   * **支持原型目录打包**：本地多级 HTML/CSS/JS/图片一次性流式传输并服务端原子解包；
   * **支持单张设计生图**：自动识别图片格式，手机端点击全屏大图预览；
   * **离线二维码直达**：每个项目卡片内置离线纯 JS 二维码，手机直接扫码秒开。

---

## 快速上手

### 步骤一：Git 提交并在内网服务器部署启动

1. **本地推送代码至 Git 仓库**：
   ```bash
   git init
   git add .
   git commit -m "feat: init static-preview system"
   git remote add origin <你的Git仓库地址>
   git push -u origin main
   ```

2. **在内网 88 服务器拉取并启动**：
   ```bash
   # 1. 克隆或拉取代码至 88 服务器标准部署目录
   git clone <你的Git仓库地址> /opt/deploy/static-preview
   cd /opt/deploy/static-preview/server

   # 2. 预先创建数据持久化目录并赋权（符合 88 规范）
   sudo mkdir -p /data/static-preview && sudo chmod -R 755 /data/static-preview

   # 3. 启动容器（无需编译，直接拉取官方标准 alpine 镜像，秒级运行）
   docker compose up -d
   ```

   启动后即可直接访问：
   * 📱 **总览看板**：`http://100.64.0.88:8088/`
   * 🩺 **API 健康检测**：`http://100.64.0.88:8088/api/health`

### 步骤二：在 Windows Agent 中配置 MCP

将以下配置复制到您的 Agent MCP 配置文件中（如 Cursor 或 Claude Desktop）：

```json
{
  "mcpServers": {
    "static-preview": {
      "command": "python",
      "args": [
        "d:\\project\\static_deploy\\client-mcp\\mcp_server.py"
      ],
      "env": {
        "PREVIEW_SERVER_HOST": "100.64.0.88",
        "PREVIEW_SERVER_PORT": "8088",
        "PREVIEW_API_TOKEN": "lan-static-preview-token-2026"
      }
    }
  }
}
```

### 步骤三：日常使用

在手机端像往常一样指挥 Agent 编写原型：
> “*请帮我做一个新的活动倒计时弹窗原型，并提交预览。*”

Agent 完成开发后将自动调用 `deploy_static_project` 工具，并在聊天框直接向您回复可在手机上点击打开的预览 URL！
