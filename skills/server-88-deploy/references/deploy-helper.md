# 自动化运维脚本（deploy-helper.ps1）

> 本文件是技能包内可执行资产的 Markdown 转写 —— 分发通道只放行 `SKILL.md` 与 `references/*.md`。
> 落地方法：按各节标题里的路径原样写回磁盘，代码块内容与原文件一致。

## `scripts/deploy-helper.ps1`

```powershell
<#
.SYNOPSIS
    88 服务器 (100.64.0.88) 自动化部署与运维辅助脚本
.DESCRIPTION
    用于从 Windows 本机快速对 100.64.0.88 服务器执行服务部署、更新、状态巡检、停止与清理。
.EXAMPLE
    .\deploy-helper.ps1 -Action check-port -Port 8080
    .\deploy-helper.ps1 -Action deploy -ProjectName myapp -LocalDir C:\path\to\config
    .\deploy-helper.ps1 -Action status -ProjectName myapp
#>

param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("check-port", "deploy", "status", "logs", "recreate", "down", "check-server")]
    [string]$Action,

    [Parameter(Mandatory=$false)]
    [string]$ProjectName,

    [Parameter(Mandatory=$false)]
    [int]$Port,

    [Parameter(Mandatory=$false)]
    [string]$LocalDir,

    [Parameter(Mandatory=$false)]
    [string]$KeyPath = "C:\Users\HXD\.ssh\xl",

    [Parameter(Mandatory=$false)]
    [string]$ServerHost = "100.64.0.88",

    [Parameter(Mandatory=$false)]
    [string]$User = "root"
)

$ErrorActionPreference = "Stop"

function Invoke-RemoteSsh {
    param([string]$RemoteCmd)
    & ssh -i $KeyPath -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new "$User@$ServerHost" $RemoteCmd
}

switch ($Action) {
    "check-server" {
        Write-Host ">>> 正在检测 88 服务器连接与 Docker 环境..." -ForegroundColor Cyan
        Invoke-RemoteSsh "uname -a; docker --version; docker compose version; df -h / /data"
    }

    "check-port" {
        if (-not $Port) {
            Write-Error "请指定 -Port 参数"
        }
        Write-Host ">>> 检查端口 $Port 是否已被占用..." -ForegroundColor Cyan
        $res = Invoke-RemoteSsh "ss -tulpn | grep :$Port || echo 'PORT_FREE'"
        if ($res -like "*PORT_FREE*") {
            Write-Host "OK: 端口 $Port 空闲可用" -ForegroundColor Green
        } else {
            Write-Host "WARN: 端口 $Port 已被占用:" -ForegroundColor Yellow
            Write-Output $res
        }
    }

    "deploy" {
        if (-not $ProjectName -or -not $LocalDir) {
            Write-Error "请提供 -ProjectName 与 -LocalDir 参数"
        }
        $composePath = Join-Path $LocalDir "docker-compose.yml"
        $envPath = Join-Path $LocalDir ".env"
        if (-not (Test-Path $composePath)) {
            Write-Error "未在 $LocalDir 找到 docker-compose.yml"
        }

        Write-Host ">>> 1. 创建远程目录与设置权限..." -ForegroundColor Cyan
        Invoke-RemoteSsh "mkdir -p /opt/deploy/$ProjectName /data/$ProjectName && chmod 755 /data/$ProjectName"

        Write-Host ">>> 2. 传输配置文件到 /opt/deploy/$ProjectName/ ..." -ForegroundColor Cyan
        $composeContent = [System.IO.File]::ReadAllText($composePath)
        $composeB64 = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($composeContent))
        Invoke-RemoteSsh "echo '$composeB64' | base64 -d > /opt/deploy/$ProjectName/docker-compose.yml"

        if (Test-Path $envPath) {
            $envContent = [System.IO.File]::ReadAllText($envPath)
            $envB64 = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($envContent))
            Invoke-RemoteSsh "echo '$envB64' | base64 -d > /opt/deploy/$ProjectName/.env"
        }

        $opsPath = Join-Path $LocalDir "OPERATIONS.md"
        if (Test-Path $opsPath) {
            $opsContent = [System.IO.File]::ReadAllText($opsPath)
            $opsB64 = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($opsContent))
            Invoke-RemoteSsh "echo '$opsB64' | base64 -d > /opt/deploy/$ProjectName/OPERATIONS.md"
        }

        Write-Host ">>> 3. 启动容器..." -ForegroundColor Cyan
        Invoke-RemoteSsh "cd /opt/deploy/$ProjectName && docker compose up -d --force-recreate"

        Write-Host ">>> 4. 检查服务状态..." -ForegroundColor Cyan
        Start-Sleep -Seconds 3
        Invoke-RemoteSsh "cd /opt/deploy/$ProjectName && docker compose ps"
        Write-Host "OK: 部署完成" -ForegroundColor Green
    }

    "status" {
        if (-not $ProjectName) {
            Write-Error "请指定 -ProjectName 参数"
        }
        Invoke-RemoteSsh "test -d /opt/deploy/$ProjectName && cd /opt/deploy/$ProjectName && docker compose ps || echo 'Project directory not found'"
    }

    "logs" {
        if (-not $ProjectName) {
            Write-Error "请指定 -ProjectName 参数"
        }
        Invoke-RemoteSsh "cd /opt/deploy/$ProjectName && docker compose logs --tail=100"
    }

    "recreate" {
        if (-not $ProjectName) {
            Write-Error "请指定 -ProjectName 参数"
        }
        Write-Host ">>> 正在强制重建容器 $ProjectName..." -ForegroundColor Cyan
        Invoke-RemoteSsh "cd /opt/deploy/$ProjectName && docker compose up -d --force-recreate && docker compose ps"
    }

    "down" {
        if (-not $ProjectName) {
            Write-Error "请指定 -ProjectName 参数"
        }
        Write-Host ">>> 停止并移除容器 $ProjectName..." -ForegroundColor Yellow
        Invoke-RemoteSsh "cd /opt/deploy/$ProjectName && docker compose down"
    }
}
```
