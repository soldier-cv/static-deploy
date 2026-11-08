# Woodpecker 与 GitHub Actions 共存规则

## 结论先说

**两种 CI 可以共存，而且很常见。** 判断依据不是「这个项目该用哪个 CI」，而是「**这个项目的每个交付物** 该用哪个 CI」。

一个仓库里有多个交付物是常态：

- 服务端镜像 → 内网 registry → k3s/GitOps → **Woodpecker**
- 桌面/安卓客户端安装包 → GitHub Release → Gitee 镜像 → **GitHub Actions**

这是合理的分工，不是重复建设。真正需要避免的是**同一个交付物挂两条流水线**。

## 判据：按交付物分工，不按项目一刀切

| 交付物 | 去哪 | 用哪套 | 触发 |
|---|---|---|---|
| 服务端镜像 | 内网 registry → 集群 | Woodpecker | tag 或 manual |
| 服务端静态资源 | 内网对象存储/CDN | Woodpecker | tag 或 manual |
| 桌面安装包 | GitHub Release + Gitee | GHA | tag |
| 安卓 APK（对外分发） | GitHub Release + Gitee | GHA | tag |
| 安卓 APK（内网自用更新通道） | 自建 `/api/.../version` | Woodpecker | tag |
| 固件 bin | 内部归档 + OTA 服务器 | 自建脚本或 Woodpecker | tag |
| 文档站 | GitHub Pages | GHA | push main |

**反模式（必须避免）：**

- ❌ 服务端镜像既由 Woodpecker 构建推送，又由 GHA 构建推送 → 两个 registry 里出现不同 digest，回滚时不知道哪个是线上版本。
- ❌ 客户端安装包 Woodpecker 出一份、GHA 出一份 → 两份 sha256 不同，用户下载到的和别人装的不一样。
- ❌ 两条流水线都去改同一个 manifest / 同一个版本文件 → 并发覆盖。

## 共存时的四条纪律

### 1. 路径或交付物必须隔离

```
repo/
├── server/          → Woodpecker 管
├── client/          → GHA 管
├── firmware/        → Woodpecker 或独立脚本管
└── .woodpecker.yml  → 只在 server/** 或 firmware/** 变更时触发
```

Woodpecker 用 `when: path:` 限定目录；GHA 用 `on.push.paths:` 限定目录。两边都不该对全仓库任何变更都触发。

### 2. 触发条件互斥，且写进文件头注释

同一份代码如果两套都要跑（比如测试），明确分工：

- Woodpecker：`event: [tag, manual]`
- GHA：`on.push.tags: ['v*']` + `paths: ['client/**']`

两个文件的头部都写一行注释说明「本文件负责什么，另一套负责什么」，否则半年后没人知道为什么有两套。

### 3. 版本号只有一个真源

两套流水线都必须从 **git tag** 读版本，并且各自校验产物里的版本号与 tag 一致。禁止任何一边自己 `date +%Y%m%d` 或读 `package.json` 版本。

### 4. 发布产物互不覆盖

- Woodpecker 推内网 registry，GHA 推 GitHub Release，**目标不同、命名不同**。
- 如果两边都要产同一个文件（比如 APK），只能选一条链路作为唯一发布源，另一条最多做「构建验证」不上传。

## 现实例子：一个仓库同时有服务端和安卓客户端

```
repo/
├── server/              # Go 服务端
│   └── Dockerfile
├── tv/                  # Android 客户端（gradle）
└── .woodpecker.yml      # server 镜像 + APK 出包（都走内网）
```

这种项目只有 Woodpecker 一套，因为 APK 也只在内网更新通道分发，没有对外发布需求。

一旦需求变成「APK 也要放 GitHub 给外部用户下载」，正确演进是：

- 新增 `.github/workflows/release.yml`，只在 `paths: tv/**` + tag 时跑，产出 GitHub Release；
- Woodpecker 保留服务端镜像职责，APK 出包职责**移交或明确降级为仅内网通道**；
- 在两个文件头部互相注明分工与唯一发布源。

**不要**简单地在 Woodpecker 里加一段 `gh release upload`——那样两套逻辑混在一个文件里，排障时没人分得清是 CI 平台的问题还是脚本的问题。

## 自检

发布前问三个问题：

1. 这个交付物的**唯一发布源**是哪套流水线？
2. 另一套会不会也产出同名文件？（会 → 改成只验证不上传）
3. 两套的版本号都来自同一个 tag 吗？
