#!/usr/bin/env python3
"""独立验收：用真实 MCP 客户端 SDK 直连远程端点，走完整握手 -> 工具列表 -> 部署 -> 取回链接。

用法: python3 sd_mcp_client_check.py [base_url]   # 默认 http://127.0.0.1:8088
"""
import asyncio
import json
import sys
import uuid

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8088").rstrip("/")
MARK = "SDCHK" + uuid.uuid4().hex[:6]
FAILED = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (" | " + str(detail) if detail else ""))
    if not cond:
        FAILED.append(name)


def text_of(result):
    return "".join(c.text for c in result.content if getattr(c, "type", "") == "text")


async def main():
    url = BASE + "/mcp"
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, read=180.0)) as http:
        async with streamable_http_client(url, http_client=http) as (read, write):
            async with ClientSession(read, write) as s:
                init = await s.initialize()
                check("initialize", init.server_info.name == "static-deploy", init.server_info)
                check("protocolVersion", bool(init.protocol_version), init.protocol_version)

                tools = await s.list_tools()
                names = sorted(t.name for t in tools.tools)
                check("tools/list 三工具", names == ["deploy_static_project", "list_projects", "upload_image"], names)

                # 1) html 单文件简写
                r = await s.call_tool("deploy_static_project", {
                    "project_name": "SDMCP单文件" + MARK,
                    "description": "独立验收 harness 创建",
                    "html": "<!doctype html><html><head><meta charset=utf-8><title>%s</title></head><body>%s</body></html>" % (MARK, MARK),
                })
                t = text_of(r)
                check("deploy html", (not r.is_error) and MARK in t, t.splitlines()[:3])
                link = next((w for w in t.split() if w.startswith("http") and "/sites/" in w), None)
                check("返回绝对链接", bool(link), link)
                if link:
                    resp = await http.get(link)
                    check("链接可访问且内容正确", resp.status_code == 200 and MARK in resp.text,
                          "status=%s len=%s" % (resp.status_code, len(resp.text)))

                # 2) files 多文件 + 子目录入口
                r2 = await s.call_tool("deploy_static_project", {
                    "project_name": "SDMCP多文件" + MARK,
                    "description": "独立验收 harness 创建",
                    "files": {"demo/index.html": "<html><body>%s-NESTED</body></html>" % MARK,
                              "demo/css/app.css": "body{color:#fff}"},
                    "entry_file": "demo/index.html",
                })
                t2 = text_of(r2)
                check("deploy files 嵌套入口", (not r2.is_error) and "demo/index.html" in t2, t2.splitlines()[:3])
                link2 = next((w for w in t2.split() if w.startswith("http") and "/sites/" in w), None)
                if link2:
                    resp2 = await http.get(link2)
                    check("嵌套入口链接 200", resp2.status_code == 200 and ("-NESTED" in resp2.text),
                          "status=%s" % resp2.status_code)

                # 3) list_projects 含刚部署项且为绝对 URL
                r3 = await s.call_tool("list_projects", {})
                t3 = text_of(r3)
                check("list_projects 含新项目", MARK in t3, t3.splitlines()[:2])
                check("list_projects 绝对 URL", ("http://" in t3 or "https://" in t3))

                # 4) 冲突参数被拒
                r4 = await s.call_tool("deploy_static_project", {
                    "project_name": "SDMCP冲突" + MARK, "description": "x",
                    "files": {"index.html": "x"}, "html": "<html></html>",
                })
                check("files+html 冲突被拒", bool(r4.is_error), text_of(r4)[:80])

    # 清理本次创建的项目（URL 形如 <base>/sites/<pid>/<entry>）
    import urllib.request as _u
    for lnk in [l for l in (link, link2) if l]:
        pid = lnk.split("/sites/")[1].split("/")[0]
        try:
            req = _u.Request(BASE + "/api/projects/" + pid, method="DELETE")
            with _u.urlopen(req, timeout=15) as r:
                check("清理 " + pid, r.status == 200, r.status)
        except Exception as e:
            print("FAIL 清理 %s | %s" % (pid, e))

    print("")
    print("RESULT: " + ("ALL PASS" if not FAILED else "FAILED: " + ", ".join(FAILED)))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
