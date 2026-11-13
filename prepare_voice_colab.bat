@echo off
cd /d "%~dp0"
py -m tools.build_voice_colab
py -m tools.install_emotions
pause
