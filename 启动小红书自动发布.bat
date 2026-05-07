@echo off
chcp 65001 >nul
title 小豆芽小红书自动发布脚本
color 0A

echo ===================================================
echo          新榜小豆芽 - 小红书自动发布脚本
echo ===================================================
echo.
echo 发布参数：
echo 1. 视频目录：C:\Users\TU\Desktop\小红书麻将
echo 2. 发布账号：启动后可手动选择 H01-H12
echo 3. 已发布目录：C:\Users\TU\Desktop\小红书麻将\已发布
echo.
echo 请确保：
echo 1. 新榜小豆芽客户端已经打开并保持登录。
echo 2. 小豆芽中可见“多开面板”与“天天麻将小红书”合集。
echo 3. 执行期间不要操作鼠标和键盘。
echo.
echo 运行中如需紧急终止：按 Ctrl+T
echo.
echo 按任意键开始执行...（如需取消请直接关闭窗口）
pause >nul

cd /d "%~dp0"
py -3 xhs_xiaodouya_launcher.py

echo.
echo ===================================================
echo 执行结束！如有报错请查看 xhs_error_log.txt
echo ===================================================
pause
