#!/usr/bin/env python3
"""
局域网静态原型与生图展示中心 - 命令行部署工具 (CLI)
可脱离 AI Agent 单独运行，用于在本地终端快速上传原型或图片到 88 服务器。
"""

import argparse
import os
import sys
from mcp_server import create_zip_from_path, send_deploy_request, API_BASE_URL, fetch_projects

def main():
    parser = argparse.ArgumentParser(description="局域网静态原型与生图一键部署工具")
    parser.add_argument("--path", "-p", required=False, help="本地待部署的目录、HTML文件或图片路径")
    parser.add_argument("--name", "-n", required=False, help="中文项目名称")
    parser.add_argument("--desc", "-d", default="手动上传部署", help="中文项目描述")
    parser.add_argument("--type", "-t", choices=["html", "image"], default=None, help="项目类型 (html 或 image，默认自动探测)")
    parser.add_argument("--entry", "-e", default="index.html", help="入口文件名 (默认 index.html)")
    parser.add_argument("--list", "-l", action="store_true", help="列出服务器上已有的项目")

    args = parser.parse_args()

    if args.list:
        print(f">>> 正在获取 {API_BASE_URL} 上的项目列表...")
        projects = fetch_projects()
        if not projects:
            print("服务器上暂无项目。")
            return
        print(f"\n共 {len(projects)} 个项目：\n" + "-" * 60)
        for p in projects:
            print(f"[{p.get('type', 'html').upper()}] {p.get('name')}")
            print(f"  时间: {p.get('created_at')}  ID: {p.get('id')}")
            print(f"  说明: {p.get('description')}")
            print(f"  链接: {API_BASE_URL}{p.get('url')}\n")
        return

    if not args.path or not args.name:
        parser.error("上传时必须指定 --path (-p) 与 --name (-n) 参数")

    target_path = os.path.abspath(args.path)
    if not os.path.exists(target_path):
        print(f"错误: 找不到目标路径 {target_path}", file=sys.stderr)
        sys.exit(1)

    # 自动探测类型
    p_type = args.type
    if not p_type:
        ext = os.path.splitext(target_path)[1].lower()
        if ext in [".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"]:
            p_type = "image"
        else:
            p_type = "html"

    print(f">>> 正在处理: {target_path}")
    print(f">>> 项目名称: {args.name}")
    print(f">>> 项目类型: {p_type}")

    if p_type == "image":
        with open(target_path, "rb") as f:
            file_bytes = f.read()
        entry_file = os.path.basename(target_path)
    else:
        file_bytes = create_zip_from_path(target_path)
        entry_file = args.entry

    print(f">>> 正在发送至 88 服务器 ({API_BASE_URL})...")
    res = send_deploy_request(file_bytes, args.name, args.desc, project_type=p_type, entry_file=entry_file)

    full_url = f"{API_BASE_URL}{res['url']}"
    print("\n" + "=" * 60)
    print("部署成功！")
    print(f"项目名称: {res['name']}")
    print(f"手机预览链接: {full_url}")
    print(f"总览控制台:   {API_BASE_URL}/")
    print("=" * 60 + "\n")

if __name__ == "__main__":
    main()
