@echo off
cd /d "%~dp0"
set "PY="
for %%v in (3.13 3.12 3.11 3.14) do if not defined PY py -%%v -c "" >nul 2>nul && set "PY=py -%%v"
if not defined PY set "PY=python"
%PY% -m pip install kokoro-onnx==0.4.7 psutil
if errorlevel 1 goto done
%PY% kokoro_voice.py --install --variant masha
:done
pause
