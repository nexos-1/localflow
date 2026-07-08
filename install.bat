@echo off
REM ============================================================
REM  LocalFlow - Ein-Klick-Setup fuer Windows
REM  Einfach doppelklicken. Installiert bei Bedarf Python (winget),
REM  dann venv + Dependencies + Startmenue-Eintrag, und startet die App.
REM ============================================================
setlocal
cd /d "%~dp0"

echo == LocalFlow Setup ==

REM Python vorhanden? (python im PATH ODER der py-Launcher)
where python >nul 2>nul
if not errorlevel 1 goto haspython
where py >nul 2>nul
if not errorlevel 1 goto haspython

echo Python nicht gefunden - installiere Python 3.12 ueber winget...
winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
if errorlevel 1 (
  echo.
  echo winget-Installation fehlgeschlagen. Bitte Python 3.11+ manuell
  echo installieren: https://www.python.org/downloads/
  echo Danach install.bat erneut doppelklicken.
  pause
  exit /b 1
)
echo.
echo Python installiert. Bitte dieses Fenster schliessen und
echo install.bat ERNEUT doppelklicken (damit der neue PATH greift).
pause
exit /b 0

:haspython
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
if errorlevel 1 (
  echo.
  echo Setup fehlgeschlagen - Meldungen oben pruefen.
)
pause
