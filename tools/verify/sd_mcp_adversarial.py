#!/usr/bin/env python3
"""派发方独立对抗验收：超大输入 / zip slip（API 路径）/ 并发原子写 / 残留清理。
用法: python3 sd_mcp_adversarial.py [base_url]
"""
import concurrent.futures as cf
import io
import json
import os
import sys
import urllib.error
import urllib.request
import urllib.parse
import uuid
import zipfile

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8088").rstrip("/")
DATA = "/data/static-deploy"
FAILED = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (" | " + str(detail) if detail else ""))
    if not cond:
        FAILED.append(name)


def post_raw(path, data, headers=None, timeout=180):
    h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    h.update(headers or {})
    req = urllib.request.Request(BASE + path, data=data, headers=h, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return -1, str(e)


def rpc(method, params=None, mid=1):
    st, body = post_raw("/mcp", json.dumps({"jsonrpc": "2.0", "id": mid, "method": method, "params": params}).encode())
    try:
        return st, json.loads(body)
    except Exception:
        return st, {"_raw": body}


def call(name, args):
    st, j = rpc("tools/call", {"name": name, "arguments": args})
    res = (j or {}).get("result") or {}
    text = "".join(c.get("text", "") for c in res.get("content", []))
    return st, j, text, bool(res.get("isError")), res.get("structuredContent")


def sites_count():
    try:
        return len(os.listdir(os.path.join(DATA, "sites")))
    except Exception:
        return -1


def meta_projects():
    with open(os.path.join(DATA, "meta", "projects.json"), encoding="utf-8") as f:
        return json.load(f)


print("== A. 超大输入 ==")
before = sites_count()
big = "x" * (11 * 1024 * 1024)
st, j, text, err, _ = call("deploy_static_project", {
    "project_name": "BIG" + uuid.uuid4().hex[:6], "description": "超大测试",
    "files": {"a.html": "<html>a</html>", "b.txt": big, "c.txt": big},
})
check("总内容 >20MB 被拒", err, text[:120])
check("超大输入未留下半成品目录", sites_count() == before, "sites: %s -> %s" % (before, sites_count()))

st, j, text, err, _ = call("deploy_static_project", {
    "project_name": "BIG2" + uuid.uuid4().hex[:6], "description": "单文件超大",
    "html": big + big,
})
check("单文件 >20MB 被拒", err, text[:120])

print("== B. zip slip（/api/deploy 路径）==")
mark = uuid.uuid4().hex[:8]
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w") as z:
    z.writestr("index.html", "<html>zip slip test</html>")
    z.writestr("../evil_%s.txt" % mark, "pwned")
    z.writestr("../../evil2_%s.txt" % mark, "pwned")
    z.writestr("/tmp/evil3_%s.txt" % mark, "pwned")
zb = buf.getvalue()
st, body = post_raw("/api/deploy", zb, {
    "X-Project-Name": "ZIPSLIP%s" % mark, "X-Project-Desc": "zip slip",
    "X-Project-Type": "html", "X-Entry-File": "index.html",
    "Content-Type": "application/octet-stream",
})
check("zip 上传返回 200", st == 200, (st, body[:120]))
leaked = [p for p in ("%s/meta/evil_%s.txt" % (DATA, mark), "%s/evil_%s.txt" % (DATA, mark),
                      "/data/evil_%s.txt" % mark, "/tmp/evil3_%s.txt" % mark, "/data/evil2_%s.txt" % mark)
          if os.path.exists(p)]
check("zip slip 未越界落文件", not leaked, leaked)

print("== C. 并发原子写 ==")
N = 5
m = uuid.uuid4().hex[:6]
def deploy(i):
    return call("deploy_static_project", {
        "project_name": "CONC%d-%s" % (i, m), "description": "并发",
        "html": "<html>conc %d %s</html>" % (i, m)})
with cf.ThreadPoolExecutor(max_workers=N) as ex:
    results = list(ex.map(deploy, range(N)))
oks = [r for r in results if not r[3]]
check("5 并发全部成功", len(oks) == N, "%d/%d" % (len(oks), N))
try:
    projects = meta_projects()
    check("projects.json 可解析", isinstance(projects, list), len(projects))
except Exception as e:
    projects = []
    check("projects.json 可解析", False, e)
ids = [p["id"] for p in projects if p.get("name", "").startswith("CONC")]
check("5 条并发记录齐备(无截断)", len(set(ids)) == N, len(set(ids)))
try:
    with open(os.path.join(DATA, "meta", "projects.json.tmp"), encoding="utf-8") as f:
        f.read()
    check("无残留 .tmp 文件", False, "projects.json.tmp 存在")
except FileNotFoundError:
    check("无残留 .tmp 文件", True)

print("== D. 入口解析（zip 顶层目录，回归我发现的 404 缺陷）==")
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w") as z:
    z.writestr("demo/index.html", "<html>NESTED-%s</html>" % m)
    z.writestr("demo/app.css", "body{}")
st, body = post_raw("/api/deploy", buf.getvalue(), {
    "X-Project-Name": "NEST%s" % m, "X-Project-Desc": urllib.parse.quote("顶层目录"),
    "X-Project-Type": "html", "X-Entry-File": "index.html",
    "Content-Type": "application/octet-stream"})
ok = False
detail = body[:160]
try:
    j = json.loads(body)
    url = BASE + j["url"]
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=20) as r:
        content = r.read().decode()
        ok = r.status == 200 and "NESTED-" in content
        detail = "%s -> %s" % (j["url"], r.status)
except Exception as e:
    detail = "%s | %s" % (body[:120], e)
check("顶层目录 zip 入口可访问 200", ok, detail)

print("== E. 清理测试数据 ==")
projects = meta_projects()
removed = 0
for p in list(projects):
    if p.get("name", "").startswith(("BIG", "ZIPSLIP", "CONC", "NEST", "SDCHK", "RAWCHK", "SDMCP")):
        req = urllib.request.Request(BASE + "/api/projects/" + p["id"], method="DELETE")
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                if r.status == 200:
                    removed += 1
        except Exception as e:
            print("  delete failed", p["id"], e)
print("已清理测试项目 %d 个" % removed)
left = meta_projects()
print("剩余项目:", [(p.get("name"), p.get("id")) for p in left])

print("")
print("RESULT: " + ("ALL PASS" if not FAILED else "FAILED: " + ", ".join(FAILED)))
sys.exit(1 if FAILED else 0)
