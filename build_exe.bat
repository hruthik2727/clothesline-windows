@echo off
cd /d "%~dp0"
set "VENV=%LOCALAPPDATA%\Clothesline\venv"
if not exist "%VENV%\Scripts\python.exe" call run.bat
call "%VENV%\Scripts\activate.bat"
pip install -q pyinstaller
pyinstaller --noconfirm --windowed --name Clothesline --distpath "%LOCALAPPDATA%\Clothesline\dist" --workpath "%LOCALAPPDATA%\Clothesline\build" --specpath "%LOCALAPPDATA%\Clothesline" clothesline.py
echo.
echo Done. Your app is in %LOCALAPPDATA%\Clothesline\dist\Clothesline\Clothesline.exe
pause
