#!/usr/bin/env python3
"""skillctl: 技能注册表通用客户端。

真源只有 index.json（v2）。线上文件用顶层字段 ``schema: 2``，
任务书示例用顶层 ``version: 2``，两者都接受。
本地 ``.skillctl-manifest.json`` 只是安装记录。

每个文件先写入临时文件，sha256 与索引一致后才原子改名到目标路径。
校验失败时不创建技能目录，也不保留半截文件。
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import shutil
import socket
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

DEFAULT_INDEX = "http://100.64.0.88:8088/.well-known/skills/index.json"
MANIFEST_NAME = ".skillctl-manifest.json"
USER_AGENT = "skillctl/1"

# 与分发端 nginx 白名单同一字符集，从源头拒绝路径穿越。
NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,127}$")
VERSION_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._+-]{0,63}$")
FILE_PART_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")

MAX_INDEX_BYTES = 2 * 1024 * 1024
MAX_FILE_BYTES = 8 * 1024 * 1024
SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    "__pycache__",
    ".skillctl-staging",
}


class SkillctlError(Exception):
    """用户可处理的失败。消息写到 stderr，进程以 1 退出。"""


class _RejectRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise SkillctlError(f"拒绝重定向: HTTP {code} {_redact(newurl)}")


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8")
        except (OSError, ValueError):
            pass


def _redact(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    if not parts.username and not parts.password:
        return url
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    return urllib.parse.urlunsplit((parts.scheme, host, parts.path, parts.query, parts.fragment))


def _unlink_quiet(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


def _network_error(url: str, exc: BaseException, *, index: bool) -> SkillctlError:
    prefix = "注册表不可达" if index else "下载失败"
    shown = _redact(url)
    if isinstance(exc, urllib.error.HTTPError):
        return SkillctlError(f"{prefix}: HTTP {exc.code} {shown}")
    reason = exc
    if isinstance(exc, urllib.error.URLError):
        reason = exc.reason
    if isinstance(reason, (TimeoutError, socket.timeout)):
        return SkillctlError(f"{prefix}: 超时 {shown}")
    return SkillctlError(f"{prefix}: {reason} {shown}")


def parse_timeout(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        raise SkillctlError(f"非法超时: {text!r}") from None
    if value != value or value in (float("inf"), float("-inf")):
        raise SkillctlError(f"非法超时: {text!r}")
    if not (value > 0) or value > 600:
        raise SkillctlError(f"超时须大于 0 且不超过 600 秒: {text}")
    return value


def validate_skill_name(name: object) -> str:
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        shown = name if isinstance(name, str) and len(name) <= 80 else repr(name)[:80]
        raise SkillctlError(f"非法技能名: {shown}")
    return name


def validate_version(version: object) -> str:
    if not isinstance(version, str) or not VERSION_RE.fullmatch(version):
        raise SkillctlError(f"非法版本号: {version!r}")
    return version


def validate_rel_path(rel: object) -> str:
    if not isinstance(rel, str):
        raise SkillctlError(f"非法文件路径: {rel!r}")
    if (
        not rel
        or len(rel) > 240
        or "\\" in rel
        or "\x00" in rel
        or rel.startswith(("/", "~"))
    ):
        raise SkillctlError(f"非法文件路径: {rel!r}")
    parts = rel.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise SkillctlError(f"非法文件路径: {rel!r}")
    for part in parts:
        if not FILE_PART_RE.fullmatch(part):
            raise SkillctlError(f"非法文件路径: {rel!r}")
    return rel


def _lex_inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def assert_safe_child(root: Path, rel: str) -> Path:
    rel_path = Path(rel)
    if rel_path.is_absolute() or ".." in rel_path.parts:
        raise SkillctlError(f"路径越界: {rel}")
    final = root / rel_path
    if not _lex_inside(root, final):
        raise SkillctlError(f"路径越界: {final}")
    cur = root
    if cur.is_symlink():
        raise SkillctlError(f"拒绝符号链接: {cur}")
    for part in rel_path.parts:
        cur = cur / part
        if cur.is_symlink():
            raise SkillctlError(f"拒绝符号链接: {cur}")
    return final


def _validate_abs_dir_target(path: str) -> Path:
    raw = Path(path).expanduser()
    if not raw.is_absolute():
        raise SkillctlError(f"需要绝对路径: {path}")
    if raw.is_symlink():
        raise SkillctlError(f"拒绝符号链接目录: {raw}")
    resolved = raw.resolve()
    if resolved == Path("/"):
        raise SkillctlError("拒绝把根目录当作技能目录")
    if resolved.exists() and not resolved.is_dir():
        raise SkillctlError(f"不是目录: {resolved}")
    return resolved


def require_abs_dir(path: str, *, create: bool) -> Path:
    resolved = _validate_abs_dir_target(path)
    if not resolved.exists():
        if not create:
            raise SkillctlError(f"目录不存在: {resolved}")
        resolved.mkdir(parents=True, mode=0o755, exist_ok=True)
    return resolved


def _opener() -> urllib.request.OpenerDirector:
    # 直连注册表。空 ProxyHandler 忽略环境变量里的 HTTP 代理，避免局域网地址被送出代理。
    return urllib.request.build_opener(_RejectRedirect, urllib.request.ProxyHandler({}))


def _read_limited(resp, limit: int, url: str, *, index: bool) -> bytes:
    buf = bytearray()
    while True:
        chunk = resp.read(65536)
        if not chunk:
            break
        if len(buf) + len(chunk) > limit:
            what = "index.json" if index else _redact(url)
            raise SkillctlError(f"响应超过 {limit} 字节: {what}")
        buf += chunk
    return bytes(buf)


def fetch_bytes(url: str, timeout: float, limit: int, *, index: bool) -> bytes:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json" if index else "*/*"},
    )
    try:
        with _opener().open(req, timeout=timeout) as resp:
            status = getattr(resp, "status", None) or resp.getcode()
            if status != 200:
                prefix = "注册表不可达" if index else "下载失败"
                raise SkillctlError(f"{prefix}: HTTP {status} {_redact(url)}")
            return _read_limited(resp, limit, url, index=index)
    except SkillctlError:
        raise
    except urllib.error.HTTPError as exc:
        raise _network_error(url, exc, index=index) from None
    except urllib.error.URLError as exc:
        raise _network_error(url, exc, index=index) from None
    except (TimeoutError, socket.timeout) as exc:
        raise _network_error(url, exc, index=index) from None
    except OSError as exc:
        raise _network_error(url, exc, index=index) from None


def download_file(url: str, dest: Path, timeout: float) -> str:
    """流式写入同目录临时文件。调用方负责在校验失败时删掉目标。"""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    digest = hashlib.sha256()
    dest.parent.mkdir(parents=True, mode=0o755, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".part-", dir=str(dest.parent))
    tmp = Path(tmp_name)
    try:
        with _opener().open(req, timeout=timeout) as resp:
            status = getattr(resp, "status", None) or resp.getcode()
            if status != 200:
                raise SkillctlError(f"下载失败: HTTP {status} {_redact(url)}")
            written = 0
            with os.fdopen(fd, "wb") as fh:
                fd = -1
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > MAX_FILE_BYTES:
                        raise SkillctlError(f"文件超过 {MAX_FILE_BYTES} 字节: {_redact(url)}")
                    digest.update(chunk)
                    fh.write(chunk)
                fh.flush()
                os.fsync(fh.fileno())
        os.chmod(tmp, 0o644)
        os.replace(tmp, dest)
    except SkillctlError:
        _unlink_quiet(tmp)
        raise
    except urllib.error.HTTPError as exc:
        _unlink_quiet(tmp)
        raise _network_error(url, exc, index=False) from None
    except urllib.error.URLError as exc:
        _unlink_quiet(tmp)
        raise _network_error(url, exc, index=False) from None
    except (TimeoutError, socket.timeout) as exc:
        _unlink_quiet(tmp)
        raise _network_error(url, exc, index=False) from None
    except OSError as exc:
        _unlink_quiet(tmp)
        raise SkillctlError(f"下载失败: {exc} {_redact(url)}") from None
    finally:
        if fd >= 0:
            os.close(fd)
    return digest.hexdigest()


def index_root(index_url: str) -> str:
    parts = urllib.parse.urlsplit(index_url)
    if parts.scheme not in ("http", "https"):
        raise SkillctlError(f"不支持的 index 协议: {parts.scheme or '(空)'}")
    if not parts.netloc:
        raise SkillctlError(f"index URL 缺少主机: {index_url}")
    if not parts.path.endswith("/index.json"):
        raise SkillctlError("index URL 必须以 /index.json 结尾")
    root_path = parts.path[: -len("index.json")]
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, root_path, "", ""))


def file_url(index_url: str, name: str, rel: str) -> str:
    root = index_root(index_url)
    segments = [urllib.parse.quote(name, safe="")]
    segments.extend(urllib.parse.quote(part, safe="") for part in rel.split("/"))
    return root + "/".join(segments)


def _normalize_skill(entry: object) -> dict:
    if not isinstance(entry, dict):
        raise SkillctlError("技能条目不是对象")
    name = validate_skill_name(entry.get("name"))
    version = validate_version(entry.get("version"))
    updated_at = entry.get("updated_at")
    if (
        not isinstance(updated_at, str)
        or not updated_at.strip()
        or len(updated_at) > 64
        or "\n" in updated_at
        or "\r" in updated_at
    ):
        raise SkillctlError(f"{name} 的 updated_at 非法")
    files = entry.get("files")
    sha = entry.get("sha256")
    if not isinstance(files, list) or not files:
        raise SkillctlError(f"{name} 缺少 files")
    if not isinstance(sha, dict):
        raise SkillctlError(f"{name} 缺少 sha256")
    norm_files: list[str] = []
    for rel in files:
        norm_files.append(validate_rel_path(rel))
    if len(set(norm_files)) != len(norm_files):
        raise SkillctlError(f"{name} 的 files 有重复")
    if set(norm_files) != set(sha):
        raise SkillctlError(f"{name} 的 files 与 sha256 不一致")
    norm_sha: dict[str, str] = {}
    for rel in norm_files:
        digest = sha[rel]
        if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
            raise SkillctlError(f"{name} 的 sha256 非法: {rel}")
        norm_sha[rel] = digest.lower()
    description = entry.get("description", "")
    if not isinstance(description, str):
        raise SkillctlError(f"{name} 的 description 非法")
    return {
        "name": name,
        "description": description,
        "version": version,
        "updated_at": updated_at,
        "files": norm_files,
        "sha256": norm_sha,
    }


def parse_index(payload: object) -> list[dict]:
    """只接受 v2。线上真源字段是 schema，任务书示例字段是 version。"""
    if not isinstance(payload, dict):
        raise SkillctlError("index.json 不是对象")
    schema = payload.get("schema", None)
    version = payload.get("version", None)
    if schema is None and version is None:
        raise SkillctlError("不支持的 index 格式（仅支持 v2）")
    if schema is not None and schema != 2:
        raise SkillctlError(f"不支持的 index schema: {schema!r}（仅支持 v2）")
    if schema is None and version != 2:
        raise SkillctlError(f"不支持的 index 版本: {version!r}（仅支持 v2）")
    if schema is not None and version is not None and version != 2:
        raise SkillctlError(f"不支持的 index 版本: {version!r}（仅支持 v2）")
    skills = payload.get("skills")
    if not isinstance(skills, list):
        raise SkillctlError("index.json 缺少 skills 数组")
    normalized = [_normalize_skill(item) for item in skills]
    names = [item["name"] for item in normalized]
    if len(set(names)) != len(names):
        dup = sorted({name for name in names if names.count(name) > 1})
        raise SkillctlError(f"index.json 技能名重复: {', '.join(dup)}")
    normalized.sort(key=lambda item: item["name"])
    return normalized


def load_index(index_url: str, timeout: float) -> list[dict]:
    index_root(index_url)
    raw = fetch_bytes(index_url, timeout, MAX_INDEX_BYTES, index=True)
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SkillctlError(f"index.json 不是合法 JSON: {exc}") from None
    return parse_index(payload)


def sha256_file(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise SkillctlError(f"拒绝读取非普通文件: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _path_has_symlink(root: Path, rel: str) -> bool:
    cur = root
    if cur.is_symlink():
        return True
    for part in Path(rel).parts:
        cur = cur / part
        if cur.exists() and cur.is_symlink():
            return True
    return False


def content_drift(folder: Path, remote: dict) -> list[str]:
    """对照远端 sha256 检查磁盘文件。路径上任一符号链接只报告，不跟随读取。"""
    problems: list[str] = []
    for rel, digest in remote["sha256"].items():
        path = folder / rel
        if _path_has_symlink(folder, rel) or not path.is_file():
            problems.append(rel)
            continue
        if not hmac.compare_digest(sha256_file(path), digest):
            problems.append(rel)
    return problems


def atomic_write_json(path: Path, obj: dict) -> None:
    data = json.dumps(obj, ensure_ascii=False, indent=2) + "\n"
    path.parent.mkdir(parents=True, mode=0o755, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".skillctl-manifest-", dir=str(path.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fd = -1
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except Exception:
        _unlink_quiet(tmp)
        raise
    finally:
        if fd >= 0:
            os.close(fd)


def read_manifest(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SkillctlError(f"无法读取安装记录: {path} ({exc})") from None
    if not isinstance(data, dict):
        raise SkillctlError(f"安装记录格式错误: {path}")
    validate_skill_name(data.get("name"))
    validate_version(data.get("version"))
    return data


def discover(root: Path) -> list[tuple[Path, dict]]:
    found: list[tuple[Path, dict]] = []
    root_real = root.resolve()
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(dirpath)
        kept: list[str] = []
        for name in dirnames:
            child = current / name
            if name.startswith(".") or name in SKIP_DIRS or child.is_symlink():
                continue
            kept.append(name)
        dirnames[:] = kept
        if MANIFEST_NAME not in filenames:
            continue
        manifest_path = current / MANIFEST_NAME
        if manifest_path.is_symlink() or not manifest_path.is_file():
            continue
        try:
            current.resolve().relative_to(root_real)
        except (OSError, ValueError):
            continue
        manifest = read_manifest(manifest_path)
        found.append((current, manifest))
    found.sort(key=lambda item: str(item[0]))
    return found


def _find_skill(skills: list[dict], name: str) -> dict:
    matches = [item for item in skills if item["name"] == name]
    if not matches:
        raise SkillctlError(f"注册表中没有技能: {name}")
    return matches[0]


def _stage_skill(index_url: str, skill: dict, staging: Path, timeout: float) -> None:
    """全部文件校验通过后才返回。任一失败由调用方删除 staging。"""
    for rel in skill["files"]:
        dest = assert_safe_child(staging, rel)
        url = file_url(index_url, skill["name"], rel)
        digest = download_file(url, dest, timeout)
        expected = skill["sha256"][rel]
        if not hmac.compare_digest(digest, expected):
            _unlink_quiet(dest)
            raise SkillctlError(
                f"sha256 不匹配: {skill['name']}/{rel}"
                f"（注册表 {expected}，实际 {digest}）。已中止，未写入目标目录"
            )
        # 再读一次临时文件，防止写入后被换掉。
        if not hmac.compare_digest(sha256_file(dest), expected):
            _unlink_quiet(dest)
            raise SkillctlError(f"sha256 不匹配: {skill['name']}/{rel}。已中止，未写入目标目录")


def _backup_path(final: Path, version: str) -> Path:
    validate_version(version)
    return final.with_name(final.name + f".bak-{version}")


def _rollback(created: bool, dest: Path, backups: list[tuple[Path, Path]], new_files: list[Path]) -> None:
    if created:
        shutil.rmtree(dest, ignore_errors=True)
        return
    for path in new_files:
        if path.exists() and not path.is_symlink() and path.is_file():
            _unlink_quiet(path)
    for bak, final in reversed(backups):
        if final.exists() and not final.is_symlink() and final.is_file():
            _unlink_quiet(final)
        if bak.exists() and not bak.is_symlink() and bak.is_file():
            os.replace(bak, final)


def publish_staged(
    staging: Path,
    dest: Path,
    skill: dict,
    *,
    backup_version: str | None,
) -> None:
    """把已校验的暂存树挪进目标目录，然后写 manifest。"""
    if dest.is_symlink():
        raise SkillctlError(f"拒绝符号链接: {dest}")
    created = not dest.exists()
    backups: list[tuple[Path, Path]] = []
    new_files: list[Path] = []
    try:
        dest.mkdir(parents=True, mode=0o755, exist_ok=True)
        if dest.is_symlink() or not dest.is_dir():
            raise SkillctlError(f"拒绝写入: {dest}")
        for rel in skill["files"]:
            src = assert_safe_child(staging, rel)
            final = assert_safe_child(dest, rel)
            if not src.is_file() or src.is_symlink():
                raise SkillctlError(f"暂存文件缺失: {rel}")
            final.parent.mkdir(parents=True, mode=0o755, exist_ok=True)
            if final.exists():
                if final.is_symlink() or not final.is_file():
                    raise SkillctlError(f"拒绝覆盖非普通文件: {final}")
                if backup_version is not None:
                    bak = _backup_path(final, backup_version)
                    if not _lex_inside(dest, bak):
                        raise SkillctlError(f"备份路径越界: {bak}")
                    if bak.exists():
                        if bak.is_symlink() or not bak.is_file():
                            raise SkillctlError(f"备份路径异常: {bak}")
                        bak.unlink()
                    os.replace(final, bak)
                    backups.append((bak, final))
            else:
                new_files.append(final)
            os.replace(src, final)
            os.chmod(final, 0o644)
            got = sha256_file(final)
            if not hmac.compare_digest(got, skill["sha256"][rel]):
                raise SkillctlError(f"落盘后 sha256 不匹配: {rel}")
        manifest = {
            "name": skill["name"],
            "version": skill["version"],
            "updated_at": skill["updated_at"],
            "installed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "files": list(skill["files"]),
            "sha256": {rel: skill["sha256"][rel] for rel in skill["files"]},
        }
        atomic_write_json(dest / MANIFEST_NAME, manifest)
    except Exception:
        _rollback(created, dest, backups, new_files)
        raise


def install_verified(
    dest: Path,
    skill: dict,
    index_url: str,
    timeout: float,
    *,
    backup_version: str | None,
) -> Path:
    """校验通过后写入 dest。dest 的目录名必须等于技能名，避免落到别的路径。"""
    if dest.is_symlink():
        raise SkillctlError(f"拒绝符号链接: {dest}")
    if dest.name != skill["name"]:
        raise SkillctlError(f"目录名与技能名不一致: {dest.name} / {skill['name']}")
    if dest.exists() and not dest.is_dir():
        raise SkillctlError(f"不是目录: {dest}")
    parent = dest.parent
    if not parent.is_dir():
        raise SkillctlError(f"不是目录: {parent}")
    try:
        dest.resolve().relative_to(parent.resolve())
    except (OSError, ValueError):
        raise SkillctlError(f"路径越界: {dest}") from None
    # 暂存目录与目标同一父目录，保证 os.replace 在同一文件系统上。
    staging = Path(tempfile.mkdtemp(prefix=".skillctl-staging-", dir=str(parent)))
    try:
        _stage_skill(index_url, skill, staging, timeout)
        publish_staged(staging, dest, skill, backup_version=backup_version)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return dest.resolve()


def compare_status(folder: Path, manifest: dict, remote: dict) -> str:
    drifted = content_drift(folder, remote)
    if manifest["version"] != remote["version"]:
        return "落后"
    if drifted:
        return "漂移"
    return "一致"


def _needs_work(folder: Path, manifest: dict, remote: dict) -> tuple[bool, bool]:
    version_diff = manifest["version"] != remote["version"]
    drifted = bool(content_drift(folder, remote))
    return version_diff, drifted


def cmd_list(index_url: str, timeout: float, to: str | None) -> int:
    skills = load_index(index_url, timeout)
    local: dict[str, tuple[Path, dict]] = {}
    if to is not None:
        root = require_abs_dir(to, create=False)
        for folder, manifest in discover(root):
            local.setdefault(manifest["name"], (folder, manifest))
    for skill in skills:
        line = f"{skill['name']}  {skill['version']}  {skill['updated_at']}"
        hit = local.get(skill["name"])
        if hit is not None:
            folder, manifest = hit
            status = compare_status(folder, manifest, skill)
            line += f"  本地 {manifest['version']}  {status}"
        print(line)
    return 0


def _existing_version(dest: Path) -> str:
    manifest_path = dest / MANIFEST_NAME
    if not manifest_path.is_file() or manifest_path.is_symlink():
        return ""
    try:
        return " " + read_manifest(manifest_path)["version"]
    except SkillctlError:
        return ""


def cmd_install(index_url: str, timeout: float, name: str, to: str, force: bool) -> int:
    validate_skill_name(name)
    root = require_abs_dir(to, create=True)
    dest = root / name
    if dest.is_symlink():
        raise SkillctlError(f"拒绝符号链接: {dest}")
    if dest.exists() and not force:
        raise SkillctlError(f"已安装 {name}{_existing_version(dest)}。请使用 update 或 --force")
    skill = _find_skill(load_index(index_url, timeout), name)
    final = install_verified(dest, skill, index_url, timeout, backup_version=None)
    verb = "已覆盖安装" if force else "已安装"
    print(f"{verb} {name} {skill['version']} {final}")
    return 0


def _plan_line(name: str, local_ver: str, remote_ver: str, *, drift_only: bool) -> str:
    line = f"{name} → {local_ver} → {remote_ver}"
    if drift_only:
        line += " 漂移（sha256 不一致）"
    return line


def cmd_update(index_url: str, timeout: float, to: str, apply: bool) -> int:
    root = require_abs_dir(to, create=False)
    installed = discover(root)
    if not installed:
        raise SkillctlError(f"目录里没有已安装的技能: {root}")
    remote_by_name = {item["name"]: item for item in load_index(index_url, timeout)}
    pending: list[tuple[Path, dict, dict, bool]] = []
    missing: list[str] = []
    for folder, manifest in installed:
        remote = remote_by_name.get(manifest["name"])
        if remote is None:
            missing.append(f"{manifest['name']} → {manifest['version']} → 远端缺失")
            continue
        version_diff, drifted = _needs_work(folder, manifest, remote)
        if version_diff or drifted:
            pending.append((folder, manifest, remote, version_diff))
    if not pending and not missing:
        # 契约：一致时 stdout 只有这一行。
        sys.stdout.write("已是最新\n")
        return 0
    lines = [
        _plan_line(
            manifest["name"],
            manifest["version"],
            remote["version"],
            drift_only=not version_diff,
        )
        for _folder, manifest, remote, version_diff in pending
    ]
    lines.extend(missing)
    if not apply:
        sys.stdout.write("\n".join(lines) + "\n")
        sys.stdout.write("加 --apply 执行升级\n")
        return 0
    if missing:
        raise SkillctlError("有技能在注册表中不存在，已中止升级: " + "；".join(missing))
    for folder, manifest, remote, version_diff in pending:
        install_verified(
            folder,
            remote,
            index_url,
            timeout,
            backup_version=manifest["version"],
        )
        if version_diff:
            print(f"已升级 {remote['name']} {manifest['version']} → {remote['version']}")
        else:
            print(f"已修复 {remote['name']} {manifest['version']} 漂移")
    return 0


def _copy_self_to_bootstrap(root: Path) -> Path:
    """把 skillctl.py 自身复制到 root / .skillctl / skillctl.py 并赋 755 权限。"""
    skillctl_dir = root / ".skillctl"
    skillctl_dir.mkdir(parents=True, mode=0o755, exist_ok=True)
    dest = skillctl_dir / "skillctl.py"

    src: Path | None = None
    if "__file__" in globals() and globals()["__file__"]:
        candidate = Path(__file__).resolve()
        if candidate.is_file():
            src = candidate
    if src is None and sys.argv and sys.argv[0]:
        candidate = Path(sys.argv[0]).resolve()
        if candidate.is_file():
            src = candidate

    if src is None:
        raise SkillctlError("无法定位 skillctl.py 自身文件路径进行自举复制")

    if src.resolve() == dest.resolve():
        try:
            os.chmod(dest, 0o755)
        except OSError as exc:
            raise SkillctlError(f"设置执行权限失败: {dest} ({exc})") from None
        return dest

    # 临时文件 + 原子替换，避免写入中断留下半截文件
    fd, tmp_name = tempfile.mkstemp(prefix=".part-skillctl-", dir=str(skillctl_dir))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as out_fh, src.open("rb") as in_fh:
            fd = -1
            shutil.copyfileobj(in_fh, out_fh)
            out_fh.flush()
            os.fsync(out_fh.fileno())
        os.chmod(tmp, 0o755)
        os.replace(tmp, dest)
        os.chmod(dest, 0o755)
    except Exception as exc:
        _unlink_quiet(tmp)
        raise SkillctlError(f"自举复制失败: {exc}") from None
    finally:
        if fd >= 0:
            os.close(fd)
    return dest


BOOTSTRAP_DEFAULT_SKILLS = ("skill-distribution", "skill-publisher")


def cmd_bootstrap(index_url: str, timeout: float, to: str, install_all: bool) -> int:
    root = require_abs_dir(to, create=True)
    _copy_self_to_bootstrap(root)

    skills = load_index(index_url, timeout)
    if install_all:
        target_skills = skills
    else:
        target_skills = [_find_skill(skills, name) for name in BOOTSTRAP_DEFAULT_SKILLS]

    for skill in target_skills:
        name = skill["name"]
        dest = root / name
        if dest.is_symlink():
            raise SkillctlError(f"拒绝符号链接: {dest}")
        if dest.exists():
            if not dest.is_dir():
                raise SkillctlError(f"目标不是目录: {dest}")
            print(f"已跳过 {name}{_existing_version(dest)}（已安装）")
            continue
        final = install_verified(dest, skill, index_url, timeout, backup_version=None)
        print(f"已安装 {name} {skill['version']} {final}")

    guide_path = root / "skill-distribution" / "SKILL.md"
    print(f"1. 读 {guide_path} 了解 skillctl 的完整用法（装/升级技能）与 skill-publisher（创建/发布新技能）")
    print("2. 日常用本目录 .skillctl/skillctl.py list/update")
    print("3. update 默认只检测，--apply 才升级")
    return 0


def split_globals(argv: list[str]) -> tuple[str, float, list[str]]:
    index = DEFAULT_INDEX
    timeout = 30.0
    rest: list[str] = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--index":
            if i + 1 >= len(argv):
                raise SkillctlError("缺少 --index 的值")
            index = argv[i + 1]
            i += 2
            continue
        if arg.startswith("--index="):
            index = arg.split("=", 1)[1]
            i += 1
            continue
        if arg == "--timeout":
            if i + 1 >= len(argv):
                raise SkillctlError("缺少 --timeout 的值")
            timeout = parse_timeout(argv[i + 1])
            i += 2
            continue
        if arg.startswith("--timeout="):
            timeout = parse_timeout(arg.split("=", 1)[1])
            i += 1
            continue
        rest.append(arg)
        i += 1
    return index, timeout, rest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="skillctl",
        description="技能注册表客户端。真源是 index.json v2，本地 manifest 只是安装记录。",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    list_cmd = sub.add_parser("list", help="列出注册表技能")
    list_cmd.add_argument("--to", help="本地技能根目录的绝对路径，用于对照安装记录")

    install_cmd = sub.add_parser("install", help="安装一个技能")
    # nargs='?' 让以 "-" 开头的恶意名字落到 unknown，而不是被 argparse 当成缺省参数。
    install_cmd.add_argument("name", nargs="?", help="技能名")
    install_cmd.add_argument("--to", required=True, help="技能根目录的绝对路径")
    install_cmd.add_argument("--force", action="store_true", help="目标已存在时覆盖")

    update_cmd = sub.add_parser("update", help="检查已安装技能，--apply 才升级")
    update_cmd.add_argument("--to", required=True, help="技能根目录的绝对路径")
    update_cmd.add_argument("--apply", action="store_true", help="执行升级并备份旧文件")

    bootstrap_cmd = sub.add_parser("bootstrap", help="一键自举客户端与基础技能")
    bootstrap_cmd.add_argument("--to", required=True, help="技能根目录的绝对路径")
    bootstrap_cmd.add_argument("--all", action="store_true", help="安装注册表全部技能（默认安装 skill-distribution 与 skill-publisher）")
    return parser


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    try:
        _configure_stdio()
        index, timeout, rest = split_globals(argv)
        args, unknown = build_parser().parse_known_args(rest)
        if args.cmd == "install" and args.name is None and len(unknown) == 1:
            args.name = unknown[0]
            unknown = []
        if unknown:
            raise SkillctlError(f"未知参数: {' '.join(unknown)}")
        if args.cmd == "list":
            return cmd_list(index, timeout, args.to)
        if args.cmd == "install":
            if not args.name:
                raise SkillctlError("缺少技能名")
            return cmd_install(index, timeout, args.name, args.to, args.force)
        if args.cmd == "update":
            return cmd_update(index, timeout, args.to, args.apply)
        if args.cmd == "bootstrap":
            return cmd_bootstrap(index, timeout, args.to, args.all)
        raise SkillctlError(f"未知命令: {args.cmd}")
    except SkillctlError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except BrokenPipeError:
        return 0


if __name__ == "__main__":
    sys.exit(main())
