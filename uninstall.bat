@echo off
REM ============================================================
REM  LocalFlow - Deinstallation (einfach doppelklicken)
REM  Beendet die App, entfernt Autostart + Startmenue-Eintrag und
REM  bietet an: Modell-Caches loeschen, Ordner komplett entfernen.
REM ============================================================
setlocal
set "ROOT=%~dp0"
REM Aus dem Ordner heraus wechseln, damit er geloescht werden kann.
cd /d "%TEMP%"

powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%uninstall.ps1" -Root "%ROOT%"
if errorlevel 42 exit /b 0

pause
