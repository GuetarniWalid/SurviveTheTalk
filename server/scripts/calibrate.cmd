@echo off
REM Story 6.15/6.16 — run calibrate_scenario.py with the project venv Python (bypasses
REM the Windows "python" App-Execution-Alias Store stub). Usage from anywhere:
REM   server\scripts\calibrate.cmd waiter_easy_01
REM   server\scripts\calibrate.cmd            (smart sweep of all scenarios)
"%~dp0..\.venv\Scripts\python.exe" "%~dp0calibrate_scenario.py" %*
