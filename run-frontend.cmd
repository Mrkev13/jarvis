@echo off
echo ========================================================
echo   Standa Hub - FRONTEND  (Tailscale ready: 0.0.0.0:3000)
echo ========================================================
echo.

cd /d "%~dp0frontend"

if not exist "package.json" (
    echo [CHYBA] package.json nenalezen ve slozce %CD%
    echo          Spravna cesta je: c:\Projekt\standa-hub\frontend\
    echo          Pravdepodobne jsi spustil skript v kopii projektu.
    echo.
    pause
    exit /b 1
)

echo Current dir: %CD%
echo.
echo Kontrola NEXT_PUBLIC_API_URL v .env.local:
if not exist ".env.local" (
    echo [VAROVANI] .env.local NEEXISTUJE! Vytvor ho dle .env.template
    echo            Frontend bude pouzivat fallback: http://127.0.0.1:8000
    echo.
) else (
    for /f "tokens=2 delims==" %%a in ('findstr /B /C:"NEXT_PUBLIC_API_URL" .env.local') do (
        set "API_URL=%%a"
        echo     Aktualni hodnota: %%a
        echo.
        echo %%a | findstr /B /C:"http://" >nul
        if errorlevel 1 (
            echo [CHYBA] CHYBI http:// PREFIX v NEXT_PUBLIC_API_URL!
            echo          Musi byt: http://100.XXX.XXX.XXX:8000
            echo          NE pouze: 100.XXX.XXX.XXX:8000
            echo          Oprav .env.local a restartuj.
            echo.
            pause
            exit /b 1
        )
    )
)

echo Starting Next.js dev server with --hostname 0.0.0.0
echo (po nacteni otevri http://localhost:3000 nebo Tailscale IP)
echo.
npm.cmd run dev -- --hostname 0.0.0.0
pause
