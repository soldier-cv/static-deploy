# Woodpecker v3 流水线：compose 本机发布骨架

适用：服务端用 docker compose 跑在同一台宿主，CI 要「构建镜像 → 推 registry → compose up → 健康验证」。
实证：desk-alarm（api + gateway 两个镜像）、reimburse-ai。

## 完整骨架（三 step，可抄）

```yaml
# Woodpecker v3.19 实测
when:
  - event: tag
    ref: refs/tags/v*
  - event: manual          # 页面手动触发，可填 deploy_tag 指定版本（也是回滚手段）

skip_clone: false

steps:
  - name: resolve-tag
    image: alpine:3.20
    volumes:
      - /opt/code/<project>:/opt/code/<project>
    commands:
      - mkdir -p /opt/code/<project>
      - cp -rf docker server shared mockups docker-compose.yml .dockerignore .env.example /opt/code/<project>/
      - if [ ! -f /opt/code/<project>/.env ]; then cp .env.example /opt/code/<project>/.env; fi
      # tag 事件用 CI_COMMIT_TAG；manual 用页面变量，大小写都认（Woodpecker 不做大写映射）
      - >-
        if [ -n "$${CI_COMMIT_TAG}" ]; then echo "$${CI_COMMIT_TAG}"; elif [ -n "$${deploy_tag:-}" ]; then echo "$${deploy_tag}";
        elif [ -n "$${DEPLOY_TAG:-}" ]; then echo "$${DEPLOY_TAG}"; else echo latest; fi | tr -d ' ' > /tmp/release_tag
      - echo "RELEASE_TAG=$$(cat /tmp/release_tag)"
      # step 间不共享环境变量 → 版本落共享卷文件
      - cp /tmp/release_tag /opt/code/<project>/.release_tag

  - name: verify-server
    image: docker.1ms.run/library/node:22-alpine
    depends_on: [resolve-tag]
    commands:
      - cd server
      - npm config set registry https://registry.npmmirror.com
      - npm ci --no-audit --no-fund
      - npm run typecheck
      - npm run build

  - name: build-and-deploy
    image: docker:26                     # 自带 docker CLI + compose + busybox wget
    depends_on: [verify-server]
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - /opt/code/<project>:/opt/code/<project>
    environment:
      REGISTRY_HOST: { from_secret: registry_host }   # v3 只有这种写法，没有 step 级 secrets 数组
      REGISTRY_USER: { from_secret: registry_user }
      REGISTRY_PASS: { from_secret: registry_pass }
    commands:
      - cd /opt/code/<project>
      - RELEASE_TAG=$$(cat .release_tag)
      - test -n "$$REGISTRY_HOST" || { echo "缺少 registry_host 变量" >&2; exit 1; }
      - echo "$$REGISTRY_PASS" | docker login "$$REGISTRY_HOST" -u $$REGISTRY_USER --password-stdin
      # 双 tag 同 digest：一次 build 打两个 tag，再分别 push
      - docker build -f docker/api.Dockerfile -t "$$REGISTRY_HOST/<app>-api:$${RELEASE_TAG}" -t "$$REGISTRY_HOST/<app>-api:latest" .
      - docker push "$$REGISTRY_HOST/<app>-api:$${RELEASE_TAG}"
      - docker push "$$REGISTRY_HOST/<app>-api:latest"
      - docker logout "$$REGISTRY_HOST"
      # compose 只管文件里定义的服务；改名前的旧容器不会被带走，会继续占端口
      - docker rm -f <old-container-name> 2>/dev/null || echo "无旧容器，跳过"
      - REGISTRY_HOST=$$REGISTRY_HOST IMAGE_TAG=$${RELEASE_TAG} docker compose up -d --force-recreate
      - docker compose ps
      # 健康验证看容器 healthcheck，不看 compose 退出码
      - >-
        for i in $$(seq 1 30); do st=$$(docker inspect -f '{{.State.Health.Status}}' <container> 2>/dev/null || echo missing);
        if [ "$$st" = "healthy" ]; then echo "deploy OK: $${RELEASE_TAG}"; exit 0; fi;
        echo "waiting health ($$i): $$st"; sleep 5; done; echo "health check failed" >&2; exit 1
```

## 铁律（每条对应一次真实事故）

1. **v3 没有 step 级 `secrets: [...]`**：必须 `environment.X.from_secret`。照抄 v2 教程 → linter 报
   `Additional property secrets is not allowed`，整条 pipeline 编译失败。
2. **Secret 不存在 = 整条 pipeline 编译 error**（不是 warning）：连"本该被 when 跳过"的 push 也 error。
   可选通知步骤要么先建 secret，要么不写。
3. **Secret 的 `events` 必须覆盖所有部署触发事件**：只配 `["tag"]` 的 secret 在 manual 触发时报
   `not allowed to be used with pipeline event "manual"`。统一配 `["tag","release","manual","cron"]`。
4. **`$` → `$$`**：CI 会先做变量替换，`$${VAR}`/`$$(cmd)` 才是容器内 shell 展开。
   裸 `$VAR` 会被替换成空串，表现为"变量莫名丢失"。
5. **命令含 `key: value`（`curl -H "Content-Type: x"`、`echo "版本: $V"`、`grep '"a": 1'`）会破坏 YAML**：
   用 `>-` 折叠块承载整条命令，或把断言抽成仓库里的 `.sh` 由 step 调用。
6. **跨 step 传值只能落共享卷文件**（`.release_tag`）：每个 step 是独立容器，环境变量不继承，挂载也不继承。
7. **repo 的 `trusted.volumes` 未开 → 每条 pipeline 都 `Insufficient trust level to use volumes`**。
   接入新仓库第一件事就开：
   ```bash
   curl -s -X PATCH -H "Authorization: Bearer $PAT" -H 'Content-Type: application/json' \
     http://<ci-host>:8000/api/repos/<id> -d '{"trusted":{"network":true,"volumes":true,"security":true}}'
   ```
8. **步骤脚本一律 `set -eu` + `$${VAR:-}`**：CI 只注入部分变量（实测 `CI_NETRC_MACHINE` 有值、
   `CI_NETRC_USERNAME/PASSWORD` 无值），裸引用未定义变量 → exit 2 秒退。
9. **镜像走加速源**：CI 不复用宿主已拉镜像，`docker.1ms.run/library/node:22-alpine` 这类前缀能省大量等待。
10. **健康探测不要用 awk 解析 HTTP 状态码**（busybox awk 的 `$${2}` 转义极易坏），
    用 `wget --spider` 退出码、`docker inspect` 健康状态或 python urllib。

## 双 tag 同 digest（部署正确性的核心）

```bash
docker build -t img:1.2.3 -t img:latest .   # 一次 build 两个 tag
docker push img:1.2.3 && docker push img:latest
```

分两次 build 会因层缓存/时间戳差异产生不同 digest，`latest` 与版本 tag 就不再等价，
回滚和"到底在跑哪版"全部失效。

## 验收（CI 绿 ≠ 部署生效）

```bash
# 1) 运行容器的镜像 digest
docker inspect <container> --format '{{.Image}}'
# 2) registry 上版本 tag 与 latest 的 digest（Basic auth 取 auths[<registry>].auth）
curl -s -u "$USER:$PASS" -H 'Accept: application/vnd.docker.distribution.manifest.v2+json' \
  https://<registry>/v2/<repo>/manifests/<tag> -D- -o /dev/null | grep -i docker-content-digest
```

判据：**版本 tag digest == 运行容器 digest**。不要用 `latest == running` 验收——latest 可能还指旧构建，
等式恒真、毫无证明力。

## manual 触发与回滚

```bash
curl -s -X POST -H "Authorization: Bearer $PAT" -H 'Content-Type: application/json' \
  http://<ci-host>:8000/api/repos/<id>/pipelines \
  -d '{"event":"manual","branch":"master","variables":{"DEPLOY_TAG":"v1.2.3"}}'
```

- **manual 是回滚手段**：填旧版本号即可把旧镜像重新部署（前提：registry 里还有那个 tag）。
- 页面变量 `deploy_tag` 与 `DEPLOY_TAG` **不做映射**，yml 里两种大小写都要认，否则静默落 `latest`
  （构建成功、版本 tag 没推，最难发现）。
- 改了 yml 后 **rerun 无效**（rerun 固定原 commit），要新建 manual pipeline 或打新 tag。

## 排障表

| 症状 | 根因 | 处置 |
|---|---|---|
| 每条 pipeline 都 error（含 push） | `trusted.volumes` 未开 | PATCH repo trusted |
| status=error 无 workflow | 编译期问题（secret 缺失/事件不允许/语法） | 看 `/pipelines/<n>` 的 `errors` 字段 |
| step 秒退 exit 2 / `parameter not set` | 裸引用未注入变量 | 全改 `$${VAR:-}` |
| `docker: not found`（exit 127） | 镜像没带 CLI | 用 `docker:26` 镜像 |
| 容器循环重启、端口 bind 失败 | 旧容器占端口 / compose 读错 `.env` | `docker rm -f <旧名>`；核对两处 `.env` md5 |
| 探宿主 `127.0.0.1` 连接被拒 | step 容器在 docker 网桥，回环不通 | 用 `172.17.0.1:<port>` |
| 测试容器里 `sudo/ss: not found` | slim 镜像缺工具 | `apt-get install -y -qq iproute2 docker.io` |
| `No such image`（宿主明明能拉） | CI 不复用宿主镜像 | 镜像名走加速源，或宿主 pull 后重跑 |
| clone 偶发 TLS eof | 代理链路抖动 | 重跑同一 pipeline，别改代理配置 |
| webhook 没触发 pipeline | GitHub→CI 投递失败 | 查 `gh api repos/<o>/<r>/hooks/<id>/deliveries`，必要时 API 手动触发 |

## 与 k3s/GitOps 的分工

- compose 本机发布：本文档。
- k3s 发布（build → push → bump GitOps → ArgoCD 同步）：见 `k3s-gitops-onboarding`。
- 服务端运维（PAT、sqlite 查状态、forge timeout、secret 补齐）：见 `woodpecker-ci-pipelines`。
