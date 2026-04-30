@echo off
chcp 65001 >nul
color 0A

echo ========================================================
echo               启动小豆芽自动发布脚本 (独立版)
echo ========================================================
echo.
echo 注意事项：
echo 1. 请确保已配置好同目录下的 xiaodouya_config.json
echo 2. 请确保已打开“新榜小豆芽”并登录账号
echo 3. 请将小豆芽软件置于当前可见桌面（建议桌面2）
echo.

if not exist "xiaodouya_config.json" (
    echo [错误] 找不到配置文件 xiaodouya_config.json！
    echo 请确保配置文件与本程序在同一个文件夹内。
    echo.
    pause
    exit /b 1
)

if not exist "xiaodouya_poster.exe" (
    echo [错误] 找不到主程序 xiaodouya_poster.exe！
    echo 请确保主程序与本脚本在同一个文件夹内。
    echo.
    pause
    exit /b 1
)

echo [状态] 正在启动自动化程序...
echo.

xiaodouya_poster.exe

echo.
if %errorlevel% neq 0 (
    color 0C
    echo ========================================================
    echo [警告] 程序执行出现异常！请检查上方的错误信息。
    echo ========================================================
) else (
    color 0A
    echo ========================================================
    echo [完成] 所有视频已处理完毕！
    echo ========================================================
)

echo.
pause
