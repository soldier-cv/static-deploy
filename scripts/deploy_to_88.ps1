<#
.SYNOPSIS
    在 88 服务器上更新并启动 static-deploy
.DESCRIPTION
    SSH 到 88，在 /opt/code/static-deploy 执行 git pull --ff-only，再用 docker compose 拉起容器。
    git 是唯一代码来源，不再逐文件传输。
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
$ProjectName = "static-deploy"
$RemoteRepo = "/opt/code/static-deploy"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ">>> 准备部署 $ProjectName 至 88 服务器 ($ServerHost)" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

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
    if ($LASTEXITCODE -ne 0) {
        throw "远程命令失败 (exit $LASTEXITCODE): $Cmd"
    }
}

# 1. 连通性与端口检查
Write-Host "`n>>> [1/4] 检查服务器网络与端口 $Port..." -ForegroundColor Cyan
$portCheck = & ssh $sshOpts "$User@$ServerHost" "ss -tulpn | grep :$Port || echo 'PORT_FREE'"
if ($portCheck -notlike "*PORT_FREE*") {
    Write-Host "OK: 端口 $Port 已在监听（将通过 compose up -d 滚动更新）" -ForegroundColor Yellow
} else {
    Write-Host "OK: 端口 $Port 当前空闲" -ForegroundColor Green
}

# 2. git pull
Write-Host "`n>>> [2/4] 在 $RemoteRepo 执行 git pull --ff-only ..." -ForegroundColor Cyan
Invoke-Remote "cd $RemoteRepo && git pull --ff-only"

# 3. 拉起容器
Write-Host "`n>>> [3/4] docker compose up -d ..." -ForegroundColor Cyan
Invoke-Remote "cd $RemoteRepo && docker compose -f server/docker-compose.yml --env-file server/.env up -d"

# 4. 健康检查
Write-Host "`n>>> [4/4] 等待服务初始化与健康检查..." -ForegroundColor Cyan
Start-Sleep -Seconds 3
Invoke-Remote "cd $RemoteRepo && docker compose -f server/docker-compose.yml --env-file server/.env ps"
$health = & ssh $sshOpts "$User@$ServerHost" "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:$Port/api/health"
Write-Host "健康检查 HTTP $health" -ForegroundColor $(if ($health -eq "200") { "Green" } else { "Yellow" })

Write-Host "`n============================================================" -ForegroundColor Green
Write-Host "部署完成！" -ForegroundColor Green
Write-Host "控制看板访问: http://${ServerHost}:${Port}/" -ForegroundColor Green
Write-Host "API 健康检测: http://${ServerHost}:${Port}/api/health" -ForegroundColor Green
Write-Host "MCP 端点:      http://${ServerHost}:${Port}/mcp" -ForegroundColor Green
Write-Host "MCP 指引:      http://${ServerHost}:${Port}/setup" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
