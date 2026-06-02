@echo off
REM Story 6.16 — run build_scenario.py with the project venv Python (bypasses the
REM Windows "python" App-Execution-Alias Store stub). Usage from anywhere:
REM   server\scripts\build.cmd --id cop_interrogation_01 --character cop -d "..."
"%~dp0..\.venv\Scripts\python.exe" "%~dp0build_scenario.py" %*
