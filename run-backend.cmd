@echo off
echo ========================================================
echo   Standa Hub - BACKEND  (Tailscale ready: 0.0.0.0:8000)
echo ========================================================
echo.

cd /d "%~dp0backend"

if not exist "main.py" (
    echo [CHYBA] main.py nenalezen ve slozce %CD%
    echo          Spravna cesta je: c:\Projekt\standa-hub\backend\
    echo          Pravdepodobne jsi spustil skript v kopii projektu.
    echo.
    pause
    exit /b 1
)

if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=%CD%\.venv\Scripts\python.exe"
    echo Pouzivam Python z virtualniho prostredi .venv
) else (
    set "PYTHON_EXE=python.exe"
    echo Varovani: .venv nenalezen, pouzivam globalni python.exe
)

echo Current dir: %CD%
echo.
echo Starting uvicorn with --host 0.0.0.0 --port 8000 --reload
echo.
"%PYTHON_EXE%" -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
pause
