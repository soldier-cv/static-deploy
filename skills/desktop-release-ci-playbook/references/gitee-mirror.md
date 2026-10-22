# GitHub → Gitee 双通道镜像（源码 + tag + Release 附件）

## 为什么要分两个 workflow

| workflow | 职责 | 触发 | 冲突风险 |
|---|---|---|---|
| `sync-gitee.yml` | 源码分支镜像 | push `main`/`master`、手动 | 低（只推分支） |
| `build.yml` 的 `gitee-release` job | tag + Release 附件 + 地址校验 | 发版（tag / 手动） | 与分支镜像互不触碰 |

把两者合并成一个 workflow 会在发版时同时往 Gitee 推分支和 tag，`--force` 互相覆盖。
分两段、各管一段，是刻意的边界。

## 源码分支镜像

```yaml
name: Sync to Gitee
on:
  push:
    branches: [main, master]
  workflow_dispatch:

concurrency:
  group: sync-gitee-branch
  cancel-in-progress: true

jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - name: Push to Gitee
        env:
          GITEE_TOKEN: ${{ secrets.GITEE_TOKEN }}
        run: |
          export GIT_TERMINAL_PROMPT=0      # 凭证异常时不要卡在交互式密码提示
          if [ -z "$GITEE_TOKEN" ]; then
            echo "::error::未配置 GITEE_TOKEN（仓库 Settings → Secrets → Actions）"; exit 1
          fi
          if [ "${{ github.repository }}" != "<owner>/<repo>" ]; then
            echo "非主仓库（fork），跳过镜像推送"; exit 0
          fi
          git remote add gitee "https://<gitee_user>:${GITEE_TOKEN}@gitee.com/<gitee_owner>/<gitee_repo>.git"
          git fetch origin main
          git checkout -B main origin/main
          git push -u gitee main:main --force
```

- `fetch-depth: 0`：浅克隆推不出完整历史。
- `--force`：镜像语义是"Gitee 与 GitHub 一致"，不是合并。Gitee 侧若被手工改过，直接覆盖。
- **fork 守卫**（`github.repository` 判断）必须放在 `git remote add` 之前，否则 PR fork 会试图用主仓库 token 推。

## Release 附件同步（build.yml 的 gitee-release job）

排序关键：`needs: [plan, windows, macos, latest-json]` —— 要连 `latest.json` 一起搬，
否则 Gitee 上有安装包却没清单，客户端照样问不出版本。

```yaml
  gitee-release:
    if: ${{ needs.plan.outputs.publish == 'true' && github.repository == '<owner>/<repo>' }}
    needs: [plan, windows, macos, latest-json]
    runs-on: ubuntu-latest
    continue-on-error: true      # 镜像失败不该让整个发版显示失败（GitHub Release 已可用）
    env:
      GITEE_OWNER: <gitee_owner>
      GITEE_REPO: <gitee_repo>
      TAG: ${{ needs.plan.outputs.release_tag }}
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0 }

      - name: 检查 GITEE_TOKEN
        id: token
        env: { GITEE_TOKEN: ${{ secrets.GITEE_TOKEN }} }
        run: |
          if [ -z "${GITEE_TOKEN:-}" ]; then
            echo "::error::未配置 GITEE_TOKEN，国内用户拿不到镜像通道。"
            echo "ok=false" >> "$GITHUB_OUTPUT"
          else echo "ok=true" >> "$GITHUB_OUTPUT"; fi

      - name: 推 tag 到 Gitee
        if: ${{ steps.token.outputs.ok == 'true' }}
        env: { GITEE_TOKEN: ${{ secrets.GITEE_TOKEN }} }
        run: |
          set -euo pipefail
          export GIT_TERMINAL_PROMPT=0
          git remote add gitee "https://${GITEE_OWNER}:${GITEE_TOKEN}@gitee.com/${GITEE_OWNER}/${GITEE_REPO}.git"
          git fetch --tags origin "refs/tags/${TAG}:refs/tags/${TAG}"
          git push gitee "refs/tags/${TAG}:refs/tags/${TAG}" --force

      - name: 从 GitHub Release 取安装包
        if: ${{ steps.token.outputs.ok == 'true' }}
        env: { GH_TOKEN: ${{ secrets.GITHUB_TOKEN }} }
        run: mkdir -p assets && gh release download "$TAG" --dir assets && ls -l assets

      - name: 同步 Release 到 Gitee
        if: ${{ steps.token.outputs.ok == 'true' }}
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          GITEE_TOKEN: ${{ secrets.GITEE_TOKEN }}
        run: |
          set -uo pipefail
          API="https://gitee.com/api/v5/repos/${GITEE_OWNER}/${GITEE_REPO}"
          BODY="$(gh release view "$TAG" --json body -q .body || true)"
          [ -n "$BODY" ] || BODY="Release ${TAG}"

          # ① 建 Release：必须 multipart form（JSON POST 有概率被 WAF 拦成 400，
          #    form 顺带解决中文正文换行编码）
          CREATE="$(curl -sS -X POST "${API}/releases" \
            -F "access_token=${GITEE_TOKEN}" -F "tag_name=${TAG}" \
            -F "target_commitish=main" -F "name=App ${TAG}" \
            -F "body=${BODY}" -F "prerelease=false" || true)"
          ID="$(printf '%s' "$CREATE" | jq -r '.id // empty' || true)"

          # ② 没拿到 id 不代表失败：可能已存在（补包重跑），按 tag 查回来复用并刷新说明
          if [ -z "$ID" ]; then
            ID="$(curl -sS "${API}/releases/tags/${TAG}?access_token=${GITEE_TOKEN}" | jq -r '.id // empty' || true)"
            [ -n "$ID" ] && curl -sS -X PATCH "${API}/releases/${ID}" \
              -F "access_token=${GITEE_TOKEN}" -F "tag_name=${TAG}" -F "name=App ${TAG}" -F "body=${BODY}" || true
          fi

          # ③ 仍无 id 就停：空壳 Release 比没有更糟（用户点进去下不到东西）
          if [ -z "$ID" ]; then echo "::error::没拿到 Gitee Release id，附件未上传。响应：$CREATE"; exit 1; fi

          # ④ 逐文件：先删同名（Gitee 同名会 400），再传，重试 3 次
          ok=0
          for f in assets/*; do
            [ -f "$f" ] || continue
            n="$(basename "$f")"
            for old in $(curl -sS "${API}/releases/${ID}/attach_files?access_token=${GITEE_TOKEN}" \
                           | jq -r --arg n "$n" '.[] | select(.name == $n) | .id' || true); do
              curl -sS -X DELETE "${API}/releases/${ID}/attach_files/${old}?access_token=${GITEE_TOKEN}" || true
            done
            uploaded=0
            for attempt in 1 2 3; do
              resp="$(curl -sS -X POST "${API}/releases/${ID}/attach_files?access_token=${GITEE_TOKEN}" \
                        -F "access_token=${GITEE_TOKEN}" \
                        -F "file=@${f};filename=${n};type=application/octet-stream" || true)"
              if printf '%s' "$resp" | jq -e '.id or .browser_download_url' >/dev/null 2>&1; then
                uploaded=1; ok=$((ok+1)); break
              fi
              echo "::warning::$n 上传失败：$resp"; sleep 5
            done
            if [ "$uploaded" != "1" ]; then
              echo "::error::$n 三次上传均失败，Gitee Release ${TAG} 缺该文件"; exit 1
            fi
          done
          [ "$ok" -gt 0 ] || { echo "::error::assets 目录为空"; exit 1; }

      - name: 校验镜像上的下载地址
        if: ${{ steps.token.outputs.ok == 'true' }}
        run: |
          set -uo pipefail
          base="https://gitee.com/${GITEE_OWNER}/${GITEE_REPO}/releases/download/${TAG}"
          bad=""
          for name in $(jq -r '.platforms[].url' assets/latest.json | sed "s|.*/||"); do
            code="$(curl -sS -o /dev/null -w '%{http_code}' -L --max-time 30 "${base}/${name}" || echo 000)"
            if [ "$code" != "200" ]; then echo "::error::镜像上 ${name} 不可下载（HTTP ${code}）"; bad="1"
            else echo "OK ${name}"; fi
          done
          [ -z "$bad" ] || { echo "::error::镜像附件不完整，客户端会下载失败"; exit 1; }
```

## 关键取舍

| 决定 | 理由 |
|---|---|
| `continue-on-error: true` | GitHub Release 已建好、用户可下载，镜像失败不该把发版标红。代价是失败不进 job 状态 → 脚本内一律 `::error::` + `exit 1` 保证日志可见 |
| 缺 `GITEE_TOKEN` 只 `::error::` 不 `exit 1` | 同上：降级可用（走 GitHub），但不许静默 |
| tag 用 `--force` push | 同名 tag 重打是常规操作（修 CI 后重发），不 force 会 non-fast-forward |
| `latest.json` URL 指向 Gitee | 国内直连快；验签由客户端内置 pubkey 兜底，URL 指镜像 ≠ 放弃安全 |
| 附件先删后传 | Gitee 同名附件 400；删了再传保证幂等，重跑不会失败 |

## 验证命令

```bash
# 源码镜像：Gitee 分支头 == GitHub 分支头
git ls-remote https://gitee.com/<gitee_owner>/<gitee_repo>.git refs/heads/main
gh api repos/<owner>/<repo>/commits/main --jq .sha

# 附件与清单
curl -fsSL "https://gitee.com/<gitee_owner>/<gitee_repo>/releases/download/v0.2.3/latest.json" | jq .
curl -sS -o /dev/null -w '%{http_code}\n' -L "https://gitee.com/<gitee_owner>/<gitee_repo>/releases/download/v0.2.3/<asset>"
```

`-L` 不能省：Gitee 下载地址是 302 跳转，不带 `-L` 你会看到一个假的 302 并误判成功。

## 排障表

| 症状 | 根因 | 处置 |
|---|---|---|
| 建 Release 返回 400 无 id | JSON POST 被 WAF 拦 | 改 `-F` multipart |
| 附件上传 400 | 同名附件已存在 | 先列 attach_files 删同名 |
| Release 建了没附件 | 创建未返回 id 就继续 | 查 `releases/tags/<tag>` 复用；仍无则 exit 1 |
| 客户端提示新版但 404 | 清单先于附件生效，或 url 指错文件 | 镜像 job 里逐个 URL 校验 200 |
| branch 镜像卡住 | 凭证异常触发交互式密码提示 | `export GIT_TERMINAL_PROMPT=0` |
| fork PR 时镜像失败 | 用主仓库 token 推 fork | `github.repository` 守卫提前 return |
| 分支与 tag 互相覆盖 | 两段合并在一个 workflow | 拆分 workflow，各管一段 |
