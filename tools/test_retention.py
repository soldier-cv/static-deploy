#!/usr/bin/env python3
"""保留策略、孤儿扫描、删除护栏与 cleanup.log 的标准库测试。

数据目录由本进程创建在临时路径，不读写 /data。
"""

import io
import json
import os
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
