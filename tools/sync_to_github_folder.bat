@echo off
rem Copies Capri Reload into the GitHub repo folder (Desktop\capri-reload by default),
rem skipping private files: settings, log, reports, samples and the speech model.
set "SRC=%~dp0.."
set "DST=%USERPROFILE%\Desktop\capri-reload"
if not "%~1"=="" set "DST=%~1"
robocopy "%SRC%" "%DST%" /E /XD models reports samples __pycache__ .git .claude /XF config.json capri.log *.pyc capri.zip /NFL /NDL /NJH /NP
echo.
echo Done. Now open GitHub Desktop: Commit to main, then Push origin.
pause
