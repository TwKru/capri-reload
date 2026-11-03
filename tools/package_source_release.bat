@echo off
cd /d "%~dp0\.."
py -m tools.package_source_release || python -m tools.package_source_release
pause
