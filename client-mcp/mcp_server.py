#!/usr/bin/env python3
"""
局域网静态原型与生图展示中心 - 本地 MCP Server (Model Context Protocol)
纯 Python 标准库编写，零外部依赖，即插即用。
供 Cursor, Claude Desktop, Antigravity 等 AI Agent 直接调用。
"""

import io
import json
import os
import sys
import urllib.parse
import urllib.request
import zipfile

# 默认配置（可通过环境变量覆盖）
SERVER_HOST = os.environ.get("PREVIEW_SERVER_HOST", "100.64.0.88")
SERVER_PORT = os.environ.get("PREVIEW_SERVER_PORT", "8088")
API_TOKEN = os.environ.get("PREVIEW_API_TOKEN", "lan-static-preview-token-2026")
API_BASE_URL = f"http://{SERVER_HOST}:{SERVER_PORT}"


def create_zip_from_path(source_path):
    """将本地路径打成 ZIP 二进制字节流"""
    source_path = os.path.abspath(source_path)
    if not os.path.exists(source_path):
        raise FileNotFoundError(f"本地路径不存在: {source_path}")

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as z:
        if os.path.isfile(source_path):
            z.write(source_path, os.path.basename(source_path))
        else:
            for root, _, files in os.walk(source_path):
                for f in files:
                    full_file = os.path.join(root, f)
                    rel_path = os.path.relpath(full_file, source_path)
                    z.write(full_file, rel_path)

    zip_buffer.seek(0)
    return zip_buffer.read()


def send_deploy_request(file_bytes, project_name, description, project_type="html", entry_file="index.html"):
    """向 88 服务器发送部署请求"""
    url = f"{API_BASE_URL}/api/deploy"
    headers = {
        "Authorization": f"Bearer {API_TOKEN}",
        "X-Project-Name": urllib.parse.quote(project_name),
        "X-Project-Desc": urllib.parse.quote(description),
        "X-Project-Type": project_type,
        "X-Entry-File": entry_file,
        "Content-Type": "application/octet-stream",
        "Content-Length": str(len(file_bytes))
    }

    req = urllib.request.Request(url, data=file_bytes, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        res_data = resp.read().decode("utf-8")
        return json.loads(res_data)


def fetch_projects():
    """获取服务器上的所有项目"""
    url = f"{API_BASE_URL}/api/projects"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {API_TOKEN}"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


# 工具定义列表 (MCP Tools Schema)
TOOLS = [
    {
        "name": "deploy_static_project",
        "description": "【核心工具】将 Windows 本地开发的静态原型（HTML/CSS/JS/图片文件夹或单HTML文件）打包上传至局域网 88 服务器（100.64.0.88），并返回可在手机端直接打开的局域网在线预览链接与二维码访问地址。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "source_path": {
                    "type": "string",
                    "description": "本地原型文件或目录的绝对路径，例如: D:\\project\\cart_demo 或 D:\\project\\demo\\index.html"
                },
                "project_name": {
                    "type": "string",
                    "description": "项目的中文名称，例如: '生鲜电商购物车移动端原型'"
                },
                "description": {
                    "type": "string",
                    "description": "项目的中文功能描述，例如: '包含优惠券抵扣交互与支付确认弹窗原型，已适配手机视口'"
                },
                "entry_file": {
                    "type": "string",
                    "description": "入口文件名，默认为 index.html",
                    "default": "index.html"
                }
            },
            "required": ["source_path", "project_name", "description"]
        }
    },
    {
        "name": "upload_image",
        "description": "将 Windows 本地生成的 AI 概念图/原型设计图上传至局域网 88 服务器，生成移动端可随时全屏手势阅览的直达链接。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "image_path": {
                    "type": "string",
                    "description": "本地图片的绝对路径，例如: D:\\images\\concept.png"
                },
                "project_name": {
                    "type": "string",
                    "description": "图片的中文标题，例如: '赛博朋克咖啡馆视觉概念图'"
                },
                "description": {
                    "type": "string",
                    "description": "图片的中文描述，例如: '由 Agent 调参生成的 4K 概念视觉海报'"
                }
            },
            "required": ["image_path", "project_name", "description"]
        }
    },
    {
        "name": "list_projects",
        "description": "查询局域网 88 服务器上最近已部署的所有静态原型与效果图列表。",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    }
]


def handle_tool_call(name, args):
    """执行具体的 MCP Tool 操作"""
    if name == "deploy_static_project":
        source_path = args.get("source_path")
        project_name = args.get("project_name")
        description = args.get("description")
        entry_file = args.get("entry_file", "index.html")

        if not os.path.exists(source_path):
            return {"error": f"找不到本地路径: {source_path}"}

        # 打包上传
        zip_bytes = create_zip_from_path(source_path)
        res = send_deploy_request(zip_bytes, project_name, description, project_type="html", entry_file=entry_file)

        full_preview_url = f"{API_BASE_URL}{res['url']}"
        portal_url = f"{API_BASE_URL}/"

        reply_text = (
            f"已成功将静态原型部署至 88 服务器！\n\n"
            f"项目名称：{project_name}\n"
            f"手机端在线预览地址：{full_preview_url}\n"
            f"总览控制台地址：{portal_url}\n\n"
            f"（只要手机处于局域网 Wi-Fi 下，点击上方链接即可在手机上秒开体验该原型）"
        )
        return {"content": [{"type": "text", "text": reply_text}], "url": full_preview_url}

    elif name == "upload_image":
        image_path = args.get("image_path")
        project_name = args.get("project_name")
        description = args.get("description")

        if not os.path.exists(image_path):
            return {"error": f"找不到本地图片: {image_path}"}

        with open(image_path, "rb") as f:
            img_bytes = f.read()

        filename = os.path.basename(image_path)
        res = send_deploy_request(img_bytes, project_name, description, project_type="image", entry_file=filename)

        full_preview_url = f"{API_BASE_URL}{res['url']}"
        reply_text = (
            f"设计图已成功发布至 88 服务器！\n\n"
            f"图片名称：{project_name}\n"
            f"手机端直达链接：{full_preview_url}\n"
            f"总览控制台地址：{API_BASE_URL}/"
        )
        return {"content": [{"type": "text", "text": reply_text}], "url": full_preview_url}

    elif name == "list_projects":
        projects = fetch_projects()
        if not projects:
            return {"content": [{"type": "text", "text": "服务器上当前暂无已部署项目。"}]}

        lines = ["局域网 88 服务器近期项目列表：\n"]
        for p in projects[:10]:
            p_url = f"{API_BASE_URL}{p['url']}"
            lines.append(f"- 【{p.get('name', '未命名')}】 ({p.get('created_at', '')})")
            lines.append(f"  说明: {p.get('description', '无')}")
            lines.append(f"  直达链接: {p_url}\n")
        return {"content": [{"type": "text", "text": "\n".join(lines)}]}

    else:
        return {"error": f"未知的工具名称: {name}"}


def main():
    """MCP Stdio 协议处理循环 (JSON-RPC 2.0)"""
    sys.stderr.write("[MCP Server] 静态原型部署服务已就绪 (Stdio 模式)\n")
    sys.stderr.flush()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            req = json.loads(line)
        except Exception:
            continue

        method = req.get("method")
        msg_id = req.get("id")

        if method == "initialize":
            resp = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "tools": {}
                    },
                    "serverInfo": {
                        "name": "static-preview-mcp",
                        "version": "1.0.0"
                    }
                }
            }
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()

        elif method == "notifications/initialized":
            # 客户端握手完成通知，无需回复
            continue

        elif method == "tools/list":
            resp = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "tools": TOOLS
                }
            }
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()

        elif method == "tools/call":
            params = req.get("params", {})
            tool_name = params.get("name")
            tool_args = params.get("arguments", {})

            try:
                result = handle_tool_call(tool_name, tool_args)
                resp = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": result
                }
            except Exception as e:
                resp = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {
                        "code": -32000,
                        "message": str(e)
                    }
                }
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()

        elif method == "ping":
            resp = {"jsonrpc": "2.0", "id": msg_id, "result": {}}
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
