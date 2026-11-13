#!/usr/bin/env python3
"""重建技能分发包的 index.json。

单一真源原则：version 取自各 SKILL.md 的 frontmatter，files/sha256/updated_at
由磁盘实际内容算出，只有 description 是人工维护（太长，不适合塞 frontmatter）。

用法:
    python3 sync_index.py            # 重写 index.json
    python3 sync_index.py --check    # 只校验 index.json 是否与磁盘一致，不写盘

排除机制:
    本地保留、不进分发范围的技能写在 EXCLUDE_SKILLS 里（或用 --exclude 追加）。
    排除只影响 index.json 的生成，不删除、不移动本地技能目录。

退出码: 0 = 一致/已写入；1 = --check 下发现不一致
"""
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))
INDEX = os.path.join(ROOT, "index.json")
CST = timezone(timedelta(hours=8))
# 本地工具技能：保留在 skills/ 供本机使用，但不进分发包
EXCLUDE_SKILLS = {"skill-publisher"}
ALLOWED_SUBDIRS = ("references", "scripts", "assets", "templates")
ALLOWED_FILE_RE = re.compile(
    r"^(?!.*\.\.)[A-Za-z0-9][A-Za-z0-9_.-]*\.(?:md|py|sh|js|ps1|yaml|yml|json|txt|toml|bat|cmd)$"
)


def read_frontmatter(path):
    text = open(path, encoding="utf-8").read()
    meta = {}
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return meta
    for line in m.group(1).splitlines():
        if line.strip().startswith("#") or ":" not in line:
            continue
        key, val = line.split(":", 1)
        meta[key.strip()] = val.strip().strip('"').strip("'")
    return meta


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def collect(skill_dir):
    name = os.path.basename(skill_dir)
    skill_md = os.path.join(skill_dir, "SKILL.md")
    if not os.path.isfile(skill_md):
        return None
    files = ["SKILL.md"]
    for sub in ALLOWED_SUBDIRS:
        sub_dir = os.path.join(skill_dir, sub)
        if os.path.isdir(sub_dir) and not os.path.islink(sub_dir):
            for fn in sorted(os.listdir(sub_dir)):
                full_path = os.path.join(sub_dir, fn)
                if (
                    ALLOWED_FILE_RE.fullmatch(fn)
                    and not os.path.islink(full_path)
                    and os.path.isfile(full_path)
                ):
                    files.append(f"{sub}/{fn}")

    meta = read_frontmatter(skill_md)
    newest = max(os.path.getmtime(os.path.join(skill_dir, f)) for f in files)
    return {
        "name": name,
        "version": meta.get("version", "0.0.0"),
        "updated_at": datetime.fromtimestamp(newest, CST).strftime("%Y-%m-%d %H:%M:%S"),
        "files": files,
        "sha256": {f: sha256_of(os.path.join(skill_dir, f)) for f in files},
    }


def main():
    check_only = "--check" in sys.argv
    excluded = set(EXCLUDE_SKILLS)
    argv = sys.argv[1:]
    for i, arg in enumerate(argv):
        if arg == "--exclude" and i + 1 < len(argv):
            excluded.add(argv[i + 1])
        elif arg.startswith("--exclude="):
            excluded.add(arg.split("=", 1)[1])

    old = {}
    if os.path.isfile(INDEX):
        try:
            for s in json.load(open(INDEX, encoding="utf-8")).get("skills", []):
                old[s["name"]] = s.get("description", "")
        except (json.JSONDecodeError, KeyError):
            pass

    skills = []
    for entry in sorted(os.listdir(ROOT)):
        path = os.path.join(ROOT, entry)
        if not os.path.isdir(path) or entry.startswith(".") or entry in excluded:
            continue
        item = collect(path)
        if not item:
            continue
        fm_desc = read_frontmatter(os.path.join(path, "SKILL.md")).get("description", "")
        item["description"] = fm_desc or old.get(item["name"], "")
        # 保持字段顺序好读
        skills.append({
            "name": item["name"],
            "description": item["description"],
            "version": item["version"],
            "updated_at": item["updated_at"],
            "files": item["files"],
            "sha256": item["sha256"],
        })

    payload = {
        "schema": 2,
        "updated_at": datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S"),
        "update_url": "http://100.64.0.88:8088/.well-known/skills/index.json",
        "install_root": "http://100.64.0.88:8088/.well-known/skills/",
        "skills": skills,
    }
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"

    if check_only:
        current = open(INDEX, encoding="utf-8").read() if os.path.isfile(INDEX) else ""
        # 忽略 updated_at 这一行的差异
        strip = lambda s: re.sub(r'"updated_at": ".*?"', "", s)
        if strip(current) != strip(rendered):
            print("index.json 与磁盘不一致，需要重跑 sync_index.py", file=sys.stderr)
            return 1
        print("index.json 与磁盘一致")
        return 0

    with open(INDEX, "w", encoding="utf-8") as f:
        f.write(rendered)
    print(f"已写入 {INDEX}，共 {len(skills)} 个技能")
    for s in skills:
        print(f"  {s['name']:<32} v{s['version']:<8} {len(s['files'])} 文件  {s['updated_at']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
