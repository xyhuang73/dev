#Requires -Version 5.0
<#
.SYNOPSIS
    在本项目根目录创建独立虚拟环境 .venv 并安装 requirements.txt。

.DESCRIPTION
    与系统或其它项目（如全局安装的 vnpy、streamlit）隔离，避免 numpy/pandas 版本互相拉扯。
    用法（在资源管理器地址栏输入 powershell 后执行，或在项目根打开终端）:
        .\scripts\create_venv.ps1

    之后每次开发先激活:
        .\.venv\Scripts\Activate.ps1
    再运行:
        python main.py
#>
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$VenvPath = Join-Path $Root ".venv"
if (-not (Test-Path $VenvPath)) {
    Write-Host "创建虚拟环境: $VenvPath"
    python -m venv $VenvPath
} else {
    Write-Host "已存在虚拟环境，跳过创建: $VenvPath"
}

$Py = Join-Path $VenvPath "Scripts\python.exe"
if (-not (Test-Path $Py)) {
    throw "未找到 $Py，请确认已安装 Python 并已加入 PATH。"
}

& $Py -m pip install -U pip
& $Py -m pip install -r (Join-Path $Root "requirements.txt")

Write-Host ""
Write-Host "完成。请在项目根先执行: .\.venv\Scripts\Activate.ps1"
Write-Host "然后: python main.py"
