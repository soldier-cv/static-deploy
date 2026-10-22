# GitHub Actions 发版骨架（桌面应用，可直接抄）

## job 拓扑

```yaml
name: Build Desktop Release
on:
  push:
    tags: ['v*']
  pull_request:
    branches: [main, master]
  workflow_dispatch:
    inputs:
      tag:
        description: '发布已存在的 tag（形如 v0.2.3），留空只出 artifact'
        required: false

permissions:
  contents: read          # 顶层只读，上传类 job 各自声明 write

concurrency:
  group: release-${{ github.ref }}
  cancel-in-progress: false   # 发版不允许被并发覆盖
```

## plan：唯一版本真源

```yaml
  plan:
    runs-on: ubuntu-latest
    outputs:
      release_tag: ${{ steps.pick.outputs.tag }}
      publish: ${{ steps.pick.outputs.publish }}
    steps:
      - name: Resolve version and publish flag
        id: pick
        env:
          EVENT: ${{ github.event_name }}
          REF_TAG: ${{ github.ref_name }}
          INPUT_TAG: ${{ inputs.tag }}
        run: |
          set -euo pipefail
          if [ "$EVENT" = "push" ]; then TAG="$REF_TAG"; else TAG="$(echo "${INPUT_TAG:-}" | tr -d '[:space:]')"; fi
          if [ -n "$TAG" ] && [ "${TAG#v}" = "$TAG" ]; then TAG="v$TAG"; fi
          if [ -n "$TAG" ] && ! echo "$TAG" | grep -Eq '^v[0-9]+\.[0-9]+\.[0-9]+'; then
            echo "::error::版本号格式不对：$TAG（要形如 v0.2.0）"; exit 1
          fi
          echo "tag=$TAG" >> "$GITHUB_OUTPUT"
          if [ -n "$TAG" ]; then echo "publish=true" >> "$GITHUB_OUTPUT"; else echo "publish=false" >> "$GITHUB_OUTPUT"; fi
```

要点：所有下游 job 用 `needs.plan.outputs.release_tag / publish`，不要各自再解析一遍。
`publish=false`（PR、无 tag 手动跑）时只出 artifact，不建 Release、不签名发布。

## 打包前签名预检（省 6~8 分钟）

```yaml
      - name: Verify signing secret format
        if: ${{ needs.plan.outputs.publish == 'true' }}
        shell: bash
        env:
          KEY: ${{ secrets.TAURI_SIGNING_PRIVATE_KEY }}
        run: |
          if [ -z "$KEY" ]; then echo "::error::TAURI_SIGNING_PRIVATE_KEY 为空"; exit 1; fi
          TRIMMED="$(printf '%s' "$KEY" | tr -d '[:space:]')"
          if [ "$TRIMMED" != "$KEY" ]; then
            echo "::error::含空白/换行（粘贴带入行尾）。需要单行纯 base64（约 348 字符，无 untrusted comment 行）"; exit 1
          fi
          if ! printf '%s' "$KEY" | base64 -d >/dev/null 2>&1; then echo "::error::不是合法 base64"; exit 1; fi
          echo "私钥格式校验通过（长度 ${#KEY}）"
```

## 上传重试封装（抗 5xx）

```yaml
  windows:
    needs: plan
    runs-on: windows-latest
    permissions:
      contents: write          # 缺这行 → 403 Resource not accessible by integration
    steps:
      - uses: actions/checkout@v4
      # ... 打包 ...
      - name: Upload assets (retry)
        shell: bash
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          TAG: ${{ needs.plan.outputs.release_tag }}
        run: |
          upload_with_retry() {
            local tag="$1"; shift
            local attempt=1 max=5 delay=5
            while [ "$attempt" -le "$max" ]; do
              if gh release upload "$tag" "$@" --clobber; then return 0; fi
              if [ "$attempt" -lt "$max" ]; then
                echo "::warning::upload 第 ${attempt} 次失败（疑似 5xx），${delay}s 后重试"
                sleep "$delay"; delay=$((delay * 2))
              fi
              attempt=$((attempt + 1))
            done
            echo "::error::upload 重试 ${max} 次仍失败"; return 1
          }
          gh release view "$TAG" >/dev/null 2>&1 || gh release create "$TAG" --notes "Release $TAG"
          upload_with_retry "$TAG" dist/*.exe dist/*.sig
```

重试只治 5xx。403 是权限问题，加次数无用。

## 产物命名（先定死，后面全部依赖它）

- **显式传 `productName`** 给打包器，否则产物前缀会丢。
- **附件名用 ASCII**：中文名在 Gitee / URL / 各平台客户端里会被编码成不同形态，`latest.json` 拼 URL 必错。
- 命名模板（Tauri 默认即可）：`<product>_<version>_x64-setup.exe`、`<product>_<version>_aarch64.app.tar.gz`。

## macOS 签名路径

```yaml
      - name: Collect signature and assets
        run: |
          # Tauri 签的是 updater 产物 .app.tar.gz，落在 bundle/macos/
          SIG=$(ls app/src-tauri/target/release/bundle/macos/*.app.tar.gz.sig)
          cp "$SIG" dist/
          cp app/src-tauri/target/release/bundle/macos/*.app.tar.gz dist/
          cp app/src-tauri/target/release/bundle/dmg/*.dmg dist/    # dmg 只给人手动装，无签名
```

拿不准目录时读打包器自己的输出，别按平台惯例猜：

```bash
gh run view <run-id> --log | grep -E 'Finished [0-9]+ (bundles|updater signature)|Bundling '
```

## latest-json job（必须 checkout + write）

```yaml
  latest-json:
    if: ${{ needs.plan.outputs.publish == 'true' }}
    needs: [plan, windows, macos]
    runs-on: ubuntu-latest
    permissions:
      contents: write        # 上传附件需要
    env:
      TAG: ${{ needs.plan.outputs.release_tag }}
    steps:
      - uses: actions/checkout@v4      # gh 靠 git 上下文推断 owner/repo，缺则 fatal: not a git repository
      - name: Build and upload latest.json
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          set -euo pipefail
          V="${TAG#v}"
          GH_REL="https://github.com/${GITHUB_REPOSITORY}/releases/download/${TAG}"
          MIRROR_REL="https://gitee.com/<gitee_owner>/<gitee_repo>/releases/download/${TAG}"
          sig() { curl -fsSL "${GH_REL}/$1" | tr -d '\r\n'; }
          WIN_SIG="$(sig "desk-alarm_${V}_x64-setup.exe.sig")"
          MAC_SIG="$(sig "desk-alarm_${V}_aarch64.app.tar.gz.sig")"
          if [ -z "$WIN_SIG" ] || [ -z "$MAC_SIG" ]; then
            echo "::error::取不到 .sig（打包时没注入签名私钥？）"; exit 1
          fi
          jq -n --arg v "$V" --arg d "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
                --arg wu "${MIRROR_REL}/desk-alarm_${V}_x64-setup.exe" --arg ws "$WIN_SIG" \
                --arg mu "${MIRROR_REL}/desk-alarm_${V}_aarch64.app.tar.gz" --arg ms "$MAC_SIG" \
            '{version:$v, pub_date:$d, platforms:{
                "windows-x86_64":{url:$wu, signature:$ws},
                "darwin-aarch64":{url:$mu, signature:$ms}}}' > latest.json
          gh release upload "$TAG" latest.json --clobber
```

约定：**`url` 指向哪个文件，`signature` 就必须是那个文件的签名**。macOS 用 dmg 的 sha 配 tar.gz 的签名，
客户端验签必失败（详见 SKILL.md 签名三坑第 2 条）。
URL 指向镜像不等于放弃验签 —— 验签由客户端内置 `pubkey` 兜底。

## 手动触发复用已有 tag（省一次版本号）

```bash
gh workflow run build.yml -f tag=v0.2.3     # 已存在的 tag → 走完整发布路径
gh run list --workflow=build.yml --limit 2
gh run rerun <run-id> --failed              # 只重跑失败 job
```

修 CI 时反复用这个，不要每改一次就 bump 版本号（会污染版本历史）。

## 排障顺序

1. `gh run list --limit 12` 看哪个 job 红。
2. `gh run view <id> --json jobs` 找出**失败的 step 名**（不要整段日志从头读）。
3. `gh run view <id> --log-failed`，把报错归类（格式/路径/权限/网络）。
4. 一次只改一类，改完 `gh run rerun --failed` 立即验证。
5. 改 yml 后本地验语法：`python3 -c "import yaml;yaml.safe_load(open('.github/workflows/build.yml'));print('OK')"`。

## 工作区前提（最容易犯的错）

排障前先 `git fetch && git pull --ff-only`。本地落后的 `build.yml` 可能只有 2 个 job，远端实际跑 6 个——
照本地文件推断 "CI 为什么这么跑" 会得出完全错误的结论。确认同步：`git rev-list --left-right --count HEAD...origin/main`（两项都为 0）。
