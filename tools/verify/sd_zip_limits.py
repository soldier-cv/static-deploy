#!/usr/bin/env python3
"""解压三道上限、超限回滚、以及 MCP 通道分流文案的对抗验收。

用法: python3 tools/verify/sd_zip_limits.py [base_url]
默认 http://127.0.0.1:8088

会构造高压缩比样本，并短暂写入最多约 2GB 到 /data/static-deploy/sites，结束时删除。
"""
import base64
import io
import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
import zipfile

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8088").rstrip("/")
SITES = "/data/static-deploy/sites"
META = "/data/static-deploy/meta/projects.json"
MB = 1024 * 1024
GB = 1024 * 1024 * 1024
SINGLE = 256 * MB
TOTAL = 2 * GB
FILE_CAP = 10000
BODY_CAP = 100 * MB
FAILED = []
CREATED = []


def check(name, cond, detail=""):
    line = ("PASS " if cond else "FAIL ") + name
    if detail:
        line += " | " + str(detail)
    print(line, flush=True)
    if not cond:
        FAILED.append(name)
    return cond


def site_ids():
    try:
        return set(os.listdir(SITES))
    except OSError:
        return set()


def sites_bytes():
    out = subprocess.check_output(["du", "-sb", SITES], text=True)
    return int(out.split()[0])


def post_raw(path, data, headers=None, timeout=180):
    hdrs = {}
    hdrs.update(headers or {})
    req = urllib.request.Request(BASE + path, data=data, headers=hdrs, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except Exception as exc:
        return -1, str(exc)


def rpc(method, params=None, mid=1, timeout=180):
    payload = {"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}}
    status, body = post_raw(
        "/mcp",
        json.dumps(payload).encode("utf-8"),
        {
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        timeout=timeout,
    )
    try:
        return status, json.loads(body)
    except Exception:
        return status, {"_raw": body}


def call_tool(name, args, timeout=180):
    status, parsed = rpc(
        "tools/call",
        {"name": name, "arguments": args},
        mid=name,
        timeout=timeout,
    )
    result = (parsed or {}).get("result") or {}
    text = "".join(part.get("text", "") for part in result.get("content", []))
    return status, parsed, text, bool(result.get("isError"))


def loads(body):
    try:
        return json.loads(body)
    except Exception:
        return None


def deploy_bytes(data, name, desc, entry="index.html", timeout=300):
    status, body = post_raw(
        "/api/deploy",
        data,
        {
            "Content-Type": "application/octet-stream",
            "X-Project-Name": name,
            "X-Project-Desc": desc,
            "X-Project-Type": "html",
            "X-Entry-File": entry,
        },
        timeout=timeout,
    )
    return status, body, loads(body)


def delete_project(project_id):
    req = urllib.request.Request(BASE + "/api/projects/" + project_id, method="DELETE")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except Exception:
        return -1


def remember(parsed):
    if isinstance(parsed, dict) and parsed.get("project_id"):
        CREATED.append(parsed["project_id"])


def no_residue(label, before_ids, before_bytes, slack=8 * MB):
    extra = site_ids() - before_ids
    delta = sites_bytes() - before_bytes
    return check(
        label,
        not extra and delta < slack,
        "extra=%s delta=%s" % (sorted(extra), delta),
    )


def assert_limit(label, status, parsed, body, limit_bytes=None, limit_count=None, needle=""):
    advice = (parsed or {}).get("advice") if isinstance(parsed, dict) else ""
    error = (parsed or {}).get("error") if isinstance(parsed, dict) else ""
    ok = status == 400 and isinstance(parsed, dict)
    ok = ok and isinstance(error, str) and "上限" in error
    ok = ok and isinstance(advice, str) and advice.strip() != ""
    ok = ok and ("/api/deploy" in advice or "POST /api/deploy" in error)
    if limit_bytes is not None:
        ok = ok and parsed.get("limit_bytes") == limit_bytes
    if limit_count is not None:
        ok = ok and parsed.get("limit_count") == limit_count
    if needle:
        ok = ok and needle in error
    return check(label, ok, "status=%s body=%s" % (status, (body or "")[:500]))


def project_tree_size(project_id):
    root = os.path.join(SITES, project_id)
    total = 0
    files = 0
    links = []
    for dirpath, _dirs, names in os.walk(root, followlinks=False):
        for name in names:
            path = os.path.join(dirpath, name)
            if os.path.islink(path):
                links.append(path)
                continue
            if os.path.isfile(path):
                files += 1
                total += os.path.getsize(path)
    return total, files, links


def http_range_ok(url, prefix):
    req = urllib.request.Request(url, headers={"Range": "bytes=0-%d" % (len(prefix) - 1)})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
            return resp.status in (200, 206) and data.startswith(prefix), resp.status, data[:40]
    except Exception as exc:
        return False, -1, str(exc)


def add_repeated(archive, name, size, fill=b"A"):
    block = fill * (MB // len(fill))
    with archive.open(name, "w") as dest:
        left = size
        while left:
            n = min(left, len(block))
            dest.write(block[:n])
            left -= n


def new_zip(path):
    return zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1)


def zip_member_size(path, name):
    with zipfile.ZipFile(path) as archive:
        info = archive.getinfo(name)
        return info.file_size, info.compress_size


def run_unit():
    print("== 0. 容器内流式计数（小阈值，证明越限块不写并回滚）==", flush=True)
    script = r"""
import io, os, shutil, zipfile
import receiver

for name in os.listdir(receiver.SITES_DIR):
    if name.startswith("p-unit-"):
        shutil.rmtree(os.path.join(receiver.SITES_DIR, name), ignore_errors=True)

receiver.ZIP_READ_CHUNK = 400
receiver.ZIP_MAX_SINGLE_BYTES = 1000
receiver.ZIP_MAX_TOTAL_BYTES = 2500
receiver.ZIP_MAX_FILE_COUNT = 3

src = io.BytesIO(b"A" * 1200)
path = "/tmp/sd-zip-copy.bin"
with open(path, "wb") as out:
    try:
        receiver._copy_with_limits(src, out, 0)
        raise SystemExit("copy should have failed")
    except receiver.ZipLimitError as exc:
        err = exc
size = os.path.getsize(path)
os.unlink(path)
assert size == 800, size
assert err.limit_bytes == 1000 and err.advice and "上限" in err.message
print("UNIT copy stops before overflowing chunk bytes=%s" % size)

saved_total = receiver.ZIP_MAX_TOTAL_BYTES
saved_single = receiver.ZIP_MAX_SINGLE_BYTES
receiver.ZIP_MAX_TOTAL_BYTES = 1000
receiver.ZIP_MAX_SINGLE_BYTES = 5000
src = io.BytesIO(b"B" * 400)
path = "/tmp/sd-zip-total.bin"
with open(path, "wb") as out:
    try:
        receiver._copy_with_limits(src, out, 900)
        raise SystemExit("total should have failed")
    except receiver.ZipLimitError as exc:
        err = exc
size = os.path.getsize(path)
os.unlink(path)
receiver.ZIP_MAX_TOTAL_BYTES = saved_total
receiver.ZIP_MAX_SINGLE_BYTES = saved_single
assert size == 0, size
assert err.limit_bytes == 1000 and "总体积" in err.message
print("UNIT total limit writes nothing when the first chunk would cross bytes=%s" % size)

def once(label, payload, expect_ok):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        if isinstance(payload, list):
            for name, data in payload:
                zf.writestr(name, data)
        else:
            zf.writestr("index.html", payload)
    pid = "p-unit-" + label
    pdir = os.path.join(receiver.SITES_DIR, pid)
    os.makedirs(pdir, exist_ok=True)
    try:
        receiver.extract_zip_safely(buf.getvalue(), pdir)
        if not expect_ok:
            raise SystemExit(label + " should fail")
        print("UNIT %s kept bytes=%s" % (label, os.path.getsize(os.path.join(pdir, "index.html"))))
    except receiver.ZipLimitError as exc:
        if expect_ok:
            raise
        print("UNIT %s rejected limit_bytes=%s limit_count=%s advice=%s" % (
            label, exc.limit_bytes, exc.limit_count, exc.advice[:60]))
    finally:
        if expect_ok:
            shutil.rmtree(pdir, ignore_errors=True)
        if os.path.exists(pdir):
            raise SystemExit(label + " residue " + pdir)
        print("UNIT %s dir gone" % label)

once("exact", b"B" * 1000, True)
once("plus", b"C" * 1001, False)
once("count_ok", [("index.html", b"ok"), ("a.txt", b""), ("b.txt", b"")], True)
once("count_over", [("index.html", b"ok"), ("a.txt", b""), ("b.txt", b""), ("c.txt", b"")], False)
print("UNIT_OK")
"""
    proc = subprocess.run(
        ["docker", "exec", "-w", "/app", "-e", "PYTHONPATH=/app", "static-deploy-api", "python3", "-c", script],
        capture_output=True,
        text=True,
        timeout=60,
    )
    text = (proc.stdout or "") + (proc.stderr or "")
    print(text, flush=True)
    check("容器内流式计数与回滚", proc.returncode == 0 and "UNIT_OK" in text, "rc=%s" % proc.returncode)


def run_descriptions():
    print("== 1. initialize / tools/list 通道分流描述 ==", flush=True)
    status, parsed = rpc(
        "initialize",
        {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "sd-zip-limits", "version": "1"},
        },
    )
    instructions = ((parsed or {}).get("result") or {}).get("instructions") or ""
    check(
        "initialize 指引含阈值与 HTTP 直传",
        status == 200 and "20KB" in instructions and "200KB" in instructions and "/api/deploy" in instructions and "3MB" in instructions,
        instructions[:240],
    )
    status, parsed = rpc("tools/list")
    tools = {}
    for tool in ((parsed or {}).get("result") or {}).get("tools") or []:
        tools[tool.get("name")] = tool
    deploy = (tools.get("deploy_static_project") or {}).get("description") or ""
    image = (tools.get("upload_image") or {}).get("description") or ""
    listing = (tools.get("list_projects") or {}).get("description") or ""
    check(
        "deploy_static_project 描述含规模阈值与替代路径",
        all(part in deploy for part in ("20KB", "200KB", "20MB", "100MB", "/api/deploy", "X-Project-Type: html")),
        deploy[:300],
    )
    check(
        "upload_image 描述含规模阈值与替代路径",
        all(part in image for part in ("3MB", "20MB", "100MB", "/api/deploy", "X-Project-Type: image")),
        image[:300],
    )
    check(
        "list_projects 描述含分流",
        all(part in listing for part in ("20KB", "200KB", "3MB", "/api/deploy", "100MB")),
        listing[:300],
    )


def run_small_channels(mark):
    print("== 2. 正常小包：HTTP 与 MCP ==", flush=True)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("index.html", "<html>HTTP-SMALL-%s</html>" % mark)
        archive.writestr("app.css", "body{color:#222}")
    before = site_ids()
    status, body, parsed = deploy_bytes(buf.getvalue(), "ZLIM-http-%s" % mark, "http small")
    remember(parsed)
    url = ""
    if isinstance(parsed, dict) and parsed.get("abs_url"):
        url = parsed["abs_url"]
    page_ok = False
    if url:
        try:
            with urllib.request.urlopen(url, timeout=20) as resp:
                page_ok = resp.status == 200 and ("HTTP-SMALL-%s" % mark).encode() in resp.read()
        except Exception as exc:
            page_ok = False
            url = "%s %s" % (url, exc)
    check("HTTP 小 zip 部署成功且可访问", status == 200 and page_ok, "status=%s url=%s" % (status, url))

    _status, _parsed, text, is_error = call_tool(
        "deploy_static_project",
        {
            "project_name": "ZLIM-mcp-%s" % mark,
            "description": "mcp small",
            "html": "<html>MCP-SMALL-%s</html>" % mark,
        },
    )
    link = ""
    for line in text.splitlines():
        if "http://" in line or "https://" in line:
            link = line.split("：", 1)[-1].strip()
            if "http" in link:
                link = link[link.find("http"):]
                break
    page_ok = False
    if link.startswith("http"):
        project_id = link.split("/sites/")[1].split("/")[0]
        CREATED.append(project_id)
        try:
            with urllib.request.urlopen(link, timeout=20) as resp:
                page_ok = resp.status == 200 and ("MCP-SMALL-%s" % mark).encode() in resp.read()
        except Exception as exc:
            page_ok = False
            link = "%s %s" % (link, exc)
    check("MCP 小 HTML 部署成功且可访问", (not is_error) and page_ok, text[:180])

    png = base64.b64encode(
        base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+X89QAAAAASUVORK5CYII="
        )
    ).decode()
    _status, _parsed, text, is_error = call_tool(
        "upload_image",
        {
            "project_name": "ZLIM-img-%s" % mark,
            "description": "mcp image",
            "filename": "dot.png",
            "image_base64": png,
        },
    )
    if "/sites/" in text:
        CREATED.append(text.split("/sites/")[1].split("/")[0])
    check("MCP 小图片上传成功", (not is_error) and "上传成功" in text, text[:180])
    check("小包之后站点集合只增加了本次项目", len(site_ids() - before) >= 1)


def run_guidance(mark):
    print("== 3. 超限文案指向 HTTP 直传 ==", flush=True)
    before_ids = site_ids()
    before_bytes = sites_bytes()
    big = "x" * (21 * MB)
    _status, _parsed, text, is_error = call_tool(
        "deploy_static_project",
        {
            "project_name": "ZLIM-bigtext-%s" % mark,
            "description": "over mcp content",
            "html": big,
        },
        timeout=180,
    )
    check(
        "MCP 文本超 20MB 的错误含上限与 HTTP 做法",
        is_error and "20971520" in text and "/api/deploy" in text and "上限" in text,
        text[:300],
    )
    raw = b"\x89PNG\r\n\x1a\n" + (b"\0" * (20 * MB + 1 - 8))
    encoded = base64.b64encode(raw).decode("ascii")
    _status, _parsed, text, is_error = call_tool(
        "upload_image",
        {
            "project_name": "ZLIM-bigimg-%s" % mark,
            "description": "over image",
            "filename": "big.png",
            "image_base64": encoded,
        },
        timeout=180,
    )
    check(
        "MCP 图片超 20MB 的错误含上限与 HTTP 做法",
        is_error and "20971520" in text and "/api/deploy" in text and "X-Project-Type: image" in text,
        text[:300],
    )
    status, body = post_over_body("/api/deploy", BODY_CAP + 1)
    parsed = loads(body)
    check(
        "HTTP 请求体超 100MB 返回 413 且含上限与做法",
        status == 413
        and isinstance(parsed, dict)
        and parsed.get("limit_bytes") == BODY_CAP
        and "104857600" in (parsed.get("error") or "")
        and (parsed.get("advice") or "").strip() != "",
        "status=%s body=%s" % (status, (body or "")[:400]),
    )
    no_residue("MCP 与 HTTP 超限未留下目录", before_ids, before_bytes)


def post_over_body(path, length):
    host_port = BASE.split("://", 1)[-1]
    host, port_text = host_port.rsplit(":", 1)
    sock = socket.create_connection((host, int(port_text)), timeout=30)
    try:
        header = (
            "POST %s HTTP/1.1\r\n"
            "Host: %s\r\n"
            "Content-Type: application/octet-stream\r\n"
            "Content-Length: %d\r\n"
            "Connection: close\r\n"
            "\r\n" % (path, host_port, length)
        ).encode("ascii")
        sock.sendall(header)
        chunk = b"\0" * MB
        left = length
        try:
            while left:
                n = min(left, len(chunk))
                sock.sendall(chunk[:n])
                left -= n
            sock.shutdown(socket.SHUT_WR)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        data = b""
        sock.settimeout(20)
        while True:
            try:
                part = sock.recv(65536)
            except socket.timeout:
                break
            if not part:
                break
            data += part
            if b"\r\n\r\n" in data and len(data) > 200:
                break
    finally:
        sock.close()
    head, _, rest = data.partition(b"\r\n\r\n")
    status = -1
    try:
        status = int(head.split()[1])
    except Exception:
        status = -1
    return status, rest.decode("utf-8", "replace")


def reject_case(label, blob, limit_bytes=None, limit_count=None, needle=""):
    before_ids = site_ids()
    before_bytes = sites_bytes()
    status, body, parsed = deploy_bytes(blob, "ZLIM-%s" % label, label)
    remember(parsed)
    assert_limit(label + " 被拒绝且 JSON 含上限与做法", status, parsed, body, limit_bytes, limit_count, needle)
    no_residue(label + " 无残留目录且占用未异常增长", before_ids, before_bytes)


def accept_case(label, blob, expect_bytes, expect_files, prefix, timeout=300):
    before_ids = site_ids()
    status, body, parsed = deploy_bytes(blob, "ZLIM-%s" % label, label, timeout=timeout)
    remember(parsed)
    project_id = (parsed or {}).get("project_id") if isinstance(parsed, dict) else None
    size = files = None
    links = []
    ranged = (False, -1, b"")
    if project_id:
        size, files, links = project_tree_size(project_id)
        url = (parsed or {}).get("abs_url") or ""
        if url:
            ranged = http_range_ok(url, prefix)
    ok = (
        status == 200
        and project_id
        and project_id not in before_ids
        and size == expect_bytes
        and files == expect_files
        and not links
        and ranged[0]
    )
    check(
        label + " 成功",
        ok,
        "status=%s id=%s bytes=%s files=%s range=%s body=%s"
        % (status, project_id, size, files, ranged[:2], (body or "")[:180]),
    )
    if project_id:
        delete_project(project_id)
    return project_id


def build_repeated_zip(path, members):
    started = time.time()
    with new_zip(path) as archive:
        for name, size, fill in members:
            if size == 0:
                archive.writestr(name, b"")
            else:
                add_repeated(archive, name, size, fill)
    elapsed = time.time() - started
    file_size = os.path.getsize(path)
    print("built %s zip_bytes=%s seconds=%.1f" % (path, file_size, elapsed), flush=True)
    return file_size


def run_zip_attacks(workdir, mark):
    print("== 4. zip 炸弹 / 单文件 / 文件数 / 正常包 / 路径 / 符号链接 ==", flush=True)
    bomb = os.path.join(workdir, "bomb.zip")
    with new_zip(bomb) as archive:
        archive.writestr("index.html", "<html>bomb</html>")
        add_repeated(archive, "payload.bin", 500 * MB, b"Z")
    uncompressed, compressed = zip_member_size(bomb, "payload.bin")
    check(
        "炸弹样本解压声明 500MB 且压缩后小于 4MB",
        uncompressed == 500 * MB and compressed < 4 * MB,
        "file=%s compress=%s" % (uncompressed, compressed),
    )
    reject_case("bomb", open(bomb, "rb").read(), limit_bytes=SINGLE, needle="单个文件")

    single_over = os.path.join(workdir, "single300.zip")
    with new_zip(single_over) as archive:
        add_repeated(archive, "index.html", 300 * MB, b"Q")
    reject_case("single300", open(single_over, "rb").read(), limit_bytes=SINGLE, needle="单个文件")

    single_exact = os.path.join(workdir, "single256.zip")
    with new_zip(single_exact) as archive:
        add_repeated(archive, "index.html", SINGLE, b"E")
    accept_case("single-exact-256MB", open(single_exact, "rb").read(), SINGLE, 1, b"E")

    single_plus = os.path.join(workdir, "single256plus.zip")
    with new_zip(single_plus) as archive:
        add_repeated(archive, "index.html", SINGLE + 1, b"P")
    reject_case("single-256MB-plus-1", open(single_plus, "rb").read(), limit_bytes=SINGLE, needle="单个文件")

    count_ok = os.path.join(workdir, "count10000.zip")
    with zipfile.ZipFile(count_ok, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("index.html", "<html>COUNT-OK-%s</html>" % mark)
        for i in range(FILE_CAP - 1):
            archive.writestr("f-%05d.txt" % i, b"")
    accept_case(
        "count-exact-10000",
        open(count_ok, "rb").read(),
        len(("<html>COUNT-OK-%s</html>" % mark).encode()),
        FILE_CAP,
        ("<html>COUNT-OK-%s</html>" % mark).encode(),
    )

    count_over = os.path.join(workdir, "count10001.zip")
    with zipfile.ZipFile(count_over, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("index.html", "<html>COUNT-NO</html>")
        for i in range(FILE_CAP):
            archive.writestr("g-%05d.txt" % i, b"")
    reject_case("count-10001", open(count_over, "rb").read(), limit_count=FILE_CAP, needle="文件数")

    normal = io.BytesIO()
    with zipfile.ZipFile(normal, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        marker = ("<html>NORMAL-%s</html>" % mark).encode()
        archive.writestr("index.html", marker)
        rest = 10 * MB - len(marker)
        per = rest // 49
        extra = rest - per * 49
        for i in range(49):
            size = per + (extra if i == 0 else 0)
            archive.writestr("assets/a-%02d.bin" % i, b"N" * size)
    blob = normal.getvalue()
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        total = sum(info.file_size for info in archive.infolist())
        count = len(archive.infolist())
    check("正常包样本为 50 个文件且总量 10MB", count == 50 and total == 10 * MB, "count=%s total=%s" % (count, total))
    accept_case("normal-50x10MB", blob, 10 * MB, 50, marker)

    slip = io.BytesIO()
    with zipfile.ZipFile(slip, "w") as archive:
        archive.writestr("index.html", "<html>SLIP-%s</html>" % mark)
        archive.writestr("../evil_%s.txt" % mark, "pwned")
        archive.writestr("../../evil2_%s.txt" % mark, "pwned")
        archive.writestr("/tmp/evil3_%s.txt" % mark, "pwned")
        archive.writestr("sub/../../evil4_%s.txt" % mark, "pwned")
    outside = [
        "/tmp/evil3_%s.txt" % mark,
        "/data/evil_%s.txt" % mark,
        "/data/evil2_%s.txt" % mark,
        "/data/static-deploy/evil_%s.txt" % mark,
        "/data/static-deploy/evil2_%s.txt" % mark,
        "/data/static-deploy/sites/evil_%s.txt" % mark,
        os.path.join(SITES, "evil4_%s.txt" % mark),
    ]
    status, body, parsed = deploy_bytes(slip.getvalue(), "ZLIM-slip-%s" % mark, "slip")
    remember(parsed)
    project_id = (parsed or {}).get("project_id") if isinstance(parsed, dict) else ""
    leaked = [path for path in outside if os.path.exists(path)]
    inside_evil = []
    if project_id:
        for dirpath, _dirs, names in os.walk(os.path.join(SITES, project_id)):
            for name in names:
                if name.startswith("evil"):
                    inside_evil.append(os.path.join(dirpath, name))
    check(
        "路径穿越成员被跳过且项目目录外无文件",
        status == 200 and not leaked and not inside_evil and project_id,
        "status=%s leaked=%s inside=%s body=%s" % (status, leaked, inside_evil, (body or "")[:160]),
    )

    link_zip = io.BytesIO()
    with zipfile.ZipFile(link_zip, "w") as archive:
        archive.writestr("index.html", "<html>LINK-%s</html>" % mark)
        info = zipfile.ZipInfo("escape.link")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        info.create_system = 3
        info.compress_type = zipfile.ZIP_STORED
        archive.writestr(info, "/tmp/sd-zip-link-target-%s" % mark)
    target = "/tmp/sd-zip-link-target-%s" % mark
    status, body, parsed = deploy_bytes(link_zip.getvalue(), "ZLIM-link-%s" % mark, "symlink")
    remember(parsed)
    project_id = (parsed or {}).get("project_id") if isinstance(parsed, dict) else ""
    link_path = os.path.join(SITES, project_id, "escape.link") if project_id else ""
    is_link = bool(project_id) and os.path.islink(link_path)
    exists = bool(project_id) and os.path.lexists(link_path)
    check(
        "符号链接成员被跳过",
        status == 200 and project_id and not is_link and not exists and not os.path.exists(target),
        "status=%s islink=%s exists=%s target=%s body=%s"
        % (status, is_link, exists, os.path.exists(target), (body or "")[:160]),
    )


def run_total_boundary(workdir):
    print("== 5. 解压总量边界：正好 2GB，以及 2GB+1 ==", flush=True)
    exact = os.path.join(workdir, "total2g.zip")
    members = [("index.html", SINGLE, b"T")]
    for i in range(7):
        members.append(("part-%d.bin" % i, SINGLE, b"T"))
    zip_bytes = build_repeated_zip(exact, members)
    with zipfile.ZipFile(exact) as archive:
        declared = sum(info.file_size for info in archive.infolist())
        compressed = sum(info.compress_size for info in archive.infolist())
        count = len(archive.infolist())
    check(
        "2GB 样本声明大小正好等于总量上限且压缩后可上传",
        declared == TOTAL and count == 8 and compressed < 20 * MB and zip_bytes < 20 * MB,
        "declared=%s files=%s compress=%s zip=%s" % (declared, count, compressed, zip_bytes),
    )
    plus = os.path.join(workdir, "total2g-plus.zip")
    shutil.copy(exact, plus)
    with zipfile.ZipFile(plus, "a") as archive:
        archive.writestr("extra.bin", b"X")
    with zipfile.ZipFile(plus) as archive:
        declared_plus = sum(info.file_size for info in archive.infolist())
    check("2GB+1 样本声明大小", declared_plus == TOTAL + 1, declared_plus)
    reject_case("total-2GB-plus-1", open(plus, "rb").read(), limit_bytes=TOTAL, needle="总体积")
    accept_case("total-exact-2GB", open(exact, "rb").read(), TOTAL, 8, b"T", timeout=300)


def cleanup():
    print("== 6. 清理 ==", flush=True)
    removed = 0
    ids = set(CREATED)
    try:
        with open(META, encoding="utf-8") as handle:
            projects = json.load(handle)
    except Exception as exc:
        projects = []
        print("meta read failed: %s" % exc, flush=True)
    for project in projects:
        name = str(project.get("name") or "")
        project_id = str(project.get("id") or "")
        if name.startswith("ZLIM") or project_id in ids:
            if delete_project(project_id) == 200:
                removed += 1
    for project_id in ids:
        path = os.path.join(SITES, project_id)
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
    print("已删除测试项目 %d 个" % removed, flush=True)


def wait_health():
    for i in range(30):
        try:
            with urllib.request.urlopen(BASE + "/api/health", timeout=3) as resp:
                if resp.status == 200:
                    print("health ok", flush=True)
                    return True
        except Exception as exc:
            print("health wait %s %s" % (i, exc), flush=True)
        time.sleep(1)
    return False


def main():
    if not wait_health():
        print("RESULT: FAILED: health")
        return 1
    mark = uuid.uuid4().hex[:8]
    workdir = "/tmp/sd-zip-limits-%s" % mark
    os.makedirs(workdir, exist_ok=True)
    started = time.time()
    try:
        run_unit()
        run_descriptions()
        run_small_channels(mark)
        run_guidance(mark)
        run_zip_attacks(workdir, mark)
        run_total_boundary(workdir)
    finally:
        cleanup()
        shutil.rmtree(workdir, ignore_errors=True)
        print("elapsed %.1fs" % (time.time() - started), flush=True)
    print("")
    print("RESULT: " + ("ALL PASS" if not FAILED else "FAILED: " + ", ".join(FAILED)))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
