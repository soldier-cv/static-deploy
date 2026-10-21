#!/usr/bin/env python3
"""X-Project-Name / X-Project-Desc 解码单测。

覆盖 ASCII、UTF-8 原文（latin-1 误解码）、percent-encoding、超集字符、
混合形态、恶意输入、空值，以及 MCP 客户端 quote 一次的回归。
传入 base URL 时，再对真实 /api/deploy 做同样的检查。

用法:
  python3 tools/verify/sd_header_decode.py
  python3 tools/verify/sd_header_decode.py http://127.0.0.1:8088
"""
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile

FAILED = []
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def check(name, cond, detail=""):
    line = ("PASS " if cond else "FAIL ") + name
    if detail:
        line += " | " + str(detail)
    print(line, flush=True)
    if not cond:
        FAILED.append(name)


def load_receiver():
    os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="sd-header-decode-")
    os.environ["API_TOKEN"] = ""
    server_dir = os.path.join(ROOT, "server")
    if server_dir not in sys.path:
        sys.path.insert(0, server_dir)
    import receiver
    return receiver


def mojibake(text):
    """模拟 http.server 把 UTF-8 header 字节按 latin-1 解码。"""
    return text.encode("utf-8").decode("latin-1")


def show(receiver, title, raw, default="未命名项目"):
    once = receiver.decode_header_value(raw, default)
    twice = receiver.decode_header_value(once, default)
    print(
        "SCENE %s | in=%s out=%s twice=%s stable=%s"
        % (title, repr(raw), repr(once), repr(twice), once == twice),
        flush=True,
    )
    return once, twice


def run_unit(receiver):
    decode = receiver.decode_header_value
    name_default = "未命名项目"
    desc_default = "无描述"
    logical = "往来原型"
    forms = {
        "unicode": logical,
        "mojibake": mojibake(logical),
        "quoted": urllib.parse.quote(logical, safe="/"),
    }

    print("== 1. 纯 ASCII ==", flush=True)
    once, twice = show(receiver, "1 ascii demo", "demo")
    check("1 ASCII 不被破坏且重复调用不变", once == "demo" and twice == "demo", once)

    print("== 2. 中文原文直传（latin-1 误解码）==", flush=True)
    wire = mojibake("往来原型")
    once, twice = show(receiver, "2 raw utf-8 via latin-1", wire)
    bug = mojibake("接入自检-可删")
    bug_out, bug_twice = show(receiver, "2 实测乱码样例 接入自检-可删", bug)
    check(
        "2 中文原文还原为往来原型",
        once == "往来原型" and twice == "往来原型",
        once,
    )
    check(
        "2 接入自检-可删 同样还原",
        bug_out == "接入自检-可删" and bug_twice == bug_out,
        bug_out,
    )

    print("== 3. percent-encoded 中文 ==", flush=True)
    quoted = urllib.parse.quote("往来原型", safe="/")
    lower = quoted.lower()
    once, twice = show(receiver, "3 quoted", quoted)
    low_once, low_twice = show(receiver, "3 quoted lowercase hex", lower)
    check(
        "3 percent 与小写十六进制都得到往来原型",
        once == "往来原型" and twice == once and low_once == "往来原型" and low_twice == low_once,
        (once, low_once),
    )

    print("== 4. 超集字符 ==" , flush=True)
    samples = ["原型🎨", "日本語テスト", "نموذج أولي", "接入自检-可删"]
    superset_ok = True
    for sample in samples:
        for kind, raw in (
            ("unicode", sample),
            ("mojibake", mojibake(sample)),
            ("quoted", urllib.parse.quote(sample, safe="/")),
        ):
            try:
                got = decode(raw, name_default)
                again = decode(got, name_default)
            except Exception as e:
                superset_ok = False
                print("SCENE 4 EXC | %s %s %s" % (sample, kind, e), flush=True)
                continue
            print(
                "SCENE 4 %s %s | out=%s len=%d stable=%s"
                % (kind, sample, repr(got), len(got), got == again),
                flush=True,
            )
            if got != sample or again != got or len(got) != len(sample):
                superset_ok = False
    check("4 emoji 日文 阿拉伯文不抛异常不截断", superset_ok)

    print("== 5. 混合形态 ==", flush=True)
    mixed = "%E5%BE%80%E6%9D%A5原型"
    once, twice = show(receiver, "5 mixed unicode", mixed)
    raw_bytes = "%E5%BE%80%E6%9D%A5".encode("ascii") + "原型".encode("utf-8")
    byte_mixed = raw_bytes.decode("latin-1")
    b_once, b_twice = show(receiver, "5 mixed wire bytes", byte_mixed)
    check(
        "5 混合形态得到往来原型且不崩溃",
        once == "往来原型" and twice == once and b_once == "往来原型" and b_twice == b_once,
        (once, b_once),
    )

    print("== 6. 恶意输入 ==" , flush=True)
    malicious = [
        ("%00", name_default),
        ("A%00B", "AB"),
        ("%2e%2e%2f", "%2e%2e%2f"),
        ("%", "%"),
        ("%%", "%%"),
        ("abc%", "abc%"),
        ("%FF", "%FF"),
        ("%E5", "%E5"),
        ("%" * 9000, "%" * 9000),
        ("A" * 9000, "A" * 9000),
    ]
    mal_ok = True
    for raw, expect in malicious:
        try:
            got = decode(raw, name_default)
            again = decode(got, name_default)
        except Exception as e:
            mal_ok = False
            print("SCENE 6 EXC | %s %s" % (repr(raw)[:40], e), flush=True)
            continue
        stable = got == again
        shown = repr(got)
        if len(shown) > 80:
            shown = "%s...(len=%d)" % (shown[:40], len(got))
        print(
            "SCENE 6 | in=%s out=%s stable=%s expect_ok=%s"
            % (repr(raw)[:50], shown, stable, got == expect),
            flush=True,
        )
        if got != expect or not stable:
            mal_ok = False
    big = "往" * 3000
    big_q = None
    big_m = None
    try:
        big_q = decode(urllib.parse.quote(big, safe="/"), name_default)
        big_m = decode(mojibake(big), name_default)
        big_ok = big_q == big and big_m == big and len(big_q) == 3000
    except Exception as e:
        big_ok = False
        print("SCENE 6 EXC long chinese | %s" % e, flush=True)
    print(
        "SCENE 6 long chinese | chars=%d quoted_ok=%s mojibake_ok=%s"
        % (3000, big_q == big, big_m == big),
        flush=True,
    )
    if not big_ok:
        mal_ok = False
    try:
        surrogate = decode("原型\ud800", name_default)
        surrogate_ok = surrogate == "原型\ufffd" and decode(surrogate, name_default) == surrogate
    except Exception as e:
        surrogate_ok = False
        print("SCENE 6 EXC surrogate | %s" % e, flush=True)
    print("SCENE 6 surrogate | out=%s" % repr(surrogate if surrogate_ok else "EXC"), flush=True)
    if not surrogate_ok:
        mal_ok = False
    check("6 恶意输入不抛异常且有兜底", mal_ok)

    print("== 7. 空值 / 缺失 ==", flush=True)
    empty_cases = [
        (None, name_default, name_default),
        ("", name_default, name_default),
        ("   ", name_default, name_default),
        (None, desc_default, desc_default),
        ("", desc_default, desc_default),
        ("未命名项目", name_default, "未命名项目"),
        ("无描述", desc_default, "无描述"),
    ]
    empty_ok = True
    for raw, default, expect in empty_cases:
        got = decode(raw, default)
        again = decode(got, default)
        print(
            "SCENE 7 | in=%s default=%s out=%s stable=%s"
            % (repr(raw), repr(default), repr(got), got == again),
            flush=True,
        )
        if got != expect or again != got:
            empty_ok = False
    check("7 空值与缺失使用现有默认值", empty_ok)

    print("== 8. MCP quote 回归（与 urllib.parse.unquote(quote(s)) 一致）==", flush=True)
    mcp_names = [
        "demo",
        "往来原型",
        "家庭人情账本",
        "原型🎨",
        "日本語テスト",
        "نموذج أولي",
        "100%完成",
        "100%2F完成",
        "%41",
        "标记%41",
        "a/b",
        "往来/原型",
        "hello world",
        "setup 链路验证",
    ]
    mcp_ok = True
    three_ok = True
    for sample in mcp_names:
        quoted_name = urllib.parse.quote(sample, safe="/")
        old = urllib.parse.unquote(quoted_name)
        got = decode(quoted_name, name_default)
        again = decode(got, name_default)
        print(
            "SCENE 8 | logical=%s quoted_out=%s old=%s stable=%s"
            % (repr(sample), repr(got), repr(old), got == again),
            flush=True,
        )
        if got != sample or got != old or again != got:
            mcp_ok = False
        trio = [decode(sample, name_default), decode(mojibake(sample), name_default), got]
        if len(set(trio)) != 1 or trio[0] != sample:
            three_ok = False
            print("SCENE 8 FORM | %s -> %s" % (repr(sample), trio), flush=True)
    # 客户端源码里的调用就是 quote 一次。这里锁住这两个字段。
    client_name = urllib.parse.quote("往来原型")
    client_desc = urllib.parse.quote("家庭人情账本")
    if decode(client_name, name_default) != "往来原型" or decode(client_desc, desc_default) != "家庭人情账本":
        mcp_ok = False
    check("8 quote 一次的输入与旧 unquote 行为一致", mcp_ok)
    check("8 三种形态解码结果相同且重复调用不变", three_ok and set(decode(v, name_default) for v in forms.values()) == {logical})

    double = urllib.parse.quote(urllib.parse.quote("往来原型"))
    layer1 = decode(double, name_default)
    layer2 = decode(layer1, name_default)
    print(
        "NOTE 双重 quote 只剥一层 | first=%s second=%s"
        % (repr(layer1), repr(layer2)),
        flush=True,
    )
    check(
        "边界 双重 quote 保持单层（与 MCP 的一次 quote 对齐）",
        layer1 == urllib.parse.quote("往来原型") and layer2 == "往来原型",
        (layer1, layer2),
    )


def make_zip(marker):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("index.html", "<!doctype html><html><body>%s</body></html>" % marker)
    return buf.getvalue()


def http_json(method, url, data=None, headers=None, timeout=30):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            return resp.status, body
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def delete_project(base, project_id):
    if not project_id:
        return
    status, _body = http_json("DELETE", base + "/api/projects/" + project_id)
    print("CLEAN %s | status=%s" % (project_id, status), flush=True)


def project_by_id(base, project_id):
    status, body = http_json("GET", base + "/api/projects")
    if status != 200:
        return None
    try:
        projects = json.loads(body.decode("utf-8"))
    except Exception:
        return None
    for item in projects:
        if item.get("id") == project_id:
            return item
    return None


def curl_deploy(base, zip_path, headers):
    cmd = ["curl", "-sS", "-D", "-", "-o", "-", "-X", "POST", base + "/api/deploy", "--data-binary", "@" + zip_path]
    for key, value in headers:
        cmd.extend(["-H", "%s: %s" % (key, value)])
    proc = subprocess.run(cmd, capture_output=True, text=True)
    raw = proc.stdout
    if "\r\n\r\n" in raw:
        head, body = raw.split("\r\n\r\n", 1)
    elif "\n\n" in raw:
        head, body = raw.split("\n\n", 1)
    else:
        head, body = "", raw
    status = 0
    for line in head.splitlines():
        if line.startswith("HTTP/"):
            parts = line.split()
            if len(parts) >= 2 and parts[1].isdigit():
                status = int(parts[1])
    parsed = None
    try:
        parsed = json.loads(body)
    except Exception:
        parsed = None
    return proc.returncode, status, body, parsed, proc.stderr


def run_live(receiver, base):
    base = base.rstrip("/")
    marker = "SDHEADER"
    zip_bytes = make_zip(marker)
    fd, zip_path = tempfile.mkstemp(prefix="sd-header-", suffix=".zip")
    os.close(fd)
    with open(zip_path, "wb") as f:
        f.write(zip_bytes)
    created = []
    try:
        print("== LIVE curl 中文原文 ==", flush=True)
        code, status, body, parsed, err = curl_deploy(base, zip_path, [
            ("X-Project-Name", "往来原型"),
            ("X-Project-Desc", "家庭人情账本"),
            ("X-Project-Type", "html"),
            ("X-Entry-File", "index.html"),
        ])
        print("SCENE LIVE raw | curl=%s http=%s body=%s" % (code, status, body.strip()[:400]), flush=True)
        if err.strip():
            print("SCENE LIVE raw stderr | %s" % err.strip()[:300], flush=True)
        raw_ok = parsed and parsed.get("name") == "往来原型" and parsed.get("success") is True
        check("LIVE 原文 name 是往来原型", raw_ok, None if raw_ok else body[:200])
        if parsed and parsed.get("project_id"):
            created.append(parsed["project_id"])
            record = project_by_id(base, parsed["project_id"])
            desc = (record or {}).get("description")
            check("LIVE 原文 description 是家庭人情账本", desc == "家庭人情账本", desc)
            abs_url = parsed.get("abs_url") or ""
            try:
                st, page = http_json("GET", abs_url)
                page_text = page.decode("utf-8", "replace")
                check("LIVE 原文 abs_url 200", st == 200 and marker in page_text, (st, abs_url))
            except Exception as e:
                check("LIVE 原文 abs_url 200", False, e)

        print("== LIVE curl percent-encoding ==", flush=True)
        code, status, body, parsed, err = curl_deploy(base, zip_path, [
            ("X-Project-Name", urllib.parse.quote("往来原型")),
            ("X-Project-Desc", urllib.parse.quote("家庭人情账本")),
            ("X-Project-Type", "html"),
            ("X-Entry-File", "index.html"),
        ])
        print("SCENE LIVE quoted | curl=%s http=%s body=%s" % (code, status, body.strip()[:400]), flush=True)
        quoted_ok = parsed and parsed.get("name") == "往来原型"
        check("LIVE percent name 与原文相同", quoted_ok, None if quoted_ok else body[:200])
        if parsed and parsed.get("project_id"):
            created.append(parsed["project_id"])
            record = project_by_id(base, parsed["project_id"])
            desc = (record or {}).get("description")
            check("LIVE percent description 相同", desc == "家庭人情账本", desc)

        print("== LIVE MCP 客户端 quote 路径 ==", flush=True)
        parsed_url = urllib.parse.urlparse(base)
        os.environ["PREVIEW_SERVER_HOST"] = parsed_url.hostname or "127.0.0.1"
        os.environ["PREVIEW_SERVER_PORT"] = str(parsed_url.port or 80)
        os.environ["PREVIEW_API_TOKEN"] = ""
        spec = importlib.util.spec_from_file_location(
            "sd_client_mcp",
            os.path.join(ROOT, "client-mcp", "mcp_server.py"),
        )
        client = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(client)
        try:
            mcp_res = client.send_deploy_request(zip_bytes, "往来原型", "家庭人情账本")
        except Exception as e:
            mcp_res = {"error": str(e)}
        print("SCENE LIVE mcp | %s" % json.dumps(mcp_res, ensure_ascii=False)[:400], flush=True)
        mcp_ok = isinstance(mcp_res, dict) and mcp_res.get("name") == "往来原型"
        check("LIVE MCP quote 后 name 仍是往来原型", mcp_ok, mcp_res if not mcp_ok else "")
        if isinstance(mcp_res, dict) and mcp_res.get("project_id"):
            created.append(mcp_res["project_id"])
            record = project_by_id(base, mcp_res["project_id"])
            desc = (record or {}).get("description")
            check("LIVE MCP description 仍是家庭人情账本", desc == "家庭人情账本", desc)
        try:
            literal = client.send_deploy_request(zip_bytes, "标记%41", "百分号字面量")
        except Exception as e:
            literal = {"error": str(e)}
        print("SCENE LIVE mcp literal %%41 | %s" % json.dumps(literal, ensure_ascii=False)[:300], flush=True)
        literal_ok = isinstance(literal, dict) and literal.get("name") == "标记%41"
        check("LIVE MCP 名字里的 %41 不被再解成 A", literal_ok, literal if not literal_ok else "")
        if isinstance(literal, dict) and literal.get("project_id"):
            created.append(literal["project_id"])

        print("== LIVE 空值与恶意 header ==" , flush=True)
        code, status, body, parsed, err = curl_deploy(base, zip_path, [
            ("X-Project-Type", "html"),
            ("X-Entry-File", "index.html"),
        ])
        print("SCENE LIVE missing | http=%s body=%s" % (status, body.strip()[:240]), flush=True)
        missing_ok = parsed and parsed.get("name") == "未命名项目"
        check("LIVE 缺失 header 使用未命名项目", missing_ok, None if missing_ok else body[:160])
        if parsed and parsed.get("project_id"):
            created.append(parsed["project_id"])
            record = project_by_id(base, parsed["project_id"])
            check(
                "LIVE 缺失描述使用无描述",
                (record or {}).get("description") == "无描述",
                (record or {}).get("description"),
            )

        code, status, body, parsed, err = curl_deploy(base, zip_path, [
            ("X-Project-Name", ""),
            ("X-Project-Desc", ""),
            ("X-Project-Type", "html"),
            ("X-Entry-File", "index.html"),
        ])
        print("SCENE LIVE empty | http=%s body=%s" % (status, body.strip()[:240]), flush=True)
        empty_ok = parsed and parsed.get("name") == "未命名项目"
        check("LIVE 空 header 使用未命名项目", empty_ok, None if empty_ok else body[:160])
        if parsed and parsed.get("project_id"):
            created.append(parsed["project_id"])

        for label, raw_name in (
            ("%00", "%00"),
            ("%2e%2e%2f", "%2e%2e%2f"),
            ("%", "%"),
            ("%%", "%%"),
            ("abc%", "abc%"),
            ("long", "A" * 9000),
        ):
            code, status, body, parsed, err = curl_deploy(base, zip_path, [
                ("X-Project-Name", raw_name),
                ("X-Project-Desc", raw_name if label != "long" else "desc"),
                ("X-Project-Type", "html"),
                ("X-Entry-File", "index.html"),
            ])
            name = parsed.get("name") if isinstance(parsed, dict) else None
            shown = repr(name)
            if shown and len(shown) > 60:
                shown = "len=%s prefix=%s" % (len(name or ""), repr((name or "")[:20]))
            print(
                "SCENE LIVE evil %s | http=%s name=%s err=%s"
                % (label, status, shown, (err or "").strip()[:120]),
                flush=True,
            )
            not_500 = status != 500 and code == 0
            check("LIVE 恶意 %s 不是 500" % label, not_500, (status, body[:120]))
            if parsed and parsed.get("project_id"):
                created.append(parsed["project_id"])
            if label == "%00" and status == 200:
                check("LIVE %%00 兜底为未命名项目", name == "未命名项目", name)
            if label == "%2e%2e%2f" and status == 200:
                check("LIVE %%2e%2e%2f 按字面入库", name == "%2e%2e%2f", name)
    finally:
        for project_id in created:
            try:
                delete_project(base, project_id)
            except Exception as e:
                print("CLEAN FAIL %s | %s" % (project_id, e), flush=True)
        try:
            os.remove(zip_path)
        except OSError:
            pass


def main():
    receiver = load_receiver()
    run_unit(receiver)
    if len(sys.argv) > 1:
        run_live(receiver, sys.argv[1])
    print("", flush=True)
    print("RESULT: " + ("ALL PASS" if not FAILED else "FAILED: " + ", ".join(FAILED)), flush=True)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
