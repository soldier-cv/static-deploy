#!/usr/bin/env python3
"""skillctl 对抗性测试。全部使用临时目录和本地假注册表，不写真实技能目录。

覆盖：
1. index.json 不可达（404、超时、连接失败）
2. sha256 不匹配时不留半截文件
3. 重复 install 且没有 --force 时拒绝
4. update --apply 连跑两次，第二次无操作
5. 本地文件被改后，update 用 sha256 报告漂移
6. 路径穿越与超长技能名被拒绝
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SKILLCTL = ROOT / "skillctl.py"
INDEX_PATH = "/.well-known/skills/index.json"


def run_cli(args: list[str], timeout: float = 20) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, str(SKILLCTL), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
        env=env,
    )


def _handler_class(state: dict):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):  # noqa: N802
            path = urllib.parse.unquote(urllib.parse.urlparse(self.path).path)
            if path == INDEX_PATH:
                code = state.get("index_status", 200)
                body = b"" if code != 200 else state.get("index_bytes", b"")
                self._send(code, body, "application/json")
                return
            body = state.get("files", {}).get(path)
            if body is None:
                self._send(404, b"missing", "text/plain")
                return
            self._send(200, body, "text/plain; charset=utf-8")

        def _send(self, code: int, body: bytes, content_type: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args) -> None:
            return

    return Handler


class RegistryCase(unittest.TestCase):
    def setUp(self) -> None:
        self.state: dict = {"index_status": 200, "index_bytes": b"", "files": {}}
        self.catalog: list[dict] = []
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _handler_class(self.state))
        self.httpd.daemon_threads = True
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.httpd.server_address[:2]
        self.base = f"http://{host}:{port}/.well-known/skills"
        self.index_url = self.base + "/index.json"
        self.tmp = tempfile.TemporaryDirectory(prefix="skillctl-test-")
        self.to = Path(self.tmp.name) / "skills"
        self.to.mkdir()
        self.assertTrue(self.to.is_absolute())

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.tmp.cleanup()

    def cli(self, *args: str, timeout: float = 20) -> subprocess.CompletedProcess[str]:
        return run_cli(
            ["--index", self.index_url, "--timeout", "5", *args],
            timeout=timeout,
        )

    def upsert(
        self,
        name: str,
        version: str,
        files: dict[str, bytes],
        *,
        kind: str = "schema",
        updated_at: str = "2026-11-12 00:00:00",
        description: str = "demo",
    ) -> None:
        entry = {
            "name": name,
            "description": description,
            "version": version,
            "updated_at": updated_at,
            "files": list(files),
            "sha256": {rel: hashlib.sha256(body).hexdigest() for rel, body in files.items()},
        }
        self.catalog = [item for item in self.catalog if item["entry"]["name"] != name]
        self.catalog.append({"entry": entry, "files": dict(files), "kind": kind})
        self.flush()

    def flush(self) -> None:
        kinds = {item["kind"] for item in self.catalog}
        kind = kinds.pop() if len(kinds) == 1 else "schema"
        payload: dict = {
            "updated_at": "2026-11-12 00:00:00",
            "update_url": self.index_url,
            "install_root": self.base + "/",
            "skills": [item["entry"] for item in self.catalog],
        }
        if kind == "version":
            payload["version"] = 2
        else:
            payload["schema"] = 2
        files: dict[str, bytes] = {}
        for item in self.catalog:
            for rel, body in item["files"].items():
                files[f"/.well-known/skills/{item['entry']['name']}/{rel}"] = body
        self.state["index_status"] = 200
        self.state["index_bytes"] = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.state["files"] = files

    def skill_dir(self, name: str = "alpha") -> Path:
        return self.to / name

    def snapshot(self, root: Path) -> dict[str, bytes]:
        found: dict[str, bytes] = {}
        for path in sorted(root.rglob("*")):
            if path.is_file() and not path.is_symlink():
                found[str(path.relative_to(root))] = path.read_bytes()
        return found

    def test_01_index_404(self) -> None:
        self.state["index_status"] = 404
        proc = self.cli("list")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("注册表不可达", proc.stderr)
        self.assertIn("404", proc.stderr)
        self.assertEqual(proc.stdout, "")
        self.assertEqual(list(self.to.iterdir()), [])

    def test_02_sha256_mismatch_leaves_no_partial(self) -> None:
        good = {
            "SKILL.md": b"# alpha\n",
            "references/guide.md": b"guide\n",
        }
        self.upsert("alpha", "1.0.0", good)
        tampered_key = "/.well-known/skills/alpha/references/guide.md"
        self.state["files"][tampered_key] = b"tampered\n"
        proc = self.cli("install", "alpha", "--to", str(self.to))
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("sha256 不匹配", proc.stderr)
        self.assertIn("未写入目标目录", proc.stderr)
        self.assertFalse(self.skill_dir().exists())
        self.assertEqual(list(self.to.rglob("*")), [])

    def test_03_repeat_install_without_force_refused(self) -> None:
        body = {"SKILL.md": b"# alpha\n", "references/guide.md": b"guide\n"}
        self.upsert("alpha", "1.0.0", body)
        first = self.cli("install", "alpha", "--to", str(self.to))
        self.assertEqual(first.returncode, 0, first.stderr)
        before = self.snapshot(self.skill_dir())
        second = self.cli("install", "alpha", "--to", str(self.to))
        self.assertNotEqual(second.returncode, 0)
        self.assertIn("update", second.stderr)
        self.assertIn("--force", second.stderr)
        self.assertEqual(self.snapshot(self.skill_dir()), before)
        forced = self.cli("install", "alpha", "--to", str(self.to), "--force")
        self.assertEqual(forced.returncode, 0, forced.stderr)
        self.assertIn("已覆盖安装", forced.stdout)
        self.assertEqual((self.skill_dir() / "SKILL.md").read_bytes(), b"# alpha\n")

    def test_04_update_apply_idempotent(self) -> None:
        self.upsert(
            "alpha",
            "1.0.0",
            {"SKILL.md": b"# v1\n", "references/guide.md": b"guide v1\n"},
        )
        installed = self.cli("install", "alpha", "--to", str(self.to))
        self.assertEqual(installed.returncode, 0, installed.stderr)
        self.upsert(
            "alpha",
            "1.1.0",
            {"SKILL.md": b"# v2\n", "references/guide.md": b"guide v2\n"},
            updated_at="2026-11-12 12:00:00",
        )
        detected = self.cli("update", "--to", str(self.to))
        self.assertEqual(detected.returncode, 0, detected.stderr)
        self.assertIn("alpha → 1.0.0 → 1.1.0\n", detected.stdout)
        self.assertIn("加 --apply 执行升级", detected.stdout)
        self.assertEqual((self.skill_dir() / "SKILL.md").read_bytes(), b"# v1\n")
        self.assertEqual(list(self.skill_dir().rglob("*.bak-*")), [])

        applied = self.cli("update", "--to", str(self.to), "--apply")
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertIn("已升级 alpha 1.0.0 → 1.1.0", applied.stdout)
        self.assertEqual((self.skill_dir() / "SKILL.md").read_bytes(), b"# v2\n")
        self.assertEqual((self.skill_dir() / "references" / "guide.md").read_bytes(), b"guide v2\n")
        self.assertEqual((self.skill_dir() / "SKILL.md.bak-1.0.0").read_bytes(), b"# v1\n")
        self.assertEqual(
            (self.skill_dir() / "references" / "guide.md.bak-1.0.0").read_bytes(),
            b"guide v1\n",
        )
        manifest = json.loads((self.skill_dir() / ".skillctl-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["version"], "1.1.0")
        self.assertEqual(manifest["sha256"]["SKILL.md"], hashlib.sha256(b"# v2\n").hexdigest())

        snap = self.snapshot(self.skill_dir())
        again = self.cli("update", "--to", str(self.to), "--apply")
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(again.stdout, "已是最新\n")
        self.assertEqual(again.stderr, "")
        self.assertEqual(self.snapshot(self.skill_dir()), snap)

    def test_05_local_file_drift_detected_by_sha256(self) -> None:
        self.upsert("alpha", "1.0.0", {"SKILL.md": b"# alpha\n", "references/guide.md": b"guide\n"})
        installed = self.cli("install", "alpha", "--to", str(self.to))
        self.assertEqual(installed.returncode, 0, installed.stderr)
        target = self.skill_dir() / "SKILL.md"
        target.write_bytes(b"hacked by hand\n")
        proc = self.cli("update", "--to", str(self.to))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("alpha → 1.0.0 → 1.0.0", proc.stdout)
        self.assertIn("漂移", proc.stdout)
        self.assertIn("sha256", proc.stdout)
        self.assertEqual(target.read_bytes(), b"hacked by hand\n")
        self.assertEqual(list(self.skill_dir().rglob("*.bak-*")), [])
        listed = self.cli("list", "--to", str(self.to))
        self.assertEqual(listed.returncode, 0, listed.stderr)
        self.assertIn("漂移", listed.stdout)
        self.assertIn("本地 1.0.0", listed.stdout)

    def test_06_reject_traversal_and_oversize_name(self) -> None:
        canary = Path(self.tmp.name) / "pwned.md"
        canary.write_text("safe", encoding="utf-8")
        escaped = Path(self.tmp.name) / "escaped"
        names = [
            "../escaped",
            "..",
            ".",
            "../../etc/passwd",
            "/etc/passwd",
            "alpha/../../escaped",
            "alpha\\..\\escaped",
            "a" * 5000,
            "-leading-hyphen",
        ]
        for name in names:
            proc = self.cli("install", name, "--to", str(self.to))
            self.assertNotEqual(proc.returncode, 0, name)
            self.assertIn("非法技能名", proc.stderr, proc.stderr)
            self.assertFalse(escaped.exists(), name)
            self.assertEqual(canary.read_text(encoding="utf-8"), "safe")
            self.assertEqual(list(self.to.iterdir()), [], name)

    def test_07_index_file_path_traversal(self) -> None:
        body = b"pwn"
        payload = {
            "version": 2,
            "skills": [
                {
                    "name": "alpha",
                    "description": "x",
                    "version": "1.0.0",
                    "updated_at": "2026-11-12 00:00:00",
                    "files": ["../../pwned.md"],
                    "sha256": {"../../pwned.md": hashlib.sha256(body).hexdigest()},
                }
            ],
        }
        self.state["index_bytes"] = json.dumps(payload).encode("utf-8")
        self.state["files"]["/.well-known/skills/alpha/../../pwned.md"] = body
        canary = Path(self.tmp.name) / "pwned.md"
        proc = self.cli("install", "alpha", "--to", str(self.to))
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("非法文件路径", proc.stderr)
        self.assertFalse(self.skill_dir().exists())
        self.assertFalse(canary.exists())
        self.assertEqual(list(self.to.rglob("*")), [])

    def test_08_install_references_manifest_list_and_nested_update(self) -> None:
        alpha = {"SKILL.md": b"# alpha\n", "references/guide.md": b"guide\n"}
        beta = {"SKILL.md": b"# beta\n"}
        self.upsert("beta", "2.0.0", beta, updated_at="2026-11-11 01:02:03")
        self.upsert("alpha", "1.0.0", alpha, updated_at="2026-11-12 04:05:06", description="甲")
        category = self.to / "devops"
        category.mkdir()
        installed = self.cli("install", "alpha", "--to", str(category))
        self.assertEqual(installed.returncode, 0, installed.stderr)
        dest = category / "alpha"
        self.assertEqual((dest / "SKILL.md").read_bytes(), b"# alpha\n")
        self.assertEqual((dest / "references" / "guide.md").read_bytes(), b"guide\n")
        self.assertIn(str(dest.resolve()), installed.stdout)
        manifest = json.loads((dest / ".skillctl-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["name"], "alpha")
        self.assertEqual(manifest["version"], "1.0.0")
        self.assertEqual(manifest["updated_at"], "2026-11-12 04:05:06")
        self.assertEqual(manifest["files"], ["SKILL.md", "references/guide.md"])
        self.assertEqual(manifest["sha256"]["references/guide.md"], hashlib.sha256(b"guide\n").hexdigest())
        self.assertIn("installed_at", manifest)
        self.assertRegex(manifest["installed_at"], r"^\d{4}-\d{2}-\d{2}T")

        listed = self.cli("list", "--to", str(self.to))
        self.assertEqual(listed.returncode, 0, listed.stderr)
        text = listed.stdout
        self.assertIn("alpha  1.0.0  2026-11-12 04:05:06  本地 1.0.0  一致", text)
        self.assertIn("beta  2.0.0  2026-11-11 01:02:03", text)
        self.assertNotIn("beta  2.0.0  2026-11-11 01:02:03  本地", text)

        fresh = self.cli("update", "--to", str(self.to))
        self.assertEqual(fresh.returncode, 0, fresh.stderr)
        self.assertEqual(fresh.stdout, "已是最新\n")
        self.assertEqual(fresh.stderr, "")

        direct = self.cli("update", "--to", str(dest))
        self.assertEqual(direct.stdout, "已是最新\n")

        self.upsert("alpha", "1.2.0", alpha, updated_at="2026-11-12 08:00:00")
        behind = self.cli("list", "--to", str(self.to))
        self.assertIn("alpha  1.2.0  2026-11-12 08:00:00  本地 1.0.0  落后", behind.stdout)

    def test_09_schema_not_v2_rejected(self) -> None:
        self.state["index_bytes"] = json.dumps({"schema": 1, "skills": []}).encode("utf-8")
        proc = self.cli("list")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("v2", proc.stderr)

        self.state["index_bytes"] = json.dumps({"skills": []}).encode("utf-8")
        proc = self.cli("list")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("v2", proc.stderr)

    def test_10_version_field_v2_accepted(self) -> None:
        self.upsert("alpha", "1.0.0", {"SKILL.md": b"# from-version\n"}, kind="version")
        proc = self.cli("install", "alpha", "--to", str(self.to))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual((self.skill_dir() / "SKILL.md").read_bytes(), b"# from-version\n")
        # --index 放在子命令后面也生效。
        alt = run_cli(
            ["install", "alpha", "--to", str(self.to), "--force", "--index", self.index_url],
        )
        self.assertEqual(alt.returncode, 0, alt.stderr)

    def test_11_symlink_dest_refused(self) -> None:
        outside = Path(self.tmp.name) / "outside"
        outside.mkdir()
        secret = outside / "secret.txt"
        secret.write_text("keep", encoding="utf-8")
        (self.to / "alpha").symlink_to(outside, target_is_directory=True)
        self.upsert("alpha", "1.0.0", {"SKILL.md": b"# no\n"})
        proc = self.cli("install", "alpha", "--to", str(self.to), "--force")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("符号链接", proc.stderr)
        self.assertEqual(secret.read_text(encoding="utf-8"), "keep")
        self.assertFalse((outside / "SKILL.md").exists())

    def test_12_relative_to_rejected(self) -> None:
        proc = self.cli("install", "alpha", "--to", "skills")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("绝对路径", proc.stderr)


class TestUnreachable(unittest.TestCase):
    def test_timeout(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        port = sock.getsockname()[1]
        stop = threading.Event()

        def hold() -> None:
            try:
                conn, _addr = sock.accept()
            except OSError:
                return
            stop.wait(8)
            try:
                conn.close()
            except OSError:
                pass

        thread = threading.Thread(target=hold, daemon=True)
        thread.start()
        try:
            proc = run_cli(
                ["list", "--index", f"http://127.0.0.1:{port}/index.json", "--timeout", "1"],
                timeout=10,
            )
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("注册表不可达", proc.stderr)
            self.assertIn("超时", proc.stderr)
            self.assertEqual(proc.stdout, "")
        finally:
            stop.set()
            sock.close()

    def test_connection_refused(self) -> None:
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
        proc = run_cli(
            ["list", "--index", f"http://127.0.0.1:{port}/index.json", "--timeout", "2"],
            timeout=8,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("注册表不可达", proc.stderr)
        self.assertEqual(proc.stdout, "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
