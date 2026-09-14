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
  echo Python not found - installing Python 3.12 using winget...
winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
if errorlevel 1 (
  echo.
  echo winget-Installation fehlgeschlagen. Bitte Python 3.11+ manuell
  echo winget installation failed. Please install Python 3.11 or later
  echo installieren: https://www.python.org/downloads/
  echo manually: https://www.python.org/downloads/
  echo Danach install.bat erneut doppelklicken.
  echo Then double-click install.bat again.
  pause
  exit /b 1
)
echo.
echo Python installiert. Bitte dieses Fenster schliessen und
  echo Python installed. Please close this window and
echo install.bat ERNEUT doppelklicken (damit der neue PATH greift).
  echo double-click install.bat AGAIN so the updated PATH takes effect.
pause
exit /b 0

:haspython
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
if errorlevel 1 (
  echo.
  echo Setup fehlgeschlagen - Meldungen oben pruefen.
  echo Setup failed - check the messages above.
)
pause
