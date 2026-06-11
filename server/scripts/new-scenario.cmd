@echo off
REM Story 6.17 — double-click this to create a new scenario with a simple wizard.
REM It asks for the character, your idea + a short name, then the AI builds
REM the whole scenario (story + 20 steps + matching voice) and checks it.
"%~dp0..\.venv\Scripts\python.exe" "%~dp0new_scenario.py"
echo.
echo ----- Termine. Appuie sur une touche pour fermer. -----
pause >nul
