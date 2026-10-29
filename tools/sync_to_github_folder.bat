@echo off
rem Copies Capri Reload into the GitHub repo folder (Desktop\capri-reload by default),
rem skipping private files: settings, log, reports, samples and the speech model.
set "SRC=%~dp0.."
set "DST=%USERPROFILE%\Desktop\capri-reload"
if not "%~1"=="" set "DST=%~1"
robocopy "%SRC%" "%DST%" /E /XD models reports samples __pycache__ .ruff_cache .pytest_cache .git .claude .venv venv .capri-update-backup /XF config.json *.log *.pyc *.pyo *.tmp .capri-version .capri-update.lock capri.zip /NFL /NDL /NJH /NP
echo.
echo Done. Now open GitHub Desktop: Commit to main, then Push origin.
pause
