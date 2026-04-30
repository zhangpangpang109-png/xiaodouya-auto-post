@echo off
setlocal
title Douyin Auto Publisher
color 0A

echo ===================================================
echo               Douyin Auto Publisher
echo ===================================================
echo.
echo Preparing to start...
echo Make sure Xiaodouya app is already opened.
echo.

cd /d "%~dp0"

set "ACCIO_PY=C:\ProgramData\Accio\pre-install\7d5a6d879db7\python\python.exe"
if exist "%ACCIO_PY%" (
    "%ACCIO_PY%" xiaodouya_poster.py
) else (
    where py >nul 2>nul
    if %errorlevel%==0 (
        py xiaodouya_poster.py
    ) else (
        python xiaodouya_poster.py
    )
)

echo.
echo ===================================================
echo Finished. Check error_log.txt if anything failed.
echo ===================================================
pause
