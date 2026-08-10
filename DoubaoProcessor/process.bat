@echo off
chcp 65001 >nul

if "%~1"=="" (
    echo 请拖入图片文件夹
    pause
    exit
)

powershell.exe -ExecutionPolicy Bypass -File "%~dp0process.ps1" "%~1"

pause