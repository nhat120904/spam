@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 goto use_python
py -3 "%~dp0open_incognito_windows.py" %*
goto finished

:use_python
where python >nul 2>nul
if errorlevel 1 goto missing_python
python "%~dp0open_incognito_windows.py" %*
goto finished

:missing_python
echo Chua tim thay Python. Cai Python 3.10 tro len va bat Add Python to PATH.
pause
exit /b 1

:finished
set "THINH_LIET_EXIT=%errorlevel%"
echo.
pause
exit /b %THINH_LIET_EXIT%
