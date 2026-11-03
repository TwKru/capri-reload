@echo off
cd /d "%~dp0"
python -X utf8 -m tools.install_clone_voice
if errorlevel 1 (
  echo Installation failed. See docs/voice-clone.md.
  pause
  exit /b 1
)
echo Voice installed. Select qwen_clone in config.json to use it.
pause
