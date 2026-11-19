#!/usr/bin/env python3
"""保留策略、孤儿扫描、删除护栏与 cleanup.log 的标准库测试。

数据目录由本进程创建在临时路径，不读写 /data。
"""

import io
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zipfile
from unittest import mock


def _load_receiver(data_dir):
    os.environ["DATA_DIR"] = data_dir
    os.environ["PORT"] = "0"
    os.environ["API_TOKEN"] = ""
    server_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server")
    if server_dir not in sys.path:
        sys.path.insert(0, server_dir)
    # 模块在导入时按 DATA_DIR 建目录。测试各自换目录时重载。
    if "receiver" in sys.modules:
        del sys.modules["receiver"]
    import receiver
    return receiver


class RetentionCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sd-retention-")
        self.receiver = _load_receiver(self.tmp)
        self.httpd = None

    def tearDown(self):
        if self.httpd is not None:
            self.httpd.shutdown()
            self.httpd.server_close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _record(self, project_id, name, created):
        site = os.path.join(self.receiver.SITES_DIR, project_id)
        os.makedirs(site, exist_ok=True)
        with open(os.path.join(site, "index.html"), "w", encoding="utf-8") as f:
            f.write(project_id)
        return {
            "id": project_id,
            "name": name,
            "description": "t",
            "type": "html",
            "entry": "index.html",
            "created_at": created,
            "url": "/sites/%s/index.html" % project_id,
        }

    def test_normalize_title_folds_width_space_and_case(self):
        n = self.receiver.normalize_title
        self.assertEqual(n("活动页"), n("活 动 页"))
        self.assertEqual(n("活动页"), n("活　动\n页"))
        self.assertEqual(n("Demo Page"), n("ｄｅｍｏ　ｐａｇｅ"))
        self.assertEqual(n("Demo Page"), n("DEMO\tpage"))
        self.assertNotEqual(n("活动页"), n("活动页2"))
        self.assertNotEqual(n("活动页"), n("活动页。"))

    def test_fourth_same_title_drops_oldest_only(self):
        r = self.receiver
        removed_all = []
        for i, stamp in enumerate(("2026-01-01 00:00:0%d" % n for n in (1, 2, 3, 4)), start=1):
            rec = self._record("p-old-%d" % i, "活动 页", stamp)
            _projects, removed = r.add_project_record(rec)
            removed_all.extend(removed)
        projects = r.load_projects()
        ids = [p["id"] for p in projects]
        self.assertEqual(ids, ["p-old-4", "p-old-3", "p-old-2"])
        self.assertEqual(removed_all, ["p-old-1"])
        self.assertFalse(os.path.isdir(os.path.join(r.SITES_DIR, "p-old-1")))
        self.assertTrue(os.path.isdir(os.path.join(r.SITES_DIR, "p-old-4")))
        with open(r.CLEANUP_LOG, encoding="utf-8") as f:
            lines = [json.loads(line) for line in f if line.strip()]
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["removed_ids"], ["p-old-1"])
        self.assertEqual(lines[0]["kept_ids"], ["p-old-4", "p-old-3", "p-old-2"])

    def test_fullwidth_space_variant_joins_same_group(self):
        r = self.receiver
        for i, name in enumerate(("活动页", "活 动页", "活　动页", "活动  页"), start=1):
            rec = self._record("p-norm-%d" % i, name, "2026-02-0%d 00:00:00" % i)
            r.add_project_record(rec)
        ids = [p["id"] for p in r.load_projects()]
        self.assertEqual(ids, ["p-norm-4", "p-norm-3", "p-norm-2"])
        self.assertFalse(os.path.isdir(os.path.join(r.SITES_DIR, "p-norm-1")))

    def test_other_title_untouched(self):
        r = self.receiver
        other = self._record("p-other", "另一页", "2026-01-01 00:00:00")
        r.add_project_record(other)
        for i in range(1, 5):
            rec = self._record("p-a-%d" % i, "甲", "2026-03-0%d 00:00:00" % i)
            r.add_project_record(rec)
        ids = {p["id"] for p in r.load_projects()}
        self.assertIn("p-other", ids)
        self.assertTrue(os.path.isdir(os.path.join(r.SITES_DIR, "p-other")))

    def test_concurrent_same_title_keeps_all_newcomers(self):
        """8 个线程同时写入同一标题，最终恰好 3 条，且都来自这 8 个新 id。"""
        r = self.receiver
        for i in range(3):
            rec = self._record("p-seed-%d" % i, "并发页", "2020-01-0%d 00:00:00" % (i + 1))
            r.add_project_record(rec)

        barrier = threading.Barrier(8)
        errors = []

        def worker(i):
            try:
                barrier.wait(timeout=5)
                rec = self._record(
                    "p-new-%d" % i,
                    "并 发页" if i % 2 else "并发页",
                    "2026-11-16 12:00:%02d" % i,
                )
                r.add_project_record(rec)
            except Exception as e:  # noqa: BLE001 收集到断言
                errors.append(repr(e))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        self.assertEqual(errors, [])
        projects = r.load_projects()
        ids = [p["id"] for p in projects]
        self.assertEqual(len(ids), 3)
        self.assertTrue(all(item.startswith("p-new-") for item in ids))
        for seed in ("p-seed-0", "p-seed-1", "p-seed-2"):
            self.assertNotIn(seed, ids)
            self.assertFalse(os.path.isdir(os.path.join(r.SITES_DIR, seed)))
        for item in ids:
            self.assertTrue(os.path.isdir(os.path.join(r.SITES_DIR, item)))

    def test_same_timestamp_prefers_incoming(self):
        r = self.receiver
        stamp = "2026-05-01 00:00:00"
        for i in range(3):
            r.add_project_record(self._record("p-tie-%d" % i, "同时", stamp))
        _projects, removed = r.add_project_record(self._record("p-tie-new", "同时", stamp))
        ids = [p["id"] for p in r.load_projects()]
        self.assertIn("p-tie-new", ids)
        self.assertEqual(len(ids), 3)
        self.assertEqual(len(removed), 1)
        self.assertNotIn(removed[0], ids)

    def test_replace_failure_leaves_no_partial_meta(self):
        r = self.receiver
        r.add_project_record(self._record("p-keep", "稳定", "2026-01-01 00:00:00"))
        with open(r.META_FILE, "rb") as f:
            before = f.read()
        with mock.patch.object(r.os, "replace", side_effect=OSError("disk")):
            with self.assertRaises(OSError):
                r.add_project_record(self._record("p-new", "稳定", "2026-01-02 00:00:00"))
        with open(r.META_FILE, "rb") as f:
            after = f.read()
        self.assertEqual(before, after)
        self.assertEqual([p["id"] for p in r.load_projects()], ["p-keep"])
        leftovers = [name for name in os.listdir(r.META_DIR) if ".tmp." in name]
        self.assertEqual(leftovers, [])
        self.assertTrue(os.path.isdir(os.path.join(r.SITES_DIR, "p-new")))
        self.assertFalse(os.path.exists(r.CLEANUP_LOG))

    def test_cleanup_log_append_crash_keeps_existing_lines(self):
        r = self.receiver
        existing = '{"ts":"2026-01-01 00:00:00","removed_ids":["p-a"],"kept_ids":["p-b"]}\n'
        with open(r.CLEANUP_LOG, "w", encoding="utf-8") as f:
            f.write(existing)
        real_open = open

        def boom(path, mode="r", *args, **kwargs):
            if path == r.CLEANUP_LOG and "a" in mode:
                raise OSError("append crashed")
            return real_open(path, mode, *args, **kwargs)

        with mock.patch("builtins.open", boom):
            with self.assertRaises(OSError):
                r.append_cleanup_log(["p-c"], ["p-d"])
        with open(r.CLEANUP_LOG, encoding="utf-8") as f:
            text = f.read()
        self.assertEqual(text, existing)
        json.loads(text.strip())
        leftovers = [name for name in os.listdir(r.META_DIR) if name.startswith("cleanup.log.tmp.")]
        self.assertEqual(leftovers, [])

    def test_delete_unknown_and_named_orphan(self):
        r = self.receiver
        orphan = os.path.join(r.SITES_DIR, "asr-api")
        os.makedirs(orphan, exist_ok=True)
        with open(os.path.join(orphan, "index.html"), "w", encoding="utf-8") as f:
            f.write("orphan")
        self.assertIsNone(r.delete_project_record("does-not-exist"))
        self.assertIsNone(r.delete_project_record("asr-api"))
        self.assertTrue(os.path.isdir(orphan))
        orphans = r.scan_orphans()
        self.assertEqual([item["name"] for item in orphans], ["asr-api"])
        self.assertGreater(orphans[0]["size_bytes"], 0)
        consistent, count = r.meta_disk_status()
        self.assertFalse(consistent)
        self.assertEqual(count, 1)

    def test_http_delete_orphan_and_missing(self):
        r = self.receiver
        os.makedirs(os.path.join(r.SITES_DIR, "game-dev-playbook"), exist_ok=True)
        self.httpd = r.ThreadingHTTPServer(("127.0.0.1", 0), r.DeployHandler)
        port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        base = "http://127.0.0.1:%s" % port

        def call(method, path, data=None, headers=None):
            req = urllib.request.Request(base + path, data=data, headers=headers or {}, method=method)
            try:
                with urllib.request.urlopen(req, timeout=5) as resp:
                    return resp.status, json.loads(resp.read().decode("utf-8") or "null")
            except urllib.error.HTTPError as e:
                raw = e.read().decode("utf-8")
                e.close()
                body = json.loads(raw) if raw else {}
                return e.code, body

        status, body = call("DELETE", "/api/projects/missing-id")
        self.assertEqual(status, 404)
        self.assertIn("not found", body.get("error", "").lower())
        status, body = call("DELETE", "/api/projects/game-dev-playbook")
        self.assertEqual(status, 404)
        self.assertTrue(os.path.isdir(os.path.join(r.SITES_DIR, "game-dev-playbook")))

        status, health = call("GET", "/api/health")
        self.assertEqual(status, 200)
        self.assertIn("meta_disk_consistent", health)
        self.assertIn("orphan_count", health)
        self.assertFalse(health["meta_disk_consistent"])
        self.assertGreaterEqual(health["orphan_count"], 1)

        status, orphans = call("GET", "/api/orphans")
        self.assertEqual(status, 200)
        names = [item["name"] for item in orphans]
        self.assertIn("game-dev-playbook", names)

        blob = io.BytesIO()
        with zipfile.ZipFile(blob, "w") as zf:
            zf.writestr("index.html", "<html>v</html>")
        payload = blob.getvalue()
        removed = []
        for i in range(4):
            headers = {
                "Content-Type": "application/zip",
                "X-Project-Name": "Curl Title",
                "X-Project-Desc": "d",
                "X-Project-Type": "html",
                "X-Entry-File": "index.html",
            }
            status, body = call("POST", "/api/deploy", data=payload, headers=headers)
            self.assertEqual(status, 200, body)
            self.assertIn("removed_old", body)
            removed.extend(body["removed_old"])
            if i < 3:
                self.assertEqual(body["removed_old"], [])
        self.assertEqual(len(removed), 1)
        status, projects = call("GET", "/api/projects")
        titled = [p for p in projects if p["name"] == "Curl Title"]
        self.assertEqual(len(titled), 3)
        self.assertTrue(all("size_bytes" in p and p["size_bytes"] > 0 for p in titled))
        self.assertNotIn(removed[0], {p["id"] for p in titled})
        with open(r.CLEANUP_LOG, encoding="utf-8") as f:
            lines = [json.loads(line) for line in f if line.strip()]
        self.assertEqual(lines[-1]["removed_ids"], removed)


class ProjectSlotCase(unittest.TestCase):
    """稳定 project slug：覆盖写、快照轮转，以及不传 project 时的旧行为。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sd-project-")
        self.receiver = _load_receiver(self.tmp)
        self.httpd = None
        self.base = None

    def tearDown(self):
        if self.httpd is not None:
            self.httpd.shutdown()
            self.httpd.server_close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _start(self):
        r = self.receiver
        self.httpd = r.ThreadingHTTPServer(("127.0.0.1", 0), r.DeployHandler)
        port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = "http://127.0.0.1:%s" % port

    def _call(self, method, path, data=None, headers=None):
        req = urllib.request.Request(
            self.base + path, data=data, headers=headers or {}, method=method
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read()
                body = json.loads(raw.decode("utf-8") or "null") if raw else None
                return resp.status, body
        except urllib.error.HTTPError as e:
            raw = e.read()
            e.close()
            body = {}
            if raw:
                try:
                    body = json.loads(raw.decode("utf-8"))
                except json.JSONDecodeError:
                    body = {"error": raw.decode("utf-8", errors="replace")}
            return e.code, body

    def _zip(self, files):
        blob = io.BytesIO()
        with zipfile.ZipFile(blob, "w") as zf:
            for name, content in files.items():
                zf.writestr(name, content)
        return blob.getvalue()

    def _header(self, value):
        text = "" if value is None else str(value)
        try:
            text.encode("latin-1")
            return text
        except UnicodeEncodeError:
            return urllib.parse.quote(text)

    def _deploy(self, name, files, project=None, entry="index.html", project_type="html"):
        headers = {
            "Content-Type": "application/zip" if project_type != "image" else "application/octet-stream",
            "X-Project-Name": name,
            "X-Project-Desc": "d",
            "X-Project-Type": project_type,
            "X-Entry-File": entry,
        }
        if project is not None:
            headers["X-Project"] = self._header(project)
        headers["X-Project-Name"] = self._header(name)
        headers["X-Project-Desc"] = self._header(headers["X-Project-Desc"])
        if project_type == "image":
            payload = files if isinstance(files, bytes) else files["index.html"].encode("utf-8")
        else:
            payload = self._zip(files)
        return self._call("POST", "/api/deploy", data=payload, headers=headers)

    def _mcp_deploy(self, arguments):
        status, body = self._call(
            "POST",
            "/mcp",
            data=json.dumps({
                "jsonrpc": "2.0",
                "id": 7,
                "method": "tools/call",
                "params": {"name": "deploy_static_project", "arguments": arguments},
            }).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        return status, body

    def test_slug_rejects_traversal_absolute_long_and_illegal(self):
        r = self.receiver
        validate = r.validate_project_slug
        rejected = [
            "../etc",
            "..",
            ".",
            "/etc/passwd",
            "/tmp/sd-abs-pwn",
            "foo/bar",
            "foo\\bar",
            "a/../../x",
            "..%2F..%2Ftmp%2Fpwn",
            "What-Cooks",
            "A",
            "a_b",
            "a.b",
            "a b",
            "-abc",
            "abc-",
            "",
            " ",
            "a" * 65,
            "项目",
            "what-cooks\nset",
            "~root",
            "foo\x00bar",
            "versions/1",
        ]
        for raw in rejected:
            with self.assertRaises(r.ProjectSlugError, msg=raw):
                validate(raw)
        self.assertEqual(validate("what-cooks"), "what-cooks")
        self.assertEqual(validate(" a-b1 "), "a-b1")
        self.assertEqual(validate("a"), "a")
        self.assertEqual(validate("a" * 64), "a" * 64)
        self.assertEqual(validate("a--b"), "a--b")

        self._start()
        parent = os.path.dirname(os.path.abspath(r.SITES_DIR))
        sites_before = set(os.listdir(r.SITES_DIR))
        parent_before = set(os.listdir(parent))
        http_cases = [
            "../etc",
            "/tmp/sd-abs-pwn",
            "a" * 65,
            "What-Cooks",
            "foo/bar",
            "a_b",
            "a.b",
            "..\\..\\tmp\\pwn",
            "",
        ]
        for raw in http_cases:
            status, body = self._deploy("bad", {"index.html": "<html>no</html>"}, project=raw)
            self.assertEqual(status, 400, (raw, body))
            self.assertIn("project", (body.get("error") or "").lower() + str(body))
            self.assertFalse(os.path.exists("/tmp/sd-abs-pwn"))
            self.assertFalse(os.path.exists(os.path.join(parent, "etc")))
        self.assertEqual(set(os.listdir(r.SITES_DIR)), sites_before)
        self.assertEqual(set(os.listdir(parent)), parent_before)
        status, rpc = self._mcp_deploy({
            "project": "../etc",
            "project_name": "bad",
            "description": "bad",
            "html": "<html>no</html>",
        })
        self.assertEqual(status, 200, rpc)
        result = (rpc or {}).get("result") or {}
        self.assertTrue(result.get("isError"), rpc)
        self.assertIn("project", result.get("content", [{}])[0].get("text", ""))
        self.assertEqual(set(os.listdir(r.SITES_DIR)), sites_before)

    def test_five_deploys_keep_one_record_and_three_snapshots(self):
        r = self.receiver
        self._start()
        urls = []
        created = None
        for i in range(1, 6):
            files = {"index.html": "<html>v%d</html>" % i}
            if i == 1:
                files["only1.js"] = "only1"
            if i == 4:
                files["keep4.txt"] = "keep4"
            status, body = self._deploy("标题方案%d" % i, files, project="what-cooks")
            self.assertEqual(status, 200, body)
            self.assertEqual(body["project"], "what-cooks")
            self.assertEqual(body["project_id"], "what-cooks")
            self.assertEqual(body["url"], "/sites/what-cooks/index.html")
            self.assertEqual(body["version"], i)
            self.assertEqual(body["snapshot_count"], min(i - 1, 3))
            self.assertEqual(body["removed_old"], [])
            self.assertIsInstance(body["version"], int)
            urls.append(body["abs_url"])
            if i == 1:
                created = body["created_at"]
            else:
                self.assertEqual(body["created_at"], created)
                self.assertTrue(body.get("updated_at"))
        self.assertEqual(len(set(urls)), 1)
        projects = r.load_projects()
        slotted = [p for p in projects if p.get("id") == "what-cooks" or p.get("project") == "what-cooks"]
        self.assertEqual(len(slotted), 1)
        rec = slotted[0]
        self.assertEqual(rec["project"], "what-cooks")
        self.assertEqual(rec["version"], 5)
        self.assertEqual(rec["snapshot_count"], 3)
        self.assertEqual(len(rec["snapshots"]), 3)
        self.assertEqual([s["version"] for s in rec["snapshots"]], [4, 3, 2])
        self.assertEqual(rec["snapshots"][0]["url"], "/sites/what-cooks/versions/4/index.html")
        self.assertEqual(rec["name"], "标题方案5")
        root = os.path.join(r.SITES_DIR, "what-cooks")
        with open(os.path.join(root, "index.html"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "<html>v5</html>")
        self.assertFalse(os.path.exists(os.path.join(root, "only1.js")))
        self.assertFalse(os.path.exists(os.path.join(root, "keep4.txt")))
        self.assertFalse(os.path.isdir(os.path.join(root, "versions", "5")))
        self.assertFalse(os.path.isdir(os.path.join(root, "versions", "1")))
        for ver, text in ((2, "v2"), (3, "v3"), (4, "v4")):
            snap = os.path.join(root, "versions", str(ver), "index.html")
            with open(snap, encoding="utf-8") as f:
                self.assertEqual(f.read(), "<html>%s</html>" % text)
            self.assertFalse(os.path.isdir(os.path.join(root, "versions", str(ver), "versions")))
        with open(os.path.join(root, "versions", "4", "keep4.txt"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "keep4")
        with open(os.path.join(root, "versions", "2", "index.html"), encoding="utf-8") as f:
            self.assertNotIn("v5", f.read())
        staging = os.path.join(r.DATA_DIR, "staging")
        if os.path.isdir(staging):
            self.assertEqual(os.listdir(staging), [])

    def test_without_project_keeps_title_retention(self):
        r = self.receiver
        self._start()
        ids = []
        for i in range(4):
            status, body = self._deploy("Curl Title", {"index.html": "<html>%d</html>" % i})
            self.assertEqual(status, 200, body)
            self.assertEqual(set(body.keys()), {
                "success", "project_id", "name", "url", "abs_url",
                "entry", "created_at", "removed_old",
            })
            self.assertNotIn("project", body)
            self.assertNotIn("version", body)
            self.assertTrue(body["project_id"].startswith("p-"))
            ids.append(body["project_id"])
        self.assertEqual(len(set(ids)), 4)
        projects = [p for p in r.load_projects() if p.get("name") == "Curl Title"]
        self.assertEqual(len(projects), 3)
        kept = {p["id"] for p in projects}
        self.assertNotIn(ids[0], kept)
        self.assertTrue(all("project" not in p for p in projects))
        self.assertFalse(os.path.isdir(os.path.join(r.SITES_DIR, ids[0])))
        self.assertTrue(os.path.isdir(os.path.join(r.SITES_DIR, ids[-1])))

    def test_project_slot_is_independent_of_title_retention(self):
        r = self.receiver
        self._start()
        status, body = self._deploy("活动页", {"index.html": "<html>stable</html>"}, project="cook-page")
        self.assertEqual(status, 200, body)
        removed = []
        for i in range(4):
            status, body = self._deploy("活 动页", {"index.html": "<html>t%d</html>" % i})
            self.assertEqual(status, 200, body)
            removed.extend(body["removed_old"])
        self.assertNotIn("cook-page", removed)
        projects = r.load_projects()
        ids = [p["id"] for p in projects]
        self.assertIn("cook-page", ids)
        titled = [p for p in projects if p.get("id") != "cook-page"]
        self.assertEqual(len(titled), 3)
        self.assertTrue(all(not p.get("project") for p in titled))
        with open(os.path.join(r.SITES_DIR, "cook-page", "index.html"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "<html>stable</html>")
        self.assertEqual(len([p for p in projects if p.get("project") == "cook-page"]), 1)

    def test_snapshot_rotate_does_not_delete_current_under_concurrency(self):
        r = self.receiver
        self._start()
        status, body = self._deploy("seed", {"index.html": "V99"}, project="conc-page")
        self.assertEqual(status, 200, body)
        barrier = threading.Barrier(8)
        errors = []
        seen = []
        stop = threading.Event()

        def writer(i):
            try:
                barrier.wait(timeout=5)
                status_i, body_i = self._deploy(
                    "并发%d" % i,
                    {"index.html": "V%02d" % i},
                    project="conc-page",
                )
                if status_i != 200:
                    errors.append("status %s %s" % (status_i, body_i))
                    return
                if body_i.get("url") != "/sites/conc-page/index.html":
                    errors.append("url %s" % body_i.get("url"))
            except Exception as e:  # noqa: BLE001
                errors.append(repr(e))

        def reader():
            live = os.path.join(r.SITES_DIR, "conc-page", "index.html")
            while not stop.is_set():
                try:
                    with open(live, encoding="utf-8") as f:
                        data = f.read()
                except FileNotFoundError:
                    continue
                except OSError:
                    continue
                if not re.fullmatch(r"V\d\d", data or ""):
                    errors.append("partial:%r" % data)
                    return
                seen.append(data)
                try:
                    with open(r.META_FILE, encoding="utf-8") as f:
                        parsed = json.load(f)
                    if not isinstance(parsed, list):
                        errors.append("meta not list")
                        return
                except FileNotFoundError:
                    continue
                except json.JSONDecodeError as e:
                    errors.append("meta corrupt %s" % e)
                    return

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(8)]
        watcher = threading.Thread(target=reader)
        watcher.start()
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=20)
        stop.set()
        watcher.join(timeout=5)
        self.assertEqual(errors, [])
        projects = [p for p in r.load_projects() if p.get("project") == "conc-page"]
        self.assertEqual(len(projects), 1)
        rec = projects[0]
        self.assertEqual(rec["version"], 9)
        self.assertEqual(rec["snapshot_count"], 3)
        root = os.path.join(r.SITES_DIR, "conc-page")
        with open(os.path.join(root, "index.html"), encoding="utf-8") as f:
            live = f.read()
        self.assertRegex(live, r"^V\d\d$")
        self.assertFalse(os.path.isdir(os.path.join(root, "versions", "9")))
        snap_dirs = sorted(
            name for name in os.listdir(os.path.join(root, "versions"))
            if os.path.isdir(os.path.join(root, "versions", name))
        )
        self.assertEqual(snap_dirs, ["6", "7", "8"])
        markers = {live}
        for name in snap_dirs:
            with open(os.path.join(root, "versions", name, "index.html"), encoding="utf-8") as f:
                markers.add(f.read())
        self.assertEqual(len(markers), 4)
        self.assertNotIn("V99", markers)
        staging = os.path.join(r.DATA_DIR, "staging")
        if os.path.isdir(staging):
            self.assertEqual(os.listdir(staging), [])
        self.assertTrue(seen)

    def test_meta_replace_failure_restores_previous_tree(self):
        r = self.receiver
        self._start()
        status, body = self._deploy("v1", {"index.html": "<html>v1</html>"}, project="keep-slug")
        self.assertEqual(status, 200, body)
        with open(r.META_FILE, "rb") as f:
            before = f.read()
        real_replace = r.os.replace

        def boom(src, dst):
            if os.path.abspath(dst) == os.path.abspath(r.META_FILE):
                raise OSError("disk")
            return real_replace(src, dst)

        with mock.patch.object(r.os, "replace", side_effect=boom):
            status, body = self._deploy("v2", {"index.html": "<html>v2</html>"}, project="keep-slug")
        self.assertNotEqual(status, 200, body)
        with open(r.META_FILE, "rb") as f:
            after = f.read()
        self.assertEqual(before, after)
        with open(os.path.join(r.SITES_DIR, "keep-slug", "index.html"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "<html>v1</html>")
        self.assertFalse(os.path.isdir(os.path.join(r.SITES_DIR, "keep-slug", "versions")))
        projects = r.load_projects()
        self.assertEqual(projects[0]["version"], 1)
        leftovers = [name for name in os.listdir(r.META_DIR) if ".tmp." in name]
        self.assertEqual(leftovers, [])
        staging = os.path.join(r.DATA_DIR, "staging")
        if os.path.isdir(staging):
            self.assertEqual(os.listdir(staging), [])

    def test_corrupt_projects_json_is_not_cleared(self):
        r = self.receiver
        r.add_project_record({
            "id": "p-keep",
            "name": "keep",
            "description": "t",
            "type": "html",
            "entry": "index.html",
            "created_at": "2026-01-01 00:00:00",
            "url": "/sites/p-keep/index.html",
        })
        broken = b"{not-json"
        with open(r.META_FILE, "wb") as f:
            f.write(broken)
        with self.assertRaises(RuntimeError):
            r.load_projects()
        self._start()
        status, body = self._deploy("x", {"index.html": "<html>a</html>"})
        self.assertEqual(status, 500, body)
        status, body = self._deploy("x", {"index.html": "<html>b</html>"}, project="cook-page")
        self.assertEqual(status, 500, body)
        with open(r.META_FILE, "rb") as f:
            after = f.read()
        self.assertEqual(after, broken)
        self.assertNotEqual(after.strip(), b"[]")
        self.assertFalse(os.path.isdir(os.path.join(r.SITES_DIR, "cook-page")))

    def test_versions_payload_and_foreign_dir_do_not_clobber(self):
        r = self.receiver
        self._start()
        status, body = self._deploy("v1", {"index.html": "<html>v1</html>"}, project="safe-slug")
        self.assertEqual(status, 200, body)
        status, body = self._deploy(
            "v2",
            {"index.html": "<html>v2</html>", "versions/evil.html": "pwn"},
            project="safe-slug",
        )
        self.assertEqual(status, 400, body)
        with open(os.path.join(r.SITES_DIR, "safe-slug", "index.html"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "<html>v1</html>")
        self.assertFalse(os.path.exists(os.path.join(r.SITES_DIR, "safe-slug", "versions", "evil.html")))
        self.assertEqual(r.load_projects()[0]["version"], 1)

        orphan = os.path.join(r.SITES_DIR, "manual-slug")
        os.makedirs(orphan, exist_ok=True)
        with open(os.path.join(orphan, "marker.txt"), "w", encoding="utf-8") as f:
            f.write("keep")
        status, body = self._deploy("x", {"index.html": "<html>no</html>"}, project="manual-slug")
        self.assertEqual(status, 400, body)
        with open(os.path.join(orphan, "marker.txt"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "keep")

        taken = os.path.join(r.SITES_DIR, "taken-slug")
        os.makedirs(taken, exist_ok=True)
        with open(os.path.join(taken, "index.html"), "w", encoding="utf-8") as f:
            f.write("old")
        r.add_project_record({
            "id": "taken-slug",
            "name": "占用",
            "description": "t",
            "type": "html",
            "entry": "index.html",
            "created_at": "2026-04-01 00:00:00",
            "url": "/sites/taken-slug/index.html",
        })
        status, body = self._deploy("x", {"index.html": "<html>no</html>"}, project="taken-slug")
        self.assertEqual(status, 400, body)
        with open(os.path.join(taken, "index.html"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "old")

    def test_mcp_project_reuses_url(self):
        self._start()
        first = self._mcp_deploy({
            "project": "mcp-cook",
            "project_name": "首页收敛版",
            "description": "第一轮",
            "html": "<html>one</html>",
        })
        second = self._mcp_deploy({
            "project": "mcp-cook",
            "project_name": "首页7套配色",
            "description": "第二轮",
            "html": "<html>two</html>",
        })
        self.assertEqual(first[0], 200, first[1])
        self.assertEqual(second[0], 200, second[1])
        text1 = first[1]["result"]["content"][0]["text"]
        text2 = second[1]["result"]["content"][0]["text"]
        self.assertNotIn("isError", first[1]["result"])
        self.assertFalse(second[1]["result"].get("isError"))
        self.assertIn("/sites/mcp-cook/index.html", text1)
        self.assertIn("/sites/mcp-cook/index.html", text2)
        self.assertIn("版本: 2", text2)
        self.assertIn("快照: 1", text2)
        root = os.path.join(self.receiver.SITES_DIR, "mcp-cook")
        with open(os.path.join(root, "index.html"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "<html>two</html>")
        with open(os.path.join(root, "versions", "1", "index.html"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "<html>one</html>")
        slotted = [p for p in self.receiver.load_projects() if p.get("project") == "mcp-cook"]
        self.assertEqual(len(slotted), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
