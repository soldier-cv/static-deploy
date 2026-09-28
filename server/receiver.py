#!/usr/bin/env python3
"""
静态原型与生图展示中心 - 接收与元数据管理服务 (Deploy Receiver)
纯 Python 3 标准库实现，零外部依赖，常驻内存 < 20MB。
符合 88 服务器规范，处理 ZIP 原型解包、单图上传及 projects.json 元数据维护。
"""

import http.server
import io
import json
import os
import pathlib
import re
import secrets
import shutil
import sys
import time
import urllib.parse
import zipfile

# 环境变量配置
DATA_DIR = os.environ.get("DATA_DIR", "/data")
SITES_DIR = os.path.join(DATA_DIR, "sites")
META_DIR = os.path.join(DATA_DIR, "meta")
META_FILE = os.path.join(META_DIR, "projects.json")
API_TOKEN = os.environ.get("API_TOKEN", "lan-static-preview-token-2026")
PORT = int(os.environ.get("PORT", "8089"))

# 确保目录存在
os.makedirs(SITES_DIR, exist_ok=True)
os.makedirs(META_DIR, exist_ok=True)
if not os.path.exists(META_FILE):
    with open(META_FILE, "w", encoding="utf-8") as f:
        json.dump([], f, ensure_ascii=False, indent=2)


def load_projects():
    """读取所有项目元数据"""
    try:
        with open(META_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_projects(projects):
    """保存项目元数据（原子写入）"""
    tmp_file = META_FILE + ".tmp"
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(projects, f, ensure_ascii=False, indent=2)
    os.replace(tmp_file, META_FILE)


def sanitize_filename(name):
    """过滤文件名防路径遍历"""
    return re.sub(r'[^a-zA-Z0-9_\-\.]', '_', os.path.basename(name))


class DeployHandler(http.server.BaseHTTPRequestHandler):
    server_version = "StaticPreviewReceiver/1.0"

    def _send_json(self, status_code, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-Project-Name, X-Project-Desc, X-Project-Type, X-Entry-File")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        """处理 CORS 预检"""
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-Project-Name, X-Project-Desc, X-Project-Type, X-Entry-File")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.end_headers()

    def _check_auth(self):
        """校验 Authorization Bearer Token"""
        auth_header = self.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return False
        token = auth_header[7:].strip()
        return secrets.compare_digest(token, API_TOKEN)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        
        # 健康检查
        if parsed.path in ("/api/health", "/health"):
            self._send_json(200, {"status": "ok", "timestamp": int(time.time())})
            return

        # 获取项目列表
        if parsed.path == "/api/projects":
            projects = load_projects()
            self._send_json(200, projects)
            return

        self._send_json(404, {"error": "Not Found"})

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)

        if parsed.path != "/api/deploy":
            self._send_json(404, {"error": "Not Found"})
            return

        # 校验 Token
        if not self._check_auth():
            self._send_json(401, {"error": "Unauthorized: 认证 Token 错误或缺失"})
            return

        # 获取头部参数
        raw_name = self.headers.get("X-Project-Name", "未命名项目")
        raw_desc = self.headers.get("X-Project-Desc", "无描述")
        project_type = self.headers.get("X-Project-Type", "html").lower()
        entry_file = self.headers.get("X-Entry-File", "index.html")

        # URL 解码中文参数
        try:
            project_name = urllib.parse.unquote(raw_name)
            project_desc = urllib.parse.unquote(raw_desc)
        except Exception:
            project_name = raw_name
            project_desc = raw_desc

        content_length = int(self.headers.get("Content-Length", 0))
        if content_length <= 0:
            self._send_json(400, {"error": "Empty body"})
            return

        # 读取上传数据
        file_bytes = self.rfile.read(content_length)

        # 生成唯一的项目 ID (时间戳 + 4位随机hex)
        timestamp_str = time.strftime("%Y%m%d-%H%M%S")
        rand_suffix = secrets.token_hex(2)
        project_id = f"p-{timestamp_str}-{rand_suffix}"

        project_dir = os.path.join(SITES_DIR, project_id)
        os.makedirs(project_dir, exist_ok=True)

        try:
            if project_type == "image":
                # 单图处理
                img_name = sanitize_filename(entry_file or "image.png")
                img_path = os.path.join(project_dir, img_name)
                with open(img_path, "wb") as f:
                    f.write(file_bytes)
                relative_url = f"/sites/{project_id}/{img_name}"
                saved_entry = img_name
            else:
                # ZIP 解压处理
                zip_buffer = io.BytesIO(file_bytes)
                with zipfile.ZipFile(zip_buffer, "r") as z:
                    # 安全解压防 Zip Slip
                    for member in z.infolist():
                        # 兼容处理中文路径编码
                        try:
                            filename = member.filename.encode('cp437').decode('utf-8')
                        except Exception:
                            try:
                                filename = member.filename.encode('cp437').decode('gbk')
                            except Exception:
                                filename = member.filename

                        # 规范化路径
                        target_path = os.path.abspath(os.path.join(project_dir, filename))
                        if not target_path.startswith(os.path.abspath(project_dir)):
                            continue # 跳过恶意路径
                        
                        if member.is_dir():
                            os.makedirs(target_path, exist_ok=True)
                        else:
                            os.makedirs(os.path.dirname(target_path), exist_ok=True)
                            with z.open(member) as source, open(target_path, "wb") as target:
                                shutil.copyfileobj(source, target)

                # 确认入口文件
                entry_target = os.path.join(project_dir, entry_file)
                if not os.path.exists(entry_target):
                    # 如果根目录没有入口文件，查找第一层级目录或第一个 html
                    html_files = [f for f in os.listdir(project_dir) if f.lower().endswith(".html")]
                    if html_files:
                        saved_entry = html_files[0]
                    else:
                        saved_entry = entry_file
                else:
                    saved_entry = entry_file

                relative_url = f"/sites/{project_id}/{saved_entry}"

            # 记录元数据
            created_at = time.strftime("%Y-%m-%d %H:%M:%S")
            project_record = {
                "id": project_id,
                "name": project_name,
                "description": project_desc,
                "type": project_type,
                "entry": saved_entry,
                "created_at": created_at,
                "url": relative_url
            }

            projects = load_projects()
            projects.insert(0, project_record) # 最新发布的排在最前面
            save_projects(projects)

            # 返回给客户端
            self._send_json(200, {
                "success": True,
                "project_id": project_id,
                "name": project_name,
                "url": relative_url,
                "created_at": created_at
            })

        except Exception as e:
            # 清理失败目录
            if os.path.exists(project_dir):
                shutil.rmtree(project_dir, ignore_errors=True)
            self._send_json(500, {"error": f"处理失败: {str(e)}"})

    def do_DELETE(self):
        """删除指定项目"""
        parsed = urllib.parse.urlparse(self.path)
        match = re.match(r"^/api/projects/([a-zA-Z0-9_\-]+)$", parsed.path)
        if not match:
            self._send_json(404, {"error": "Not Found"})
            return

        if not self._check_auth():
            self._send_json(401, {"error": "Unauthorized"})
            return

        project_id = match.group(1)
        projects = load_projects()
        target = next((p for p in projects if p["id"] == project_id), None)
        if not target:
            self._send_json(404, {"error": "Project not found"})
            return

        # 从磁盘移除
        project_dir = os.path.join(SITES_DIR, project_id)
        if os.path.exists(project_dir):
            shutil.rmtree(project_dir, ignore_errors=True)

        # 更新元数据
        new_projects = [p for p in projects if p["id"] != project_id]
        save_projects(new_projects)

        self._send_json(200, {"success": True, "deleted_id": project_id})


if __name__ == "__main__":
    server_address = ("0.0.0.0", PORT)
    httpd = http.server.HTTPServer(server_address, DeployHandler)
    print(f"[StaticPreview Receiver] 启动中: 监听 0.0.0.0:{PORT} (数据目录: {DATA_DIR})", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已退出", flush=True)
