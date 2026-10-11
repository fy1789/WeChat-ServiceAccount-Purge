@echo off
chcp 65001 >nul
title PC 微信“服务号”一键彻底删除补丁工具
cd /d "%~dp0"

echo ========================================================
echo   PC 微信 (4.1.15.51) “服务号”一键彻底清空热补丁
echo ========================================================
echo.

python wx_service_delete_patch.py apply

echo.
echo [提示] 若上方显示 Applied 或 PATCHED，现在即可在微信中右键“服务号 -> 删除”一键清空！
pause
