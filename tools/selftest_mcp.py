#!/usr/bin/env python3
"""static-deploy 远程 MCP 验收 harness（纯标准库）。"""

import json
import os
import sys
import time
import urllib.error
import urllib.request

DEFAULT_BASE = "http://127.0.0.1:8088"
META_FILE = "/data/static-deploy/meta/projects.json"
DATA_ROOT = "/data/static-deploy"
PNG_1X1_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+X89QAAAAASUVORK5CYII="
)


class Tester:
    def __init__(self, base):
        self.base = base.rstrip("/")
        self.failed = 0
        self.passed = 0
        self.created_ids = []
        self.session_id = None

    def record(self, name, ok, detail=""):
        status = "PASS" if ok else "FAIL"
        extra = (" " + detail) if detail and not ok else ""
        print("%s %s%s" % (status, name, extra), flush=True)
        if ok:
            self.passed += 1
        else:
            self.failed += 1

    def request(self, method, path, data=None, headers=None, timeout=30):
        url = path if path.startswith("http") else self.base + path
        hdrs = dict(headers or {})
        body = None
        if data is not None:
            if isinstance(data, bytes):
                body = data
            else:
                body = data.encode("utf-8")
            hdrs.setdefault("Content-Type", "application/json; charset=utf-8")
        req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
        try:
            resp = urllib.request.urlopen(req, timeout=timeout)
            raw = resp.read()
            return resp.status, dict(resp.headers), raw
        except urllib.error.HTTPError as e:
            raw = e.read()
            return e.code, dict(e.headers), raw

    def mcp(self, payload, extra_headers=None, method="POST"):
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        if extra_headers:
            headers.update(extra_headers)
        body = None if payload is None else json.dumps(payload, ensure_ascii=False)
        status, hdrs, raw = self.request(method, "/mcp", data=body, headers=headers)
        sid = hdrs.get("Mcp-Session-Id") or hdrs.get("mcp-session-id")
        if sid:
            self.session_id = sid
        parsed = None
        if raw:
            try:
                parsed = json.loads(raw.decode("utf-8"))
            except Exception:
                parsed = None
        return status, hdrs, raw, parsed

    def remember_id_from_text(self, text):
        if not text:
            return
        marker = "/sites/"
        if marker not in text:
            return
        part = text.split(marker, 1)[1]
        pid = part.split("/", 1)[0].strip()
        if pid and pid not in self.created_ids:
            self.created_ids.append(pid)

    def test_initialize(self):
        status, hdrs, raw, parsed = self.mcp({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "selftest", "version": "1.0"},
            },
        })
        sid = hdrs.get("Mcp-Session-Id") or hdrs.get("mcp-session-id") or ""
        ok = (
            status == 200
            and parsed
            and parsed.get("result", {}).get("protocolVersion") == "2025-03-26"
            and len(sid) == 16
            and all(c in "0123456789abcdef" for c in sid.lower())
        )
        self.record("mcp_initialize", ok, "status=%s sid=%s body=%s" % (status, sid, raw[:200]))
        if sid:
            status2, hdrs2, _, parsed2 = self.mcp({
                "jsonrpc": "2.0",
                "id": 2,
                "method": "ping",
            }, extra_headers={"Mcp-Session-Id": sid})
            sid2 = hdrs2.get("Mcp-Session-Id") or hdrs2.get("mcp-session-id")
            self.record("mcp_session_echo", sid2 == sid and parsed2 and "result" in parsed2, "sid2=%s" % sid2)

    def test_tools_list(self):
        status, _, raw, parsed = self.mcp({
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/list",
        })
        names = []
        if parsed and isinstance(parsed.get("result"), dict):
            names = [t.get("name") for t in parsed["result"].get("tools", [])]
        ok = status == 200 and set(names) == {
            "deploy_static_project",
            "upload_image",
            "list_projects",
        }
        self.record("tools_list", ok, "names=%s" % names)

    def test_notification(self):
        status, _, raw, _ = self.mcp({
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {},
        })
        self.record("notifications_initialized", status == 202 and raw == b"", "status=%s len=%s" % (status, len(raw)))

    def test_unknown_method(self):
        status, _, _, parsed = self.mcp({
            "jsonrpc": "2.0",
            "id": 4,
            "method": "no/such/method",
        })
        code = (parsed or {}).get("error", {}).get("code")
        self.record("unknown_method", status == 200 and code == -32601, "code=%s" % code)

    def test_parse_error(self):
        status, _, raw, parsed = self.mcp(None)
        # empty / non-json body
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        status, _, raw = self.request("POST", "/mcp", data="this is not json {", headers=headers)
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except Exception:
            parsed = None
        code = (parsed or {}).get("error", {}).get("code")
        self.record("parse_error", code == -32700, "code=%s body=%s" % (code, raw[:120]))

    def test_get_delete(self):
        status, hdrs, _ = self.request("GET", "/mcp")
        allow = hdrs.get("Allow") or hdrs.get("allow") or ""
        self.record("get_mcp_405", status == 405 and "POST" in allow and "DELETE" in allow, "status=%s allow=%s" % (status, allow))
        status, _, raw = self.request("DELETE", "/mcp")
        self.record("delete_mcp_204", status == 204 and raw == b"", "status=%s" % status)

    def call_tool(self, name, arguments, req_id=10):
        return self.mcp({
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        })

    def test_deploy_html(self):
        sentinel = "SELFTEST_HTML_SENTINEL_%s" % int(time.time())
        html = "<!doctype html><html><body>%s</body></html>" % sentinel
        status, _, raw, parsed = self.call_tool("deploy_static_project", {
            "project_name": "selftest-html",
            "description": "selftest html deploy",
            "html": html,
        }, req_id=11)
        result = (parsed or {}).get("result") or {}
        text = ""
        if result.get("content"):
            text = result["content"][0].get("text", "")
        self.remember_id_from_text(text)
        ok_rpc = status == 200 and result and not result.get("isError") and "部署成功" in text and "手机直达:" in text
        url = ""
        for line in text.splitlines():
            if line.startswith("手机直达:"):
                url = line.split(":", 1)[1].strip()
        page_ok = False
        if url:
            st, _, body = self.request("GET", url)
            page_ok = st == 200 and sentinel.encode("utf-8") in body
        self.record("deploy_html", ok_rpc and page_ok, "text=%s" % text[:180])

    def test_deploy_nested_files(self):
        sentinel = "SELFTEST_NESTED_SENTINEL"
        status, _, raw, parsed = self.call_tool("deploy_static_project", {
            "project_name": "selftest-nested",
            "description": "selftest nested entry",
            "entry_file": "demo/index.html",
            "files": {
                "demo/index.html": "<!doctype html><html><body>%s</body></html>" % sentinel,
                "demo/app.js": "console.log('ok');",
            },
        }, req_id=12)
        result = (parsed or {}).get("result") or {}
        text = ""
        if result.get("content"):
            text = result["content"][0].get("text", "")
        self.remember_id_from_text(text)
        url = ""
        for line in text.splitlines():
            if line.startswith("手机直达:"):
                url = line.split(":", 1)[1].strip()
        page_ok = False
        if url:
            st, _, body = self.request("GET", url)
            page_ok = st == 200 and sentinel.encode("utf-8") in body and "/demo/index.html" in url
        ok = (not result.get("isError")) and page_ok
        self.record("deploy_nested_files", ok, "url=%s" % url)

    def test_conflict_params(self):
        status, _, _, parsed = self.call_tool("deploy_static_project", {
            "project_name": "selftest-conflict",
            "description": "conflict",
            "files": {},
            "html": "<html></html>",
        }, req_id=13)
        result = (parsed or {}).get("result") or {}
        self.record("conflict_files_html", bool(result.get("isError")), "result=%s" % result)

    def test_path_traversal(self):
        token = os.urandom(4).hex()
        evil_name = "../../evil_%s.txt" % token
        status, _, _, parsed = self.call_tool("deploy_static_project", {
            "project_name": "selftest-traversal",
            "description": "traversal",
            "files": {evil_name: "x"},
        }, req_id=14)
        result = (parsed or {}).get("result") or {}
        outside = os.path.join(os.path.dirname(DATA_ROOT.rstrip("/")), "evil_%s.txt" % token)
        host_hit = os.path.exists(outside) or os.path.exists("/data/evil_%s.txt" % token) or os.path.exists("/opt/code/evil_%s.txt" % token)
        self.record(
            "path_traversal_rejected",
            bool(result.get("isError")) and not host_hit,
            "result=%s exists=%s" % (result, host_hit),
        )

    def test_upload_image(self):
        status, _, _, parsed = self.call_tool("upload_image", {
            "project_name": "selftest-image",
            "description": "selftest png",
            "filename": "dot.png",
            "image_base64": "data:image/png;base64," + PNG_1X1_B64,
        }, req_id=15)
        result = (parsed or {}).get("result") or {}
        text = ""
        if result.get("content"):
            text = result["content"][0].get("text", "")
        self.remember_id_from_text(text)
        url = ""
        for line in text.splitlines():
            if line.startswith("手机直达:"):
                url = line.split(":", 1)[1].strip()
        page_ok = False
        if url:
            st, _, body = self.request("GET", url)
            page_ok = st == 200 and body.startswith(b"\x89PNG")
        self.record("upload_image_ok", (not result.get("isError")) and "上传成功" in text and page_ok, "text=%s" % text[:160])

    def test_upload_bad_b64(self):
        status, _, _, parsed = self.call_tool("upload_image", {
            "project_name": "selftest-badb64",
            "description": "bad",
            "filename": "dot.png",
            "image_base64": "%%%not-valid-base64%%%",
        }, req_id=16)
        result = (parsed or {}).get("result") or {}
        self.record("upload_image_bad_b64", bool(result.get("isError")), "result=%s" % result)

    def test_upload_bad_ext(self):
        status, _, _, parsed = self.call_tool("upload_image", {
            "project_name": "selftest-badext",
            "description": "bad",
            "filename": "dot.exe",
            "image_base64": PNG_1X1_B64,
        }, req_id=17)
        result = (parsed or {}).get("result") or {}
        self.record("upload_image_bad_ext", bool(result.get("isError")), "result=%s" % result)

    def test_list_projects(self):
        status, _, _, parsed = self.call_tool("list_projects", {}, req_id=18)
        result = (parsed or {}).get("result") or {}
        text = ""
        if result.get("content"):
            text = result["content"][0].get("text", "")
        has_item = "selftest-html" in text
        abs_ok = "http://" in text
        self.record("list_projects", (not result.get("isError")) and has_item and abs_ok, "text=%s" % text[:240])

    def test_empty_files(self):
        status, _, _, parsed = self.call_tool("deploy_static_project", {
            "project_name": "selftest-empty",
            "description": "empty files",
            "files": {},
        }, req_id=19)
        result = (parsed or {}).get("result") or {}
        self.record("empty_files_rejected", bool(result.get("isError")), "result=%s" % result)

    def cleanup(self):
        leftover = []
        for pid in list(self.created_ids):
            status, _, raw = self.request("DELETE", "/api/projects/%s" % pid)
            if status != 200:
                leftover.append("%s(status=%s)" % (pid, status))
        try:
            with open(META_FILE, "r", encoding="utf-8") as f:
                projects = json.load(f)
        except Exception as e:
            self.record("cleanup_meta_readable", False, str(e))
            projects = []
        for p in projects:
            name = str(p.get("name") or "")
            pid = str(p.get("id") or "")
            if name.startswith("selftest"):
                st, _, _ = self.request("DELETE", "/api/projects/%s" % pid)
                if st != 200:
                    leftover.append("%s(status=%s)" % (pid, st))
        try:
            with open(META_FILE, "r", encoding="utf-8") as f:
                projects2 = json.load(f)
        except Exception:
            projects2 = []
        residual = []
        for p in projects2:
            name = str(p.get("name") or "")
            if name.startswith("selftest"):
                residual.append(name or p.get("id"))
        if leftover:
            print("未清理的 id: %s" % ", ".join(leftover), flush=True)
        self.record("cleanup_no_selftest_residual", not residual, "residual=%s" % residual)

    def run(self):
        self.test_initialize()
        self.test_tools_list()
        self.test_notification()
        self.test_unknown_method()
        self.test_parse_error()
        self.test_get_delete()
        self.test_deploy_html()
        self.test_deploy_nested_files()
        self.test_conflict_params()
        self.test_path_traversal()
        self.test_upload_image()
        self.test_upload_bad_b64()
        self.test_upload_bad_ext()
        self.test_list_projects()
        self.test_empty_files()
        self.cleanup()
        print("done passed=%s failed=%s" % (self.passed, self.failed), flush=True)
        return 0 if self.failed == 0 else 1


def main():
    base = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_BASE
    return Tester(base).run()


if __name__ == "__main__":
    sys.exit(main())
