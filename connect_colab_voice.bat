@echo off
cd /d "%~dp0"
py -m pip install -r requirements-colab-client.txt
if errorlevel 1 goto end
py -m tools.connect_colab_voice
:end
pause
