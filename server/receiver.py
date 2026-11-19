#!/usr/bin/env python3
"""
static-deploy 接收与元数据管理服务。
纯 Python 3 标准库：HTTP API + 远程 MCP（streamable HTTP / JSON-RPC 2.0）。
"""

import base64
import http.server
import io
import json
import os
import pathlib
import re
import secrets
import shutil
import socketserver
import stat
import threading
import time
import urllib.parse
import zipfile

DATA_DIR = os.environ.get("DATA_DIR", "/data")
SITES_DIR = os.path.join(DATA_DIR, "sites")
META_DIR = os.path.join(DATA_DIR, "meta")
META_FILE = os.path.join(META_DIR, "projects.json")
CLEANUP_LOG = os.path.join(META_DIR, "cleanup.log")
# 覆盖写的临时树放在站点目录外。nginx 只挂 /sites/，半成品不会被访问到。
STAGING_DIR = os.path.join(DATA_DIR, "staging")
API_TOKEN = os.environ.get("API_TOKEN", "") or ""
PORT = int(os.environ.get("PORT", "8089"))
# 同一归一化标题最多保留的版本数。部署写入时顺带清理，不另起常驻任务。
KEEP_PER_TITLE = 3
# 稳定 project 的历史快照份数。当前版在站点根，不计入这 3 份。
KEEP_SNAPSHOTS = 3
PROJECT_SLUG_MAX = 64
VERSIONS_DIRNAME = "versions"
_PROJECT_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")

os.environ.setdefault("TZ", "Asia/Shanghai")
if hasattr(time, "tzset"):
    time.tzset()

MAX_BODY_BYTES = 100 * 1024 * 1024
MAX_CONTENT_BYTES = 20 * 1024 * 1024


def _env_positive_int(name, default):
    """读取正整数环境变量。未设置、空串或非法值时用 default。"""
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        value = int(str(raw).strip(), 10)
    except ValueError:
        return default
    if value <= 0:
        return default
    return value


# 解压防护。HTTP Content-Length 只约束压缩后的请求体，压缩比没有上限，
# 所以这三个值必须在解压过程中生效。同名环境变量可覆盖，便于以后调整。
ZIP_MAX_TOTAL_BYTES = _env_positive_int("ZIP_MAX_TOTAL_BYTES", 2 * 1024 * 1024 * 1024)
ZIP_MAX_SINGLE_BYTES = _env_positive_int("ZIP_MAX_SINGLE_BYTES", 256 * 1024 * 1024)
ZIP_MAX_FILE_COUNT = _env_positive_int("ZIP_MAX_FILE_COUNT", 10000)
ZIP_READ_CHUNK = 1024 * 1024

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
MCP_PROTOCOL_VERSIONS = {"2024-11-05", "2025-03-26", "2025-06-18"}
DEFAULT_PROTOCOL_VERSION = "2025-03-26"
MCP_INSTRUCTIONS = (
    "本服务把静态原型或图片发布成手机可打开的局域网链接。"
    "按体积分流：大内容放进 MCP 参数会按体积消耗 token。"
    "单个 HTML 小于 20KB 用 deploy_static_project 的 html；"
    "纯文本总量小于 200KB 用 files；"
    "解码后小于 3MB 的单张图片用 upload_image。"
    "达到或超过 200KB 的原型、含图片或字体的目录、解码后达到或超过 3MB 的图片，"
    "改用 HTTP POST /api/deploy（zip 或图片原始字节，请求体上限 100MB，内容不进对话）。"
    "MCP 内容硬上限 20MB。服务端读不到调用方磁盘。"
    "迭代修改同一原型必须复用同一个 project slug，主链接才不变；"
    "只有真正不同的方案才不传 project 或另起新 slug。"
)

_meta_lock = threading.Lock()
_project_locks_guard = threading.Lock()
_project_locks = {}

os.makedirs(SITES_DIR, exist_ok=True)
os.makedirs(META_DIR, exist_ok=True)
if not os.path.exists(META_FILE):
    with open(META_FILE, "w", encoding="utf-8") as f:
        json.dump([], f, ensure_ascii=False, indent=2)


def load_projects():
    if not os.path.exists(META_FILE):
        return []
    try:
        with open(META_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            raise ValueError("projects.json 不是列表")
        return data
    except Exception as e:
        # 读失败不得伪装成空列表，否则后续 save 会把真实记录抹掉
        raise RuntimeError("读取 projects.json 失败: %s" % e)


def normalize_title(name):
    """把标题收成可比较的分组键。

    规则：NFKC（全角字母数字与兼容字符折成半角）后去掉全部空白
    （含普通空格、全角空格、换行、制表），再做 Unicode 大小写折叠。
    标点与汉字保留，空标题单独成组。
    """
    import unicodedata

    text = "" if name is None else str(name)
    text = unicodedata.normalize("NFKC", text)
    text = "".join(ch for ch in text if not ch.isspace())
    return text.casefold()


class ProjectSlugError(ValueError):
    """project slug 不合法，或与已有目录冲突。调用方应把它当成 400。"""


def _slug_preview(slug):
    text = slug.replace("\r", "\\r").replace("\n", "\\n")
    if len(text) > 80:
        return text[:80] + "..."
    return text


def validate_project_slug(value):
    """稳定 slug。非法值抛 ProjectSlugError，不改写、不建目录。

    允许小写字母、数字和短横线，长度 1 到 64，且不能以短横线开头或结尾。
    路径分隔符、`..`、绝对路径、大写、下划线、点号一律拒绝。
    """
    if not isinstance(value, str):
        raise ProjectSlugError("project 必须是字符串")
    slug = value.strip()
    if slug == "":
        raise ProjectSlugError("project 不能为空")
    if (
        any(ch in slug for ch in ("/", "\\", "\x00"))
        or slug.startswith("~")
        or ".." in slug
    ):
        raise ProjectSlugError("project 含有路径字符，已拒绝: %s" % _slug_preview(slug))
    if len(slug) > PROJECT_SLUG_MAX:
        raise ProjectSlugError("project 长度超过 %d: %d" % (PROJECT_SLUG_MAX, len(slug)))
    if not _PROJECT_SLUG_RE.fullmatch(slug):
        raise ProjectSlugError(
            "project 只允许小写字母、数字和短横线，长度 1 到 %d，"
            "且不能以短横线开头或结尾。收到: %s" % (PROJECT_SLUG_MAX, _slug_preview(slug))
        )
    return slug


def _is_project_slot(item):
    if not isinstance(item, dict):
        return False
    project = item.get("project")
    return isinstance(project, str) and project.strip() != ""


def _project_lock(slug):
    with _project_locks_guard:
        lock = _project_locks.get(slug)
        if lock is None:
            lock = threading.Lock()
            _project_locks[slug] = lock
        return lock


def _created_sort_key(record):
    created = record.get("created_at")
    if isinstance(created, str) and created:
        return (1, created)
    return (0, "")


def select_retention(projects, record):
    """同归一化标题只留最新 KEEP_PER_TITLE 条（含即将写入的 record）。

    调用方必须已持有 _meta_lock。排序键是 created_at 字符串（本地时间，
    字典序即时间序）。时间相同时，即将写入的 record 排在旧条前面，
    避免并发下把刚写入的版本当成旧版删掉。
    返回 (新列表, 被移出的旧记录)。新列表仍是「最新在前」。
    """
    key = normalize_title(record.get("name"))
    group = []
    others = []
    for item in projects:
        # 带 project 的稳定槽位不参与按标题清理，避免换标题时把固定链接删掉。
        if _is_project_slot(item):
            others.append(item)
            continue
        if normalize_title(item.get("name")) == key:
            group.append(item)
        else:
            others.append(item)
    incoming = dict(record)
    incoming["_incoming"] = True
    ranked = sorted(
        [incoming] + group,
        key=lambda item: (_created_sort_key(item), 1 if item.get("_incoming") else 0),
        reverse=True,
    )
    kept_group = []
    for item in ranked[:KEEP_PER_TITLE]:
        cleaned = dict(item)
        cleaned.pop("_incoming", None)
        kept_group.append(cleaned)
    removed = ranked[KEEP_PER_TITLE:]
    return kept_group + others, removed


def _unlink_quiet(path):
    try:
        os.unlink(path)
    except OSError:
        pass


def save_projects(projects):
    tmp_file = META_FILE + ".tmp." + secrets.token_hex(4)
    try:
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(projects, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_file, META_FILE)
    except Exception:
        _unlink_quiet(tmp_file)
        raise


def append_cleanup_log(removed_ids, kept_ids):
    """追加一行 JSON。先把这一行写入临时文件再拼到日志末尾。

    已有行只被读取后原样保留。追加中断时临时文件被删掉，
    cleanup.log 里已经落盘的行不被改写。
    """
    line = json.dumps(
        {
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "removed_ids": list(removed_ids),
            "kept_ids": list(kept_ids),
        },
        ensure_ascii=False,
    )
    payload = (line + "\n").encode("utf-8")
    tmp_file = CLEANUP_LOG + ".tmp." + secrets.token_hex(4)
    try:
        with open(tmp_file, "wb") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        with open(CLEANUP_LOG, "ab") as dest:
            with open(tmp_file, "rb") as src:
                shutil.copyfileobj(src, dest)
            dest.flush()
            os.fsync(dest.fileno())
    except Exception:
        _unlink_quiet(tmp_file)
        raise
    _unlink_quiet(tmp_file)


def remove_project_dir(project_id):
    """只删除 id 形如已登记项目的站点目录。不跟随符号链接。"""
    if not project_id or not isinstance(project_id, str):
        return False
    if not re.fullmatch(r"[a-zA-Z0-9_\-]+", project_id):
        return False
    project_dir = os.path.join(SITES_DIR, project_id)
    if not os.path.lexists(project_dir):
        return False
    if os.path.islink(project_dir):
        return False
    if not os.path.isdir(project_dir):
        return False
    shutil.rmtree(project_dir)
    return True


def add_project_record(record):
    """写入新记录并按标题保留最新 KEEP_PER_TITLE 版。

    顺序：锁内改 meta（原子替换）然后锁外删旧目录，再记 cleanup.log。
    meta 替换失败时旧列表与全部目录都还在。目录已删但日志追加失败时，
    返回值里的 removed_old 仍然是这次删掉的 id。
    带 project 的稳定槽位走 publish_project，不进这里。
    """
    if _is_project_slot(record):
        raise ValueError("稳定 project 记录不能走按标题保留")
    with _meta_lock:
        projects = load_projects()
        new_projects, removed = select_retention(projects, record)
        save_projects(new_projects)
    removed_ids = [item.get("id") for item in removed if item.get("id")]
    for project_id in removed_ids:
        try:
            remove_project_dir(project_id)
        except Exception as e:
            sys_stderr = __import__("sys").stderr
            sys_stderr.write("[cleanup] 删除目录失败 %s: %s\n" % (project_id, e))
    kept_ids = [
        item.get("id")
        for item in new_projects
        if item.get("id")
        and normalize_title(item.get("name")) == normalize_title(record.get("name"))
    ]
    if removed_ids:
        try:
            append_cleanup_log(removed_ids, kept_ids)
        except Exception as e:
            sys_stderr = __import__("sys").stderr
            sys_stderr.write("[cleanup] 写 cleanup.log 失败: %s\n" % e)
    return new_projects, removed_ids


def _rmtree_quiet(path):
    if not path or not os.path.lexists(path):
        return
    if os.path.islink(path):
        _unlink_quiet(path)
        return
    shutil.rmtree(path, ignore_errors=True)


def _site_dir(slug):
    """slug 已经过校验。仍要求结果是 SITES_DIR 的直接子目录。"""
    live = os.path.abspath(os.path.join(SITES_DIR, slug))
    root = os.path.abspath(SITES_DIR)
    if os.path.dirname(live) != root or os.path.basename(live) != slug:
        raise ProjectSlugError("project 路径越界")
    return live


def _find_project_slot(projects, slug):
    for item in projects:
        if isinstance(item, dict) and item.get("id") == slug and item.get("project") == slug:
            return item
    return None


def _same_project_slot(item, slug):
    if not isinstance(item, dict):
        return False
    return item.get("id") == slug or item.get("project") == slug


def _record_version(record):
    if not record:
        return 0
    value = record.get("version")
    if isinstance(value, bool):
        return 1
    if isinstance(value, int) and value >= 1:
        return value
    if isinstance(value, str) and value.isdigit() and int(value) >= 1:
        return int(value)
    return 1


def _project_conflict(projects, slug, live):
    if os.path.islink(live):
        return "拒绝覆盖符号链接: %s" % slug
    for item in projects:
        if not isinstance(item, dict):
            continue
        if item.get("id") == slug and item.get("project") != slug:
            return "project 与已有站点 id 冲突，该 id 不是稳定 project: %s" % slug
        if item.get("project") == slug and item.get("id") != slug:
            return "project 记录的 id 与 slug 不一致: %s" % slug
    if _find_project_slot(projects, slug) is None and os.path.lexists(live):
        return "目录已存在但 meta 中没有该 project，拒绝覆盖: %s" % slug
    return None


def _project_commit_conflict(projects, slug, previous):
    """目录已经换完，这里只核对 meta，不再用目录是否存在判断冲突。"""
    for item in projects:
        if not isinstance(item, dict):
            continue
        if item.get("id") == slug and item.get("project") != slug:
            return "project 与已有站点 id 冲突: %s" % slug
        if item.get("project") == slug and item.get("id") != slug:
            return "project 记录的 id 与 slug 不一致: %s" % slug
    current = _find_project_slot(projects, slug)
    if previous is None:
        if current is not None:
            return "project 在写入期间被占用: %s" % slug
        return None
    if current is None:
        return "project 记录在写入期间消失: %s" % slug
    if _record_version(current) != _record_version(previous):
        return "project 版本在写入期间变化: %s" % slug
    return None


def _copy_tree(src, dst, skip_top_name=None):
    """把 src 拷进 dst。跳过符号链接。文件先写临时名再 os.replace。"""
    src = os.path.abspath(src)
    dst = os.path.abspath(dst)
    os.makedirs(dst, exist_ok=True)
    for dirpath, dirnames, filenames in os.walk(src, followlinks=False):
        rel = os.path.relpath(dirpath, src)
        kept = []
        for name in dirnames:
            if rel == "." and skip_top_name and name == skip_top_name:
                continue
            if os.path.islink(os.path.join(dirpath, name)):
                continue
            kept.append(name)
        dirnames[:] = kept
        if rel == ".":
            target_dir = dst
        else:
            target_dir = os.path.join(dst, rel)
            if not is_within_dir(target_dir, dst):
                dirnames[:] = []
                continue
            os.makedirs(target_dir, exist_ok=True)
        for name in filenames:
            src_file = os.path.join(dirpath, name)
            if os.path.islink(src_file) or not os.path.isfile(src_file):
                continue
            target = os.path.join(target_dir, name)
            if not is_within_dir(target, dst):
                continue
            tmp = target + ".partial." + secrets.token_hex(3)
            try:
                shutil.copyfile(src_file, tmp)
                os.replace(tmp, target)
            except Exception:
                _unlink_quiet(tmp)
                raise


def _live_has_payload(live):
    if os.path.islink(live) or not os.path.isdir(live):
        return False
    for name in os.listdir(live):
        if name != VERSIONS_DIRNAME:
            return True
    return False


def _disk_snapshot_versions(live):
    vdir = os.path.join(live, VERSIONS_DIRNAME)
    if os.path.islink(vdir) or not os.path.isdir(vdir):
        return []
    found = []
    for name in os.listdir(vdir):
        if not re.fullmatch(r"[1-9][0-9]{0,8}", name):
            continue
        path = os.path.join(vdir, name)
        if os.path.islink(path) or not os.path.isdir(path):
            continue
        found.append(int(name))
    found.sort()
    return found


def _snapshot_url(slug, version, entry):
    entry = (entry or "index.html").replace("\\", "/").lstrip("/")
    return "/sites/%s/%s/%s/%s" % (slug, VERSIONS_DIRNAME, version, entry)


def _stage_history(staging, live, slug, previous):
    """把上一版正文和仍要保留的快照放进 staging/versions。当前正文不进快照。"""
    if previous is None:
        return [], []
    prev_version = _record_version(previous)
    meta_by_ver = {}
    for item in previous.get("snapshots") or []:
        if not isinstance(item, dict):
            continue
        try:
            ver = int(item.get("version"))
        except (TypeError, ValueError):
            continue
        if ver < 1:
            continue
        entry = item.get("entry") or previous.get("entry") or "index.html"
        meta_by_ver[ver] = {
            "version": ver,
            "created_at": item.get("created_at") or "",
            "entry": entry,
            "name": item.get("name") or "",
            "url": _snapshot_url(slug, ver, entry),
        }
    created = False
    if _live_has_payload(live):
        dest = os.path.join(staging, VERSIONS_DIRNAME, str(prev_version))
        _copy_tree(live, dest, skip_top_name=VERSIONS_DIRNAME)
        entry = previous.get("entry") or "index.html"
        meta_by_ver[prev_version] = {
            "version": prev_version,
            "created_at": previous.get("updated_at") or previous.get("created_at") or "",
            "entry": entry,
            "name": previous.get("name") or "",
            "url": _snapshot_url(slug, prev_version, entry),
        }
        created = True
    disk_versions = _disk_snapshot_versions(live) if os.path.isdir(live) and not os.path.islink(live) else []
    all_versions = set(disk_versions)
    if created:
        all_versions.add(prev_version)
    ordered = sorted(all_versions)
    kept = ordered[-KEEP_SNAPSHOTS:] if len(ordered) > KEEP_SNAPSHOTS else ordered
    removed = [ver for ver in ordered if ver not in kept]
    kept_set = set(kept)
    for ver in kept:
        if created and ver == prev_version:
            continue
        src = os.path.join(live, VERSIONS_DIRNAME, str(ver))
        if os.path.isdir(src) and not os.path.islink(src):
            _copy_tree(src, os.path.join(staging, VERSIONS_DIRNAME, str(ver)))
        if ver not in meta_by_ver:
            entry = previous.get("entry") or "index.html"
            meta_by_ver[ver] = {
                "version": ver,
                "created_at": "",
                "entry": entry,
                "name": previous.get("name") or "",
                "url": _snapshot_url(slug, ver, entry),
            }
    snapshots = [meta_by_ver[ver] for ver in sorted(kept_set, reverse=True) if ver in meta_by_ver]
    return snapshots, removed


def _rollback_uncommitted(live, staging, trash, hold, moved_live, moved_in):
    """把站点目录恢复成换目录之前。新树挪走后删除，旧树从 trash 搬回。"""
    if moved_in and os.path.lexists(live):
        if os.path.lexists(hold):
            _rmtree_quiet(hold)
        os.replace(live, hold)
    if moved_live and os.path.lexists(trash) and not os.path.lexists(live):
        os.replace(trash, live)
    _rmtree_quiet(hold)
    _rmtree_quiet(staging)
    if os.path.lexists(trash) and os.path.lexists(live):
        _rmtree_quiet(trash)


def _commit_project_record(record, previous):
    slug = record["project"]
    with _meta_lock:
        projects = load_projects()
        conflict = _project_commit_conflict(projects, slug, previous)
        if conflict:
            raise ProjectSlugError(conflict)
        others = [item for item in projects if not _same_project_slot(item, slug)]
        save_projects([record] + others)


def publish_project(slug, populate, describe):
    """用固定 slug 覆盖站点根，并把上一版转成快照。

    同一 slug 的并发部署串行。新内容先写到 DATA_DIR/staging（nginx 不挂载），
    再用 os.replace 换成完整目录，避免站点根出现半份文件。
    meta 仍是临时文件加 os.replace。meta 失败时把目录换回去。
    快照只留最近 KEEP_SNAPSHOTS 份，轮转只删 versions/<旧号>，不碰当前正文。
    """
    slug = validate_project_slug(slug)
    live = _site_dir(slug)
    lock = _project_lock(slug)
    with lock:
        with _meta_lock:
            projects = load_projects()
            conflict = _project_conflict(projects, slug, live)
            if conflict:
                raise ProjectSlugError(conflict)
            previous = _find_project_slot(projects, slug)

        os.makedirs(STAGING_DIR, exist_ok=True)
        token = secrets.token_hex(4)
        staging = os.path.join(STAGING_DIR, "%s-%s" % (slug, token))
        trash = os.path.join(STAGING_DIR, "trash-%s-%s" % (slug, token))
        hold = os.path.join(STAGING_DIR, "hold-%s-%s" % (slug, token))
        moved_live = False
        moved_in = False
        rolled_back = False

        def rollback_once():
            nonlocal moved_live, moved_in, rolled_back
            if rolled_back:
                return
            _rollback_uncommitted(live, staging, trash, hold, moved_live, moved_in)
            moved_live = False
            moved_in = False
            rolled_back = True

        try:
            os.makedirs(staging)
            populate(staging)
            if os.path.lexists(os.path.join(staging, VERSIONS_DIRNAME)):
                raise ProjectSlugError("部署内容不能包含保留目录 versions")
            fields = describe(staging)
            for key in ("name", "description", "type", "entry"):
                if not isinstance(fields.get(key), str) or fields.get(key) == "":
                    raise ToolError("发布字段缺失: %s" % key)
            snapshots, removed = _stage_history(staging, live, slug, previous)
            if os.path.lexists(live):
                os.replace(live, trash)
                moved_live = True
            os.replace(staging, live)
            moved_in = True
            now = time.strftime("%Y-%m-%d %H:%M:%S")
            created = now
            if previous and isinstance(previous.get("created_at"), str) and previous.get("created_at"):
                created = previous["created_at"]
            prev_version = _record_version(previous) if previous else 0
            record = {
                "id": slug,
                "project": slug,
                "name": fields["name"],
                "description": fields["description"],
                "type": fields["type"],
                "entry": fields["entry"],
                "created_at": created,
                "updated_at": now,
                "url": "/sites/%s/%s" % (slug, fields["entry"]),
                "version": (prev_version + 1) if previous else 1,
                "snapshot_count": len(snapshots),
                "snapshots": snapshots,
            }
            try:
                _commit_project_record(record, previous)
            except Exception:
                rollback_once()
                raise
        except Exception:
            try:
                rollback_once()
            except Exception as restore_error:
                raise RuntimeError("发布失败且回滚目录失败: %s" % restore_error)
            raise
        _rmtree_quiet(trash)
        record["removed_old"] = []
        record["removed_snapshots"] = removed
        return record


def _html_fields(staging, name, description, entry_file):
    saved = resolve_entry(staging, entry_file)
    if not saved:
        raise ToolError("未找到可用的 HTML 入口（根目录 entry_file / 深度不超过 2 的 index.html 或 .html）")
    return {
        "name": name,
        "description": description,
        "type": "html",
        "entry": saved,
    }


def _image_fields(staging, name, description, img_name):
    path = os.path.join(staging, img_name)
    if os.path.islink(path) or not os.path.isfile(path) or not is_within_dir(path, staging):
        raise ToolError("图片未写入")
    return {
        "name": name,
        "description": description,
        "type": "image",
        "entry": img_name,
    }


def deploy_response(record, host):
    """不带 project 时键集合与原来一致。带 project 时追加版本和快照。"""
    body = {
        "success": True,
        "project_id": record["id"],
        "name": record["name"],
        "url": record["url"],
        "abs_url": abs_url(record["url"], host),
        "entry": record["entry"],
        "created_at": record["created_at"],
        "removed_old": record.get("removed_old") or [],
    }
    if record.get("project"):
        body["project"] = record["project"]
        body["version"] = record["version"]
        body["snapshot_count"] = record["snapshot_count"]
        body["snapshots"] = record.get("snapshots") or []
        body["updated_at"] = record.get("updated_at") or record.get("created_at")
        body["removed_snapshots"] = record.get("removed_snapshots") or []
    return body


def delete_project_record(project_id):
    with _meta_lock:
        projects = load_projects()
        target = next((p for p in projects if p.get("id") == project_id), None)
        if not target:
            return None
        new_projects = [p for p in projects if p.get("id") != project_id]
        save_projects(new_projects)
        return target


def _dir_size_bytes(path):
    total = 0
    for root, _dirs, files in os.walk(path, followlinks=False):
        for name in files:
            file_path = os.path.join(root, name)
            if os.path.islink(file_path):
                continue
            try:
                total += os.path.getsize(file_path)
            except OSError:
                continue
    return total


def project_size_bytes(project_id):
    if not project_id or not isinstance(project_id, str):
        return 0
    if not re.fullmatch(r"[a-zA-Z0-9_\-]+", project_id):
        return 0
    project_dir = os.path.join(SITES_DIR, project_id)
    if os.path.islink(project_dir) or not os.path.isdir(project_dir):
        return 0
    return _dir_size_bytes(project_dir)


def scan_orphans():
    """sites 下有目录、meta 里没有对应 id 的条目。只报告，不删除。

    符号链接与非目录项不算孤儿目录。meta 读失败时向上抛，避免把全体项目报成孤儿。
    """
    projects = load_projects()
    known = set()
    for item in projects:
        project_id = item.get("id")
        if isinstance(project_id, str) and project_id:
            known.add(project_id)
    if not os.path.isdir(SITES_DIR):
        return []
    found = []
    for name in os.listdir(SITES_DIR):
        if name in known:
            continue
        path = os.path.join(SITES_DIR, name)
        if os.path.islink(path) or not os.path.isdir(path):
            continue
        try:
            mtime = int(os.stat(path).st_mtime)
        except OSError:
            mtime = 0
        found.append({
            "name": name,
            "size_bytes": _dir_size_bytes(path),
            "mtime": mtime,
        })
    found.sort(key=lambda item: item["name"])
    return found


def meta_disk_status():
    """meta 中每个 id 都有对应站点目录，且没有孤儿目录，才算一致。"""
    projects = load_projects()
    orphans = scan_orphans()
    missing = False
    for item in projects:
        project_id = item.get("id")
        if not isinstance(project_id, str) or not project_id:
            missing = True
            continue
        if not re.fullmatch(r"[a-zA-Z0-9_\-]+", project_id):
            missing = True
            continue
        path = os.path.join(SITES_DIR, project_id)
        if os.path.islink(path) or not os.path.isdir(path):
            missing = True
    consistent = (not missing) and len(orphans) == 0
    return consistent, len(orphans)


def abs_url(path, host):
    """用请求 Host 拼绝对地址，禁止硬编码 host，禁止返回本地路径。"""
    if not path:
        path = "/"
    if path.startswith("http://") or path.startswith("https://"):
        return path
    if not path.startswith("/"):
        path = "/" + path
    host = (host or "").strip()
    if not host:
        host = "127.0.0.1:8088"
    if "://" in host:
        return host.rstrip("/") + path
    return "http://" + host + path


def public_host(headers):
    xf_host = (headers.get("X-Forwarded-Host") or "").split(",")[0].strip()
    if xf_host:
        host = xf_host
    else:
        host = (headers.get("Host") or "").strip()
    if not host:
        return host
    bare = host.rsplit("]", 1)[-1]
    if ":" not in bare:
        port = (headers.get("X-Forwarded-Port") or "").strip()
        if port and port not in ("80", "443"):
            host = host + ":" + port
    return host


def decode_header_value(value, default=""):
    """把项目 header 解成 Unicode，并对结果再调用一次保持不变。

    http.server 按 latin-1 解码 header 字节。同一逻辑字符串有三种到达形态：
    (a) 纯 ASCII 或已是正确 Unicode；(b) UTF-8 原始字节被 latin-1 误解码
    （curl 直接写中文）；(c) percent-encoding（MCP 先 quote），可叠在 (b) 上。

    顺序是「还原字节 → 一次 unquote → 校验 UTF-8」：
    1. latin-1 编码能取回原始字节时，若这些字节是合法 UTF-8 就按 UTF-8 解码。
       码位大于 U+00FF 的字符串不可能来自 latin-1，原样保留。于是 (b) 还原成
       逻辑字符串，(a) 与已经还原过的结果都是不动点。
    2. 再对连续的 %HH 做一次 percent-decode，且仅当这段正好是
       urllib.parse.quote(解码结果)（十六进制大小写不敏感）并且结果是合法
       UTF-8 时才采纳。MCP 只 quote 一次，这一层刚好还原；字面量 "%41"
       不是 quote("A")，会留下，因此已解码结果再解一次不变。(c) 与 (a)(b)
       得到同一个字符串。混合串 "%E5%BE%80%E6%9D%A5原型" 里，百分号段是 quote("往来")，
       原文段原样接上，结果是「往来原型」。
    3. 非法 UTF-8（如 %FF）、quote 不会产生的转义（如 %2e%2e%2f）保持字面量。
       去掉 NUL。空白结果或任何异常返回 default。不会抛异常。
    """
    if value is None:
        return default
    try:
        if isinstance(value, bytes):
            try:
                text = value.decode("utf-8")
            except UnicodeDecodeError:
                text = value.decode("latin-1", errors="replace")
        elif isinstance(value, str):
            text = value
        else:
            text = str(value)
    except Exception:
        return default

    try:
        text = _restore_utf8_header(text)
        text = _unquote_utf8_header(text)
        text = _as_utf8_text(text).replace("\x00", "")
    except Exception:
        try:
            text = _as_utf8_text(text).replace("\x00", "")
        except Exception:
            return default
    if not isinstance(text, str) or text.strip() == "":
        return default
    return text


def _restore_utf8_header(text):
    """撤销 http.server 的 latin-1 解码。原始字节不是 UTF-8 时保持原字符串。"""
    try:
        raw = text.encode("latin-1")
    except UnicodeEncodeError:
        return text
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return text


def _unquote_once(text):
    """一次 percent-decode。结果不是合法 UTF-8 时返回 (False, text)。"""
    try:
        decoded = urllib.parse.unquote(text, encoding="utf-8", errors="strict")
    except (UnicodeDecodeError, UnicodeEncodeError, ValueError, LookupError):
        return False, text
    except Exception:
        return False, text
    try:
        decoded.encode("utf-8")
    except UnicodeEncodeError:
        return False, text
    return True, decoded


def _is_hex(ch):
    return ch in "0123456789abcdefABCDEF"


def _quote_matches(run, decoded):
    """run 是否正好是 urllib.parse.quote(decoded) 的一层编码。"""
    try:
        requoted = urllib.parse.quote(decoded, safe="/")
    except Exception:
        return False
    return requoted.lower() == run.lower()


def _unquote_utf8_header(text):
    """只反解「quote 一次」的 %HH 段，已经解过的字面量 %HH 保持不动。"""
    if "%" not in text:
        return text
    out = []
    i = 0
    n = len(text)
    changed = False
    while i < n:
        if text[i] == "%" and i + 2 < n and _is_hex(text[i + 1]) and _is_hex(text[i + 2]):
            j = i
            while j + 2 < n and text[j] == "%" and _is_hex(text[j + 1]) and _is_hex(text[j + 2]):
                j += 3
            run = text[i:j]
            ok, decoded = _unquote_once(run)
            if ok and _quote_matches(run, decoded):
                out.append(decoded)
                changed = True
            else:
                out.append(run)
            i = j
        else:
            out.append(text[i])
            i += 1
    if not changed:
        return text
    return "".join(out)


def _as_utf8_text(text):
    """孤立代理项换成 U+FFFD，避免随后按 UTF-8 写 JSON 时 500。

    不使用 errors=replace：CPython 3.12 会写成 U+FFFD，3.14 对代理项会写成 "?"。
    """
    if not any(0xD800 <= ord(ch) <= 0xDFFF for ch in text):
        return text
    return "".join(
        "�" if 0xD800 <= ord(ch) <= 0xDFFF else ch
        for ch in text
    )


def new_project_id():
    timestamp_str = time.strftime("%Y%m%d-%H%M%S")
    return "p-%s-%s" % (timestamp_str, secrets.token_hex(2))


def sanitize_filename(name):
    return re.sub(r"[^a-zA-Z0-9_\-\.]", "_", os.path.basename(name or ""))


def decode_zip_name(filename):
    try:
        return filename.encode("cp437").decode("utf-8")
    except Exception:
        try:
            return filename.encode("cp437").decode("gbk")
        except Exception:
            return filename


def is_within_dir(target_path, directory):
    directory = os.path.abspath(directory)
    target_path = os.path.abspath(target_path)
    return target_path == directory or target_path.startswith(directory + os.sep)


def safe_join(project_dir, rel):
    if rel is None:
        return None
    if not isinstance(rel, str):
        return None
    rel = rel.replace("\\", "/").strip()
    if not rel or rel.startswith("/") or rel.startswith("~"):
        return None
    posix = pathlib.PurePosixPath(rel)
    if posix.is_absolute() or posix.anchor:
        return None
    parts = posix.parts
    if not parts or any(p in (".", "..") or p == "" for p in parts):
        return None
    target = os.path.abspath(os.path.join(project_dir, *parts))
    if not is_within_dir(target, project_dir):
        return None
    return target


def path_depth(rel):
    rel = rel.replace("\\", "/").lstrip("./")
    if not rel or rel == ".":
        return 0
    return max(0, len(pathlib.PurePosixPath(rel).parts) - 1)


def resolve_entry(project_dir, entry_file):
    """
    根目录精确 entry_file → 根目录任意 index.html
    → 深度 <=2 内任意 index.html → 深度 <=2 内第一个 .html
    返回相对 POSIX 路径；找不到返回 None。
    """
    project_dir = os.path.abspath(project_dir)
    entry_file = (entry_file or "index.html").replace("\\", "/").lstrip("/")

    exact = safe_join(project_dir, entry_file)
    if exact and os.path.isfile(exact):
        return os.path.relpath(exact, project_dir).replace(os.sep, "/")

    html_files = []
    for root, dirs, files in os.walk(project_dir, followlinks=False):
        rel_root = os.path.relpath(root, project_dir).replace(os.sep, "/")
        dir_depth = 0 if rel_root == "." else len(pathlib.PurePosixPath(rel_root).parts)
        if dir_depth > 2:
            dirs[:] = []
            continue
        dirs[:] = [d for d in dirs if d not in (".", "..")]
        for name in files:
            if not name.lower().endswith(".html"):
                continue
            full = os.path.join(root, name)
            if os.path.islink(full) or not os.path.isfile(full):
                continue
            rel = os.path.relpath(full, project_dir).replace(os.sep, "/")
            if path_depth(rel) <= 2:
                html_files.append(rel)
        dirs.sort()
    html_files.sort()

    root_index = [p for p in html_files if path_depth(p) == 0 and os.path.basename(p).lower() == "index.html"]
    if root_index:
        return root_index[0]
    nested_index = [p for p in html_files if os.path.basename(p).lower() == "index.html"]
    if nested_index:
        nested_index.sort(key=lambda p: (path_depth(p), p))
        return nested_index[0]
    if html_files:
        html_files.sort(key=lambda p: (path_depth(p), p))
        return html_files[0]
    return None


class ZipLimitError(Exception):
    """解压超过总量、单文件或文件数上限。message 同时包含上限值和建议做法。"""

    def __init__(self, message, advice, limit_bytes=None, limit_count=None):
        super().__init__(message)
        self.message = message
        self.advice = advice
        self.limit_bytes = limit_bytes
        self.limit_count = limit_count

    def to_dict(self):
        body = {"error": self.message, "advice": self.advice}
        if self.limit_bytes is not None:
            body["limit_bytes"] = self.limit_bytes
        if self.limit_count is not None:
            body["limit_count"] = self.limit_count
        return body


def _bytes_label(n):
    if n % (1024 * 1024 * 1024) == 0 and n >= 1024 * 1024 * 1024:
        return "%d 字节（%dGB）" % (n, n // (1024 * 1024 * 1024))
    if n % (1024 * 1024) == 0 and n >= 1024 * 1024:
        return "%d 字节（%dMB）" % (n, n // (1024 * 1024))
    if n % 1024 == 0 and n >= 1024:
        return "%d 字节（%dKB）" % (n, n // 1024)
    return "%d 字节" % n


def _zip_limit_advice_tail():
    return (
        "解压后总量上限 %s，单文件上限 %s，文件数上限 %d，HTTP 请求体上限 %s。"
        % (
            _bytes_label(ZIP_MAX_TOTAL_BYTES),
            _bytes_label(ZIP_MAX_SINGLE_BYTES),
            ZIP_MAX_FILE_COUNT,
            _bytes_label(MAX_BODY_BYTES),
        )
    )


def _total_limit_error():
    limit = _bytes_label(ZIP_MAX_TOTAL_BYTES)
    advice = (
        "请删掉不需要的大资源，或把原型拆成多个项目，分别 POST /api/deploy 上传。"
        "每个 zip 的请求体还要小于 %s。%s"
        % (_bytes_label(MAX_BODY_BYTES), _zip_limit_advice_tail())
    )
    message = "解压后总体积超过上限 %s。已中止并删除未完成的目录。%s" % (limit, advice)
    return ZipLimitError(message, advice=advice, limit_bytes=ZIP_MAX_TOTAL_BYTES)


def _single_limit_error():
    limit = _bytes_label(ZIP_MAX_SINGLE_BYTES)
    advice = (
        "请把该文件压到上限以内，或从 zip 中移除后再 POST /api/deploy。%s"
        % _zip_limit_advice_tail()
    )
    message = "解压时单个文件超过上限 %s。已中止并删除未完成的目录。%s" % (limit, advice)
    return ZipLimitError(message, advice=advice, limit_bytes=ZIP_MAX_SINGLE_BYTES)


def _count_limit_error(kind):
    extra = "空文件也计数。" if kind == "文件数" else ""
    advice = (
        "请减少包内%s后再 POST /api/deploy。%s%s"
        % (kind, extra, _zip_limit_advice_tail())
    )
    message = "解压%s超过上限 %d。已中止并删除未完成的目录。%s" % (
        kind,
        ZIP_MAX_FILE_COUNT,
        advice,
    )
    return ZipLimitError(message, advice=advice, limit_count=ZIP_MAX_FILE_COUNT)


def _mcp_content_limit_message():
    return (
        "内容总量超过上限 %s。"
        "MCP 会把 files 或 html 放进 JSON-RPC 参数，体积按 token 计费，不适合大文件。"
        "请改用 HTTP 直传：在调用方机器上把目录打成 zip，POST /api/deploy，"
        "请求头带上 X-Project-Name、X-Project-Desc、X-Project-Type: html、X-Entry-File。"
        "请求体上限 %s，内容不进对话。"
        "示例：curl -sS -X POST \"http://<主机>:8088/api/deploy\" "
        "-H \"X-Project-Name: 名称\" -H \"X-Project-Desc: 描述\" "
        "-H \"X-Project-Type: html\" -H \"X-Entry-File: index.html\" --data-binary @site.zip"
        % (_bytes_label(MAX_CONTENT_BYTES), _bytes_label(MAX_BODY_BYTES))
    )


def _image_limit_message():
    return (
        "图片解码后超过上限 %s。"
        "请改用 HTTP 直传原始字节：POST /api/deploy，"
        "请求头 X-Project-Type: image，X-Entry-File 为文件名（例如 poster.png），"
        "请求体是图片原始字节，上限 %s。"
        "示例：curl -sS -X POST \"http://<主机>:8088/api/deploy\" "
        "-H \"X-Project-Name: 名称\" -H \"X-Project-Desc: 描述\" "
        "-H \"X-Project-Type: image\" -H \"X-Entry-File: poster.png\" --data-binary @poster.png"
        % (_bytes_label(MAX_CONTENT_BYTES), _bytes_label(MAX_BODY_BYTES))
    )


def _discard_request_body(handler, length):
    """把超限请求体按块丢掉，再返回 413。

    nginx 开了 proxy_request_buffering off。上游若在读完 body 之前就响应，
    nginx 会回 502，调用方看不到 JSON 里的上限和建议。公开入口的 body 已被
    client_max_body_size 110M 挡住，这里再封顶，避免直连 API 时被超大
    Content-Length 拖住。
    """
    remaining = length if isinstance(length, int) and length > 0 else 0
    remaining = min(remaining, MAX_BODY_BYTES + 16 * 1024 * 1024)
    while remaining > 0:
        chunk = handler.rfile.read(min(remaining, 1024 * 1024))
        if not chunk:
            break
        remaining -= len(chunk)


def _body_limit_payload():
    advice = (
        "把 zip 或图片压到 %s 以下后重新 POST /api/deploy。"
        "单个项目仍然放不下时，拆成多个项目分次上传。"
        "MCP 只适合小内容：文本总量低于 200KB，或解码后低于 3MB 的单张图片。"
        "MCP 内容硬上限是 %s，内容会计入 token。"
        % (_bytes_label(MAX_BODY_BYTES), _bytes_label(MAX_CONTENT_BYTES))
    )
    error = "请求体超过上限 %s。%s" % (_bytes_label(MAX_BODY_BYTES), advice)
    return {"error": error, "limit_bytes": MAX_BODY_BYTES, "advice": advice}


def _rollback_project_dir(project_dir):
    """只删除 SITES_DIR 的直接子目录，避免误删数据根。"""
    if not project_dir or not isinstance(project_dir, str):
        return
    root = os.path.abspath(SITES_DIR)
    target = os.path.abspath(project_dir)
    if target == root:
        return
    try:
        if os.path.commonpath([root, target]) != root:
            return
    except ValueError:
        return
    if os.path.dirname(target) != root:
        return
    if os.path.islink(target):
        try:
            os.unlink(target)
        except OSError:
            return
        return
    if os.path.isdir(target):
        shutil.rmtree(target, ignore_errors=True)


def _plan_zip_entries(archive, project_dir):
    """列出将落盘的目录和文件。符号链接与越界路径沿用原行为：跳过，不计数。"""
    directories = []
    files = []
    for member in archive.infolist():
        filename = decode_zip_name(member.filename)
        if member.is_dir() or filename.endswith("/"):
            target_dir = safe_join(project_dir, filename.rstrip("/"))
            if target_dir:
                directories.append(target_dir)
            continue
        mode = member.external_attr >> 16
        if mode and stat.S_ISLNK(mode):
            continue
        target_path = safe_join(project_dir, filename)
        if not target_path:
            continue
        files.append((member, target_path))
    return directories, files


def _enforce_zip_plan(directories, files):
    """用中央目录做快速拒绝。file_size 是未压缩大小的声明，不是请求体大小。"""
    if len(files) > ZIP_MAX_FILE_COUNT:
        raise _count_limit_error("文件数")
    if len(directories) > ZIP_MAX_FILE_COUNT:
        raise _count_limit_error("目录数")
    declared_total = 0
    for member, _target in files:
        declared = member.file_size
        if not isinstance(declared, int) or declared < 0:
            declared = 0
        if declared > ZIP_MAX_SINGLE_BYTES:
            raise _single_limit_error()
        declared_total += declared
        if declared_total > ZIP_MAX_TOTAL_BYTES:
            raise _total_limit_error()


def _copy_with_limits(source, target, total_so_far):
    """按块把 source 写入 target，返回写入后的累计字节。

    中央目录的 file_size 只是声明。CPython zipfile 通常不会吐出超过该声明的字节，
    但这里仍以实际读到的长度为准：先把这一块算进单文件和总量，确认没有越过上限再写。
    会越限的那一块不写，调用方负责删除 project_dir。
    """
    written = 0
    while True:
        chunk = source.read(ZIP_READ_CHUNK)
        if not chunk:
            return total_so_far + written
        new_written = written + len(chunk)
        new_total = total_so_far + new_written
        if new_written > ZIP_MAX_SINGLE_BYTES:
            raise _single_limit_error()
        if new_total > ZIP_MAX_TOTAL_BYTES:
            raise _total_limit_error()
        target.write(chunk)
        written = new_written


def extract_zip_safely(file_bytes, project_dir):
    try:
        _extract_zip_members(file_bytes, project_dir)
    except Exception:
        _rollback_project_dir(project_dir)
        raise


def _extract_zip_members(file_bytes, project_dir):
    zip_buffer = io.BytesIO(file_bytes)
    with zipfile.ZipFile(zip_buffer, "r") as archive:
        directories, files = _plan_zip_entries(archive, project_dir)
        _enforce_zip_plan(directories, files)
        for target_dir in directories:
            os.makedirs(target_dir, exist_ok=True)
        total = 0
        for member, target_path in files:
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            with archive.open(member) as source, open(target_path, "wb") as target:
                total = _copy_with_limits(source, target, total)


def write_files_map(project_dir, files_map):
    if not isinstance(files_map, dict) or not files_map:
        raise ValueError("files 必须是非空对象")
    planned = []
    total = 0
    for rel, content in files_map.items():
        if not isinstance(rel, str) or not isinstance(content, str):
            raise ValueError("files 的键和值都必须是字符串")
        target = safe_join(project_dir, rel)
        if target is None:
            raise ValueError("非法路径: %s" % rel)
        raw = content.encode("utf-8")
        total += len(raw)
        if total > MAX_CONTENT_BYTES:
            raise ValueError(_mcp_content_limit_message())
        planned.append((target, raw))
    os.makedirs(project_dir, exist_ok=True)
    for target, raw in planned:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as f:
            f.write(raw)


def strip_data_url_base64(value):
    raw = (value or "").strip()
    if raw.lower().startswith("data:") and "," in raw:
        raw = raw.split(",", 1)[1]
    return "".join(raw.split())


def decode_image_base64(value):
    raw = strip_data_url_base64(value)
    if not raw:
        raise ValueError("image_base64 为空")
    try:
        return base64.b64decode(raw, validate=True)
    except Exception:
        try:
            return base64.b64decode(raw)
        except Exception:
            raise ValueError("image_base64 非法")


def success_text(kind, project_name, file_url, host, version=None, snapshot_count=None):
    title = "上传成功" if kind == "image" else "部署成功"
    preview = abs_url(file_url, host)
    board = abs_url("/", host)
    lines = [
        title,
        "项目: %s" % project_name,
        "手机直达: %s" % preview,
        "看板: %s" % board,
    ]
    if version is not None:
        lines.append("版本: %s" % version)
        lines.append("快照: %s" % (0 if snapshot_count is None else snapshot_count))
    return "\n".join(lines)


MCP_TOOLS = [
    {
        "name": "deploy_static_project",
        "description": (
            "部署静态原型并返回手机可打开的直达链接。"
            "files 与 html 会整段进入 JSON-RPC 参数，体积按 token 计费"
            "（实测约 179KB 文本约 5 万 token）。"
            "服务端读不到调用方磁盘，不要传本地路径。files 与 html 必须恰好给一个。"
            "按体积分流："
            "单个 HTML 小于 20KB 时传 html；"
            "纯文本多文件且 UTF-8 总量小于 200KB 时传 files（相对路径到文本）；"
            "文本达到或超过 200KB，或含图片、字体、二进制，或要上传整个目录时，"
            "改用 HTTP 直传。在调用方机器打包 zip，POST /api/deploy 发送原始字节"
            "（不进对话，不消耗 token）。"
            "请求头 X-Project-Name、X-Project-Desc、X-Project-Type: html、"
            "X-Entry-File（默认 index.html）。请求体上限 100MB（104857600 字节）。"
            "示例：curl -sS -X POST \"http://<主机>:8088/api/deploy\" "
            "-H \"X-Project-Name: 名称\" -H \"X-Project-Desc: 描述\" "
            "-H \"X-Project-Type: html\" -H \"X-Entry-File: index.html\" "
            "--data-binary @site.zip。"
            "本工具硬上限：内容总量 20MB（20971520 字节）。超过会被拒绝，并提示改走 HTTP 直传。"
            "迭代修改同一原型必须传同一个 project（稳定 slug），主链接 /sites/<slug>/ 保持不变，"
            "上一版自动转存到 /sites/<slug>/versions/<版本号>/，每个 project 只留最近 3 版快照。"
            "不传 project 时每次生成新 id，按标题保留最新 3 版。"
            "只有真正不同的方案才不传 project，或另起一个新 slug。不要为了同一次迭代去改标题。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {
                    "type": "string",
                    "description": (
                        "稳定项目 slug，可选。迭代同一原型时必须复用同一个值。"
                        "只允许小写字母、数字和短横线，长度 1 到 64，不能以短横线开头或结尾。"
                        "禁止路径字符。非法值会报错而不是另建站点。"
                        "不传则每次新 id，按标题保留最新 3 版。"
                    ),
                },
                "project_name": {
                    "type": "string",
                    "description": "项目名称，给人看的标题。同一 project 下可以改，不会因此换链接。",
                },
                "description": {
                    "type": "string",
                    "description": "项目描述",
                },
                "files": {
                    "type": "object",
                    "description": (
                        "相对路径到文本内容。UTF-8 总量小于 200KB 时使用。"
                        "达到或超过 200KB，或含二进制时，改用 HTTP POST /api/deploy 上传 zip。"
                        "硬上限 20MB（20971520 字节）。"
                    ),
                    "additionalProperties": {"type": "string"},
                },
                "html": {
                    "type": "string",
                    "description": (
                        "单个 HTML 小于 20KB 时使用，等价于 files={\"index.html\": <html>}。"
                        "达到或超过 200KB 改用 HTTP POST /api/deploy 上传 zip。"
                    ),
                },
                "entry_file": {
                    "type": "string",
                    "description": "入口文件相对路径，默认 index.html",
                    "default": "index.html",
                },
            },
            "required": ["project_name", "description"],
        },
    },
    {
        "name": "upload_image",
        "description": (
            "上传一张较小的图片并返回手机可打开的直达链接。"
            "image_base64 会进入 JSON-RPC 参数，base64 比原始字节大约 33%，按 token 计费。"
            "按体积分流："
            "解码后小于 3MB 的单张图片用本工具，filename 扩展名只能是 png、jpg、jpeg、gif、webp、svg，"
            "允许 data:image/png;base64, 前缀；"
            "解码后达到或超过 3MB，或要传多张图时，改用 HTTP 直传原始字节。"
            "POST /api/deploy，请求头 X-Project-Type: image，X-Entry-File 为文件名（例如 poster.png），"
            "请求体是图片原始字节，上限 100MB（104857600 字节）。"
            "示例：curl -sS -X POST \"http://<主机>:8088/api/deploy\" "
            "-H \"X-Project-Name: 名称\" -H \"X-Project-Desc: 描述\" "
            "-H \"X-Project-Type: image\" -H \"X-Entry-File: poster.png\" "
            "--data-binary @poster.png。"
            "本工具硬上限：解码后 20MB（20971520 字节）。超过会被拒绝，并提示改走 HTTP。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "图片标题"},
                "description": {"type": "string", "description": "图片描述"},
                "filename": {"type": "string", "description": "文件名，扩展名须为 png/jpg/jpeg/gif/webp/svg"},
                "image_base64": {
                    "type": "string",
                    "description": (
                        "图片 base64，允许带 data:image/png;base64, 前缀。"
                        "解码后小于 3MB 时使用。达到或超过 3MB 改用 HTTP POST /api/deploy，"
                        "请求头 X-Project-Type: image。解码硬上限 20MB（20971520 字节）。"
                    ),
                },
            },
            "required": ["project_name", "description", "filename", "image_base64"],
        },
    },
    {
        "name": "list_projects",
        "description": (
            "列出最近已部署的静态原型与图片，最多 20 条，每条含手机可打开的绝对链接。"
            "本工具不上传内容。"
            "需要上传时按体积分流：小于 20KB 的单个 HTML，或小于 200KB 的纯文本，"
            "用 deploy_static_project；解码后小于 3MB 的单张图片用 upload_image；"
            "更大的原型或图片用 HTTP POST /api/deploy"
            "（zip 或图片原始字节，请求体上限 100MB，内容不进对话）。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
]


class ToolError(Exception):
    pass


def register_html_project(project_name, description, project_dir, project_id, entry_file, host):
    saved_entry = resolve_entry(project_dir, entry_file)
    if not saved_entry:
        raise ToolError("未找到可用的 HTML 入口（根目录 entry_file / 深度不超过 2 的 index.html 或 .html）")
    relative_url = "/sites/%s/%s" % (project_id, saved_entry)
    created_at = time.strftime("%Y-%m-%d %H:%M:%S")
    record = {
        "id": project_id,
        "name": project_name,
        "description": description,
        "type": "html",
        "entry": saved_entry,
        "created_at": created_at,
        "url": relative_url,
    }
    _projects, removed_ids = add_project_record(record)
    record["removed_old"] = removed_ids
    return record, success_text("html", project_name, relative_url, host)


def register_image_project(project_name, description, project_id, img_name, host):
    relative_url = "/sites/%s/%s" % (project_id, img_name)
    created_at = time.strftime("%Y-%m-%d %H:%M:%S")
    record = {
        "id": project_id,
        "name": project_name,
        "description": description,
        "type": "image",
        "entry": img_name,
        "created_at": created_at,
        "url": relative_url,
    }
    _projects, removed_ids = add_project_record(record)
    record["removed_old"] = removed_ids
    return record, success_text("image", project_name, relative_url, host)


def _optional_project_argument(args):
    """参数缺省或 JSON null 表示不启用稳定 slug。空串和非法值报错。"""
    if "project" not in args or args.get("project") is None:
        return None
    raw = args.get("project")
    if not isinstance(raw, str):
        raise ToolError("project 必须是字符串")
    try:
        return validate_project_slug(raw)
    except ProjectSlugError as e:
        raise ToolError(str(e))


def mcp_deploy_static_project(args, host):
    if not isinstance(args, dict):
        raise ToolError("arguments 必须是对象")
    project_name = args.get("project_name")
    description = args.get("description")
    if not isinstance(project_name, str) or not project_name.strip():
        raise ToolError("project_name 必填")
    if not isinstance(description, str) or not description.strip():
        raise ToolError("description 必填")

    has_files = "files" in args and args.get("files") is not None
    has_html = "html" in args and args.get("html") is not None
    if has_files == has_html:
        raise ToolError("files 与 html 必须恰好给一个")

    entry_file = args.get("entry_file") or "index.html"
    if not isinstance(entry_file, str):
        raise ToolError("entry_file 必须是字符串")

    if has_html:
        html = args.get("html")
        if not isinstance(html, str) or html == "":
            raise ToolError("html 必须是非空字符串")
        files_map = {"index.html": html}
        if not args.get("entry_file"):
            entry_file = "index.html"
    else:
        files_map = args.get("files")
        if not isinstance(files_map, dict):
            raise ToolError("files 必须是对象")
        if not files_map:
            raise ToolError("files 不能为空")

    slug = _optional_project_argument(args)
    if slug:
        def populate(dest, files_map=files_map):
            write_files_map(dest, files_map)

        def describe(dest, entry_file=entry_file, project_name=project_name, description=description):
            return _html_fields(dest, project_name, description, entry_file)

        try:
            record = publish_project(slug, populate, describe)
        except ToolError:
            raise
        except ValueError as e:
            raise ToolError(str(e))
        text = success_text(
            "html", project_name, record["url"], host, record.get("version"), record.get("snapshot_count")
        )
        return text, record

    project_id = new_project_id()
    project_dir = os.path.join(SITES_DIR, project_id)
    try:
        write_files_map(project_dir, files_map)
        record, text = register_html_project(
            project_name, description, project_dir, project_id, entry_file, host
        )
        return text, record
    except ToolError:
        if os.path.exists(project_dir):
            shutil.rmtree(project_dir, ignore_errors=True)
        raise
    except ValueError as e:
        if os.path.exists(project_dir):
            shutil.rmtree(project_dir, ignore_errors=True)
        raise ToolError(str(e))
    except Exception:
        if os.path.exists(project_dir):
            shutil.rmtree(project_dir, ignore_errors=True)
        raise


def mcp_upload_image(args, host):
    if not isinstance(args, dict):
        raise ToolError("arguments 必须是对象")
    for key in ("project_name", "description", "filename", "image_base64"):
        if key not in args or args.get(key) in (None, ""):
            raise ToolError("%s 必填" % key)
        if not isinstance(args.get(key), str):
            raise ToolError("%s 必须是字符串" % key)

    filename = args["filename"]
    img_name = sanitize_filename(filename)
    ext = os.path.splitext(img_name)[1].lower()
    if ext not in IMAGE_EXTS:
        raise ToolError("扩展名不在白名单: %s" % ext)

    try:
        img_bytes = decode_image_base64(args["image_base64"])
    except ValueError as e:
        raise ToolError(str(e))
    if len(img_bytes) > MAX_CONTENT_BYTES:
        raise ToolError(_image_limit_message())
    if not img_bytes:
        raise ToolError("图片内容为空")

    project_id = new_project_id()
    project_dir = os.path.join(SITES_DIR, project_id)
    try:
        os.makedirs(project_dir, exist_ok=True)
        img_path = os.path.join(project_dir, img_name)
        if not is_within_dir(img_path, project_dir):
            raise ToolError("非法文件名")
        with open(img_path, "wb") as f:
            f.write(img_bytes)
        record, text = register_image_project(
            args["project_name"], args["description"], project_id, img_name, host
        )
        return text, record
    except ToolError:
        if os.path.exists(project_dir):
            shutil.rmtree(project_dir, ignore_errors=True)
        raise
    except Exception:
        if os.path.exists(project_dir):
            shutil.rmtree(project_dir, ignore_errors=True)
        raise


def mcp_list_projects(host):
    projects = load_projects()[:20]
    if not projects:
        return "暂无已部署项目"
    lines = []
    for p in projects:
        name = p.get("name", "未命名")
        created = p.get("updated_at") or p.get("created_at") or ""
        url = abs_url(p.get("url", "/"), host)
        if p.get("project"):
            lines.append("- %s (v%s, %s) %s" % (name, p.get("version") or 1, created, url))
        else:
            lines.append("- %s (%s) %s" % (name, created, url))
    return "\n".join(lines)


class DeployHandler(http.server.BaseHTTPRequestHandler):
    server_version = "StaticDeployReceiver/1.0"

    def log_message(self, fmt, *args):
        sys_stderr = __import__("sys").stderr
        sys_stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))
        sys_stderr.flush()

    def _apply_cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type, Accept, Authorization, Mcp-Session-Id, MCP-Protocol-Version, "
            "X-Project, X-Project-Name, X-Project-Desc, X-Project-Type, X-Entry-File",
        )
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Expose-Headers", "Mcp-Session-Id")

    def _send_json(self, status_code, data, extra_headers=None):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._apply_cors()
        if extra_headers:
            for k, v in extra_headers:
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _send_empty(self, status_code, extra_headers=None):
        self.send_response(status_code)
        self.send_header("Content-Length", "0")
        self._apply_cors()
        if extra_headers:
            for k, v in extra_headers:
                self.send_header(k, v)
        self.end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self._apply_cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _auth_enabled(self):
        return bool(API_TOKEN)

    def _check_auth(self):
        if not self._auth_enabled():
            return True
        auth_header = self.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return False
        token = auth_header[7:].strip()
        try:
            return secrets.compare_digest(token, API_TOKEN)
        except Exception:
            return False

    def _host(self):
        return public_host(self.headers)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/mcp":
            self.send_response(405)
            self.send_header("Allow", "POST, DELETE")
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self._apply_cors()
            body = json.dumps({"error": "Method Not Allowed"}, ensure_ascii=False).encode("utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if parsed.path in ("/api/health", "/health"):
            try:
                consistent, orphan_count = meta_disk_status()
            except Exception as e:
                self._send_json(500, {"error": str(e)})
                return
            self._send_json(200, {
                "status": "ok",
                "timestamp": int(time.time()),
                "meta_disk_consistent": consistent,
                "orphan_count": orphan_count,
            })
            return

        if parsed.path == "/api/orphans":
            try:
                orphans = scan_orphans()
            except Exception as e:
                self._send_json(500, {"error": str(e)})
                return
            self._send_json(200, orphans)
            return

        if parsed.path == "/api/projects":
            host = self._host()
            try:
                raw_projects = load_projects()
            except Exception as e:
                self._send_json(500, {"error": str(e)})
                return
            projects = []
            for p in raw_projects:
                rec = dict(p)
                rec["abs_url"] = abs_url(p.get("url", "/"), host)
                rec["size_bytes"] = project_size_bytes(p.get("id"))
                projects.append(rec)
            self._send_json(200, projects)
            return

        self._send_json(404, {"error": "Not Found"})

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/mcp":
            self._handle_mcp()
            return
        if parsed.path != "/api/deploy":
            self._send_json(404, {"error": "Not Found"})
            return
        self._handle_deploy()

    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/mcp":
            self._send_empty(204)
            return

        match = re.match(r"^/api/projects/([a-zA-Z0-9_\-]+)$", parsed.path)
        if not match:
            self._send_json(404, {"error": "Not Found"})
            return

        if not self._check_auth():
            self._send_json(401, {"error": "Unauthorized"})
            return

        project_id = match.group(1)
        # 先确认 id 在 meta 里再删目录。命名孤儿不在 meta 中，这里返回 404，目录保留。
        target = delete_project_record(project_id)
        if not target:
            self._send_json(404, {"error": "Project not found", "id": project_id})
            return

        try:
            remove_project_dir(project_id)
        except Exception as e:
            self._send_json(500, {"error": "目录删除失败: %s" % e, "id": project_id})
            return
        self._send_json(200, {"success": True, "deleted_id": project_id})

    def _handle_deploy(self):
        if not self._check_auth():
            self._send_json(401, {"error": "Unauthorized: 认证 Token 错误或缺失"})
            return

        project_type = (self.headers.get("X-Project-Type", "html") or "html").lower()
        entry_file = self.headers.get("X-Entry-File", "index.html") or "index.html"
        try:
            project_name = decode_header_value(self.headers.get("X-Project-Name"), "未命名项目")
            project_desc = decode_header_value(self.headers.get("X-Project-Desc"), "无描述")
        except Exception:
            project_name = "未命名项目"
            project_desc = "无描述"

        content_length = int(self.headers.get("Content-Length", 0) or 0)
        if content_length <= 0:
            self._send_json(400, {"error": "Empty body"})
            return
        if content_length > MAX_BODY_BYTES:
            _discard_request_body(self, content_length)
            self.close_connection = True
            self._send_json(413, _body_limit_payload(), extra_headers=[("Connection", "close")])
            return

        file_bytes = self.rfile.read(content_length)
        host = self._host()
        raw_project = self.headers.get("X-Project")
        if raw_project is not None:
            try:
                project_slug = validate_project_slug(raw_project)
            except ProjectSlugError as e:
                self._send_json(400, {"error": str(e)})
                return
            self._deploy_into_project(
                project_slug, project_type, entry_file, project_name, project_desc, file_bytes, host
            )
            return

        project_id = new_project_id()
        project_dir = os.path.join(SITES_DIR, project_id)
        os.makedirs(project_dir, exist_ok=True)

        try:
            if project_type == "image":
                img_name = sanitize_filename(entry_file or "image.png")
                if not img_name:
                    raise ValueError("非法文件名")
                img_path = os.path.join(project_dir, img_name)
                if not is_within_dir(img_path, project_dir):
                    raise ValueError("非法文件名")
                with open(img_path, "wb") as f:
                    f.write(file_bytes)
                record, _text = register_image_project(
                    project_name, project_desc, project_id, img_name, host
                )
            else:
                extract_zip_safely(file_bytes, project_dir)
                record, _text = register_html_project(
                    project_name, project_desc, project_dir, project_id, entry_file, host
                )

            self._send_json(200, deploy_response(record, host))
        except ZipLimitError as e:
            _rollback_project_dir(project_dir)
            self._send_json(400, e.to_dict())
        except ToolError as e:
            _rollback_project_dir(project_dir)
            self._send_json(400, {"error": str(e)})
        except Exception as e:
            _rollback_project_dir(project_dir)
            self._send_json(500, {"error": "处理失败: %s" % str(e)})

    def _deploy_into_project(self, slug, project_type, entry_file, project_name, project_desc, file_bytes, host):
        try:
            if project_type == "image":
                img_name = sanitize_filename(entry_file or "image.png")
                if not img_name:
                    raise ValueError("非法文件名")

                def populate(dest, img_name=img_name, file_bytes=file_bytes):
                    img_path = os.path.join(dest, img_name)
                    if not is_within_dir(img_path, dest):
                        raise ValueError("非法文件名")
                    with open(img_path, "wb") as f:
                        f.write(file_bytes)

                def describe(dest, img_name=img_name):
                    return _image_fields(dest, project_name, project_desc, img_name)
            else:
                def populate(dest, file_bytes=file_bytes):
                    extract_zip_safely(file_bytes, dest)

                def describe(dest, entry_file=entry_file):
                    return _html_fields(dest, project_name, project_desc, entry_file)

            record = publish_project(slug, populate, describe)
            self._send_json(200, deploy_response(record, host))
        except ZipLimitError as e:
            self._send_json(400, e.to_dict())
        except ProjectSlugError as e:
            self._send_json(400, {"error": str(e)})
        except ToolError as e:
            self._send_json(400, {"error": str(e)})
        except ValueError as e:
            self._send_json(400, {"error": str(e)})
        except Exception as e:
            self._send_json(500, {"error": "处理失败: %s" % str(e)})

    def _mcp_session_headers(self):
        incoming = (self.headers.get("Mcp-Session-Id") or "").strip()
        if incoming:
            session_id = incoming
        else:
            session_id = secrets.token_hex(8)
        return session_id, [("Mcp-Session-Id", session_id)]

    def _wants_sse(self):
        accept = (self.headers.get("Accept") or "").lower()
        if "application/json" in accept:
            return False
        return "text/event-stream" in accept

    def _send_mcp_payload(self, status_code, payload, session_headers, as_sse=None):
        if as_sse is None:
            as_sse = self._wants_sse()
        raw = json.dumps(payload, ensure_ascii=False)
        if as_sse:
            body = ("event: message\ndata: %s\n\n" % raw).encode("utf-8")
            content_type = "text/event-stream"
        else:
            body = raw.encode("utf-8")
            content_type = "application/json; charset=utf-8"
        self.send_response(status_code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self._apply_cors()
        for k, v in session_headers:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _handle_mcp(self):
        session_id, session_headers = self._mcp_session_headers()
        content_length = int(self.headers.get("Content-Length", 0) or 0)
        if content_length > MAX_BODY_BYTES:
            _discard_request_body(self, content_length)
            self.close_connection = True
            limited = _body_limit_payload()
            self._send_mcp_payload(
                413,
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": -32600,
                        "message": limited["error"],
                        "data": {
                            "limit_bytes": limited["limit_bytes"],
                            "advice": limited["advice"],
                        },
                    },
                },
                session_headers + [("Connection", "close")],
                as_sse=False,
            )
            return

        body = self.rfile.read(content_length) if content_length > 0 else b""
        try:
            req = json.loads(body.decode("utf-8") if body else "")
        except Exception:
            self._send_mcp_payload(
                200,
                {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}},
                session_headers,
            )
            return

        if not isinstance(req, dict):
            self._send_mcp_payload(
                200,
                {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}},
                session_headers,
            )
            return

        method = req.get("method")
        msg_id = req.get("id", None)
        has_id = "id" in req and req.get("id") is not None

        if isinstance(method, str) and method.startswith("notifications/"):
            self._send_empty(202, session_headers)
            return
        if not has_id:
            self._send_empty(202, session_headers)
            return

        if not isinstance(method, str) or not method:
            self._send_mcp_payload(
                200,
                {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32600, "message": "Invalid Request"}},
                session_headers,
            )
            return

        try:
            result = self._dispatch_mcp(method, req.get("params"), msg_id)
        except McpRpcError as e:
            self._send_mcp_payload(
                200,
                {"jsonrpc": "2.0", "id": msg_id, "error": {"code": e.code, "message": e.message}},
                session_headers,
            )
            return
        except Exception as e:
            self._send_mcp_payload(
                200,
                {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32603, "message": str(e)}},
                session_headers,
            )
            return

        self._send_mcp_payload(
            200,
            {"jsonrpc": "2.0", "id": msg_id, "result": result},
            session_headers,
        )

    def _dispatch_mcp(self, method, params, msg_id):
        host = self._host()
        if method == "initialize":
            if params is None:
                params = {}
            if not isinstance(params, dict):
                raise McpRpcError(-32602, "Invalid params")
            requested = params.get("protocolVersion")
            if requested in MCP_PROTOCOL_VERSIONS:
                version = requested
            else:
                version = DEFAULT_PROTOCOL_VERSION
            return {
                "protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "static-deploy", "version": "1.0.0"},
                "instructions": MCP_INSTRUCTIONS,
            }

        if method == "ping":
            return {}

        if method == "tools/list":
            return {"tools": MCP_TOOLS}

        if method == "tools/call":
            if not isinstance(params, dict):
                raise McpRpcError(-32602, "Invalid params")
            name = params.get("name")
            if not isinstance(name, str) or not name:
                raise McpRpcError(-32602, "Invalid params: missing tool name")
            if "arguments" not in params:
                raise McpRpcError(-32602, "Invalid params: missing arguments")
            arguments = params.get("arguments")
            if arguments is None:
                arguments = {}
            if not isinstance(arguments, dict):
                raise McpRpcError(-32602, "Invalid params: arguments must be object")
            return self._call_tool(name, arguments, host)

        raise McpRpcError(-32601, "Method not found: %s" % method)

    def _call_tool(self, name, arguments, host):
        try:
            if name == "deploy_static_project":
                text, _record = mcp_deploy_static_project(arguments, host)
            elif name == "upload_image":
                text, _record = mcp_upload_image(arguments, host)
            elif name == "list_projects":
                text = mcp_list_projects(host)
            else:
                raise McpRpcError(-32602, "Unknown tool: %s" % name)
            return {"content": [{"type": "text", "text": text}]}
        except ToolError as e:
            return {
                "content": [{"type": "text", "text": str(e)}],
                "isError": True,
            }


class McpRpcError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


if __name__ == "__main__":
    server_address = ("0.0.0.0", PORT)
    httpd = ThreadingHTTPServer(server_address, DeployHandler)
    print(
        "[static-deploy] 监听 0.0.0.0:%s 数据目录=%s 鉴权=%s "
        "解压上限 total=%s single=%s files=%s"
        % (
            PORT,
            DATA_DIR,
            "on" if API_TOKEN else "off",
            ZIP_MAX_TOTAL_BYTES,
            ZIP_MAX_SINGLE_BYTES,
            ZIP_MAX_FILE_COUNT,
        ),
        flush=True,
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已退出", flush=True)
