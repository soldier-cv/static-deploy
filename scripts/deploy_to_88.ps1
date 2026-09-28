<#
.SYNOPSIS
    将 static-preview 自动化发布部署至 88 服务器 (100.64.0.88)
.DESCRIPTION
    遵循 server-88-deploy 规范，通过 SSH 传输配置与代码，初始化 /data 数据目录，并拉起容器。
.EXAMPLE
    .\scripts\deploy_to_88.ps1
    .\scripts\deploy_to_88.ps1 -KeyPath "C:\Users\huaxu\.ssh\id_rsa"
#>

param(
    [Parameter(Mandatory=$false)]
    [string]$ServerHost = "100.64.0.88",

    [Parameter(Mandatory=$false)]
    [string]$User = "root",

    [Parameter(Mandatory=$false)]
    [string]$KeyPath = "",

    [Parameter(Mandatory=$false)]
    [int]$Port = 8088
)

$ErrorActionPreference = "Stop"
$ProjectName = "static-preview"
$ServerDir = Join-Path $PSScriptRoot "..\server"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ">>> 准备部署 $ProjectName 至 88 服务器 ($ServerHost)" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

# 自动定位私钥
if (-not $KeyPath) {
    $candidateKeys = @(
        "C:\Users\huaxu\.ssh\cloud-box-ed25519",
        "C:\Users\huaxu\.ssh\id_rsa",
        "C:\Users\huaxu\.ssh\id_ed25519",
        "C:\Users\HXD\.ssh\xl"
    )
    foreach ($k in $candidateKeys) {
        if (Test-Path $k) {
            $KeyPath = $k
            break
        }
    }
}

$sshOpts = @("-o", "ConnectTimeout=8", "-o", "StrictHostKeyChecking=accept-new")
if ($KeyPath -and (Test-Path $KeyPath)) {
    Write-Host ">>> 使用私钥: $KeyPath" -ForegroundColor DarkGray
    $sshOpts += @("-i", $KeyPath)
} else {
    Write-Host ">>> 未指定私钥，使用 SSH 默认身份/凭据" -ForegroundColor DarkGray
}

function Invoke-Remote {
    param([string]$Cmd)
    & ssh $sshOpts "$User@$ServerHost" $Cmd
}

# 1. 连通性与端口检查
Write-Host "`n>>> [1/5] 检查服务器网络与端口 $Port..." -ForegroundColor Cyan
$portCheck = Invoke-Remote "ss -tulpn | grep :$Port || echo 'PORT_FREE'"
if ($portCheck -notlike "*PORT_FREE*") {
    Write-Host "WARN: 端口 $Port 已被占用，如果是正在运行的旧版本容器则会在后续重建更新" -ForegroundColor Yellow
} else {
    Write-Host "OK: 端口 $Port 状态正常" -ForegroundColor Green
}

# 2. 创建目录
Write-Host "`n>>> [2/5] 创建远程部署与数据目录..." -ForegroundColor Cyan
Invoke-Remote "mkdir -p /opt/deploy/$ProjectName /data/$ProjectName/sites /data/$ProjectName/meta && chmod -R 755 /data/$ProjectName"

# 3. 传输文件 (使用 Base64 传输避免换行符与转义问题)
Write-Host "`n>>> [3/5] 同步服务端文件到 /opt/deploy/$ProjectName/ ..." -ForegroundColor Cyan

$filesToSync = @("docker-compose.yml", ".env", "nginx.conf", "portal.html", "receiver.py", "OPERATIONS.md")

foreach ($f in $filesToSync) {
    $localFile = Join-Path $ServerDir $f
    if (Test-Path $localFile) {
        Write-Host "  -> 同步 $f" -ForegroundColor DarkGray
        $content = [System.IO.File]::ReadAllText($localFile, [System.Text.Encoding]::UTF8)
        $b64 = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($content))
        Invoke-Remote "echo '$b64' | base64 -d > /opt/deploy/$ProjectName/$f"
    }
}

# 赋执行权
Invoke-Remote "chmod +x /opt/deploy/$ProjectName/receiver.py"

# 4. 启动容器
Write-Host "`n>>> [4/5] 启动 Docker 容器 (force-recreate)..." -ForegroundColor Cyan
Invoke-Remote "cd /opt/deploy/$ProjectName && docker compose up -d --force-recreate"

# 5. 健康检查
Write-Host "`n>>> [5/5] 等待服务初始化与健康检查..." -ForegroundColor Cyan
Start-Sleep -Seconds 3
Invoke-Remote "cd /opt/deploy/$ProjectName && docker compose ps"

Write-Host "`n============================================================" -ForegroundColor Green
Write-Host "部署完成！" -ForegroundColor Green
Write-Host "控制看板访问: http://${ServerHost}:${Port}/" -ForegroundColor Green
Write-Host "API 健康检测: http://${ServerHost}:${Port}/api/health" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
