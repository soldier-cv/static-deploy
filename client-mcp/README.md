# 客户端 MCP 接入与配置指南

本模块为运行在 Windows 本机的 MCP Server，使用 Python 3 标准库构建，**无需安装任何额外的 pip 依赖包**。

## 1. 支持接入的客户端

*   **Claude Desktop** (`%APPDATA%\Claude\claude_desktop_config.json`)
*   **Cursor** (设置 -> Features -> MCP Servers)
*   **Antigravity** (`~/.gemini/antigravity/` 或项目级 `.agents/`)
*   **Windsurf / Cline / Roo Code** 等所有兼容 Model Context Protocol 的工具

## 2. 配置方式

将以下 JSON 片段添加至您的 MCP 配置文件中：

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

## 3. Agent 自动化调用示例

在手机端通过聊天对话指挥 Windows Agent 时，Agent 完成原型开发后会自动调用：

```json
deploy_static_project({
  "source_path": "D:\\project\\order_page",
  "project_name": "外卖订餐多规格选购原型",
  "description": "包含规格弹窗与左右联动列表，已适配手机端布局"
})
```

Agent 将在聊天窗口中直接回复给您点击直达的局域网链接：
> `http://100.64.0.88:8088/sites/p-20260928-xxx/index.html`

## 4. 独立命令行使用 (CLI)

除 Agent 自动调用外，您也可以自己在终端中手动上传：

```powershell
# 1. 上传一个目录
python d:\project\static_deploy\client-mcp\deploy_cli.py --path "D:\project\demo" --name "支付结算原型" --desc "新增优惠券选择交互"

# 2. 上传单张设计图
python d:\project\static_deploy\client-mcp\deploy_cli.py --path "D:\images\banner.png" --name "主视觉设计稿" --desc "4K分辨率设计图"

# 3. 查看当前所有项目
python d:\project\static_deploy\client-mcp\deploy_cli.py --list
```
