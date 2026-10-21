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
API_TOKEN = os.environ.get("API_TOKEN", "") or ""
PORT = int(os.environ.get("PORT", "8089"))

os.environ.setdefault("TZ", "Asia/Shanghai")
if hasattr(time, "tzset"):
    time.tzset()

MAX_BODY_BYTES = 100 * 1024 * 1024
MAX_CONTENT_BYTES = 20 * 1024 * 1024
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
MCP_PROTOCOL_VERSIONS = {"2024-11-05", "2025-03-26", "2025-06-18"}
DEFAULT_PROTOCOL_VERSION = "2025-03-26"
MCP_INSTRUCTIONS = (
    "本服务可部署静态原型或图片，并返回手机可直接打开的局域网链接。"
    "远程 MCP 只能传内容（files 映射、html 字符串或图片 base64），读不到客户端磁盘。"
    "大文件请改用本机 stdio 客户端或 HTTP API。"
)

_meta_lock = threading.Lock()

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


def save_projects(projects):
    tmp_file = META_FILE + ".tmp"
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(projects, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_file, META_FILE)


def add_project_record(record):
    with _meta_lock:
        projects = load_projects()
        projects.insert(0, record)
        save_projects(projects)
        return projects


def delete_project_record(project_id):
    with _meta_lock:
        projects = load_projects()
        target = next((p for p in projects if p.get("id") == project_id), None)
        if not target:
            return None
        new_projects = [p for p in projects if p.get("id") != project_id]
        save_projects(new_projects)
        return target


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


def extract_zip_safely(file_bytes, project_dir):
    zip_buffer = io.BytesIO(file_bytes)
    with zipfile.ZipFile(zip_buffer, "r") as z:
        for member in z.infolist():
            filename = decode_zip_name(member.filename)
            if member.is_dir() or filename.endswith("/"):
                target_dir = safe_join(project_dir, filename.rstrip("/"))
                if target_dir:
                    os.makedirs(target_dir, exist_ok=True)
                continue
            mode = member.external_attr >> 16
            if mode and stat.S_ISLNK(mode):
                continue
            target_path = safe_join(project_dir, filename)
            if not target_path:
                continue
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            with z.open(member) as source, open(target_path, "wb") as target:
                shutil.copyfileobj(source, target)


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
            raise ValueError("内容总量超过 20MB")
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


def success_text(kind, project_name, file_url, host):
    title = "上传成功" if kind == "image" else "部署成功"
    preview = abs_url(file_url, host)
    board = abs_url("/", host)
    return "%s\n项目: %s\n手机直达: %s\n看板: %s" % (title, project_name, preview, board)


MCP_TOOLS = [
    {
        "name": "deploy_static_project",
        "description": (
            "部署静态原型到局域网服务器，返回手机可打开的直达链接。"
            "远程模式必须传 files（相对路径到文本内容）或 html 字符串，二者恰好给一个。"
            "服务端读不到客户端磁盘，不要传本地路径。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_name": {
                    "type": "string",
                    "description": "项目名称",
                },
                "description": {
                    "type": "string",
                    "description": "项目描述",
                },
                "files": {
                    "type": "object",
                    "description": "相对路径到文件文本内容的映射，例如 {\"index.html\": \"<!doctype html>...\"}",
                    "additionalProperties": {"type": "string"},
                },
                "html": {
                    "type": "string",
                    "description": "单文件 HTML 简写，等价于 files={\"index.html\": <html>}",
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
        "description": "上传图片（base64）到局域网服务器，返回手机可打开的直达链接。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "图片标题"},
                "description": {"type": "string", "description": "图片描述"},
                "filename": {"type": "string", "description": "文件名，扩展名须为 png/jpg/jpeg/gif/webp/svg"},
                "image_base64": {
                    "type": "string",
                    "description": "图片 base64，允许带 data:image/png;base64, 前缀",
                },
            },
            "required": ["project_name", "description", "filename", "image_base64"],
        },
    },
    {
        "name": "list_projects",
        "description": "列出最近已部署的静态原型与图片（最多 20 条），含绝对直达链接。",
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
    add_project_record(record)
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
    add_project_record(record)
    return record, success_text("image", project_name, relative_url, host)


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
        raise ToolError("图片解码后超过 20MB")
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
        created = p.get("created_at", "")
        url = abs_url(p.get("url", "/"), host)
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
            "X-Project-Name, X-Project-Desc, X-Project-Type, X-Entry-File",
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
            self._send_json(200, {"status": "ok", "timestamp": int(time.time())})
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
        target = delete_project_record(project_id)
        if not target:
            self._send_json(404, {"error": "Project not found"})
            return

        project_dir = os.path.join(SITES_DIR, project_id)
        if os.path.exists(project_dir):
            shutil.rmtree(project_dir, ignore_errors=True)
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
            self.close_connection = True
            self._send_json(413, {"error": "Payload Too Large"}, extra_headers=[("Connection", "close")])
            return

        file_bytes = self.rfile.read(content_length)
        project_id = new_project_id()
        project_dir = os.path.join(SITES_DIR, project_id)
        os.makedirs(project_dir, exist_ok=True)
        host = self._host()

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

            self._send_json(200, {
                "success": True,
                "project_id": record["id"],
                "name": record["name"],
                "url": record["url"],
                "abs_url": abs_url(record["url"], host),
                "entry": record["entry"],
                "created_at": record["created_at"],
            })
        except ToolError as e:
            if os.path.exists(project_dir):
                shutil.rmtree(project_dir, ignore_errors=True)
            self._send_json(400, {"error": str(e)})
        except Exception as e:
            if os.path.exists(project_dir):
                shutil.rmtree(project_dir, ignore_errors=True)
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
            self.close_connection = True
            self._send_mcp_payload(
                413,
                {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Payload Too Large"}},
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
        "[static-deploy] 监听 0.0.0.0:%s 数据目录=%s 鉴权=%s"
        % (PORT, DATA_DIR, "on" if API_TOKEN else "off"),
        flush=True,
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已退出", flush=True)
