@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo   EasyControl 打包脚本 (PyInstaller 单文件)
echo ============================================
echo.

echo [1/2] 安装 PyInstaller ...
python -m pip install --upgrade pyinstaller
if errorlevel 1 (
    echo PyInstaller 安装失败！
    pause
    exit /b 1
)

echo.
echo [2/2] 打包为单文件 exe ...
python -m PyInstaller --onefile --noconsole --name EasyControl ec_control.py
if errorlevel 1 (
    echo 打包失败！
    pause
    exit /b 1
)

echo.
echo 打包完成！
echo 生成文件：dist\EasyControl.exe
echo 双击即可运行，无需安装 Python。
pause
