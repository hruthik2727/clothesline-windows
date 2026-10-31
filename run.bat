@echo off
cd /d "%~dp0"
rem The Python environment lives in %LOCALAPPDATA%, so this folder can sit in OneDrive/GitHub without syncing hundreds of MB.
set "VENV=%LOCALAPPDATA%\Clothesline\venv"
if not exist "%VENV%\Scripts\pythonw.exe" (
    echo First run: setting things up, this takes a minute...
    py -3 -m venv "%VENV%" 2>nul || python -m venv "%VENV%"
    if errorlevel 1 (
        echo Python 3.10+ was not found. Install it from python.org and tick "Add python.exe to PATH".
        pause
        exit /b 1
    )
    call "%VENV%\Scripts\activate.bat"
    python -m pip install --upgrade pip -q
    pip install -r requirements.txt -q
)
start "" "%VENV%\Scripts\pythonw.exe" clothesline.py
