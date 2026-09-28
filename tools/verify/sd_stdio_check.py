#!/usr/bin/env python3
"""验证「方式二」：本机 stdio 客户端脚本（走本地路径上传），用交付的脚本原样跑。
用法: python3 sd_stdio_check.py [base_host] [base_port]
"""
import json
import os
import subprocess
import sys
import uuid

HOST = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
PORT = sys.argv[2] if len(sys.argv) > 2 else "8088"
SCRIPT = "/opt/code/static-deploy/client-mcp/mcp_server.py"
MARK = "STDIO" + uuid.uuid4().hex[:6]
FAILED = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (" | " + str(detail) if detail else ""))
    if not cond:
        FAILED.append(name)


# 造一个本地原型目录（含子目录）
root = "/home/xl/tmp/coding/builds/stdio_demo"
os.makedirs(root + "/assets", exist_ok=True)
open(root + "/index.html", "w").write("<html><body>%s</body></html>" % MARK)
open(root + "/assets/app.js", "w").write("console.log('%s')" % MARK)

env = dict(os.environ, PREVIEW_SERVER_HOST=HOST, PREVIEW_SERVER_PORT=PORT, PYTHONUNBUFFERED="1")
proc = subprocess.Popen([sys.executable, SCRIPT], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE, text=True, env=env)


def send(obj):
    proc.stdin.write(json.dumps(obj) + "\n")
    proc.stdin.flush()
    line = proc.stdout.readline()
    return json.loads(line) if line.strip() else None


r = send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
check("stdio initialize", (r or {}).get("result", {}).get("serverInfo", {}).get("name") == "static-preview-mcp", r)
r = send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
names = sorted(t["name"] for t in (r or {}).get("result", {}).get("tools", []))
check("stdio tools/list", names == ["deploy_static_project", "list_projects", "upload_image"], names)

r = send({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
          "params": {"name": "deploy_static_project",
                     "arguments": {"source_path": root, "project_name": "STDIO" + MARK,
                                   "description": "本地路径上传验收"}}})
text = "".join(c.get("text", "") for c in (r or {}).get("result", {}).get("content", []))
check("stdio 部署成功（无 token）", "部署成功" in text or "/sites/" in text, text.splitlines()[:3])
import re as _re
link = (_re.search(r"https?://[^\s\u3000]+", text) or [None])[0] if _re.search(r"https?://[^\s\u3000]+", text) else None
check("stdio 返回链接", bool(link), link)
if link:
    import urllib.request
    with urllib.request.urlopen(link, timeout=20) as resp:
        body = resp.read().decode()
    check("stdio 链接 200 且内容正确", resp.status == 200 and MARK in body, resp.status)

r = send({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "list_projects", "arguments": {}}})
text = "".join(c.get("text", "") for c in (r or {}).get("result", {}).get("content", []))
check("stdio list_projects 含新项目", MARK in text, text.splitlines()[:1])

proc.stdin.close()
proc.terminate()
try:
    proc.wait(timeout=10)
except Exception:
    proc.kill()

# 清理本次创建的项目
import urllib.request as _u
for lnk in [l for l in (link,) if l]:
    pid = lnk.split("/sites/")[1].split("/")[0]
    try:
        req = _u.Request("http://%s:%s/api/projects/%s" % (HOST, PORT, pid), method="DELETE")
        with _u.urlopen(req, timeout=15) as r:
            check("清理 " + pid, r.status == 200, r.status)
    except Exception as e:
        print("FAIL 清理 %s | %s" % (pid, e))

print("")
print("RESULT: " + ("ALL PASS" if not FAILED else "FAILED: " + ", ".join(FAILED)))
sys.exit(1 if FAILED else 0)
