"""Обновление автономной Windows-сборки только из release ZIP с SHA256."""
import hashlib
import json
import re
import subprocess
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from capri.core import cancellation


def release():
    from capri.updates.source_updater import REPOSITORY
    request = urllib.request.Request(f"https://api.github.com/repos/{REPOSITORY}/releases/latest",headers={"User-Agent":"Capri"})
    with cancellation.open_url(request,timeout=15) as response:
        data = json.load(response)
    assets = [item for item in data.get("assets",[]) if re.fullmatch(r"Capri-Windows[^/]*\.zip",item.get("name",""),re.IGNORECASE)]
    if not assets:
        raise ValueError("В последнем выпуске пока нет автономной Windows-сборки. Исходный ZIP не подходит для EXE.")
    asset = assets[0]
    digest = asset.get("digest","")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}",digest):
        raise ValueError("GitHub не предоставил SHA256 автономной сборки")
    return data, asset


def latest():
    data,_ = release()
    return data["tag_name"]


def start(base,pid):
    from capri.updates.source_updater import protected
    base = Path(base).resolve()
    data,asset = release()
    root = Path(tempfile.mkdtemp(prefix="capri-native-update-"))
    archive = root/"update.zip"
    digest = hashlib.sha256()
    received = 0
    with cancellation.open_url(asset["browser_download_url"],timeout=60) as response, archive.open("wb") as stream:
        while chunk := response.read(1024*1024):
            cancellation.checkpoint()
            received += len(chunk)
            if received > 2*1024**3:
                raise ValueError("Слишком большой архив обновления")
            stream.write(chunk); digest.update(chunk)
    if "sha256:"+digest.hexdigest() != asset["digest"]:
        raise ValueError("SHA256 обновления не совпадает")
    stage = root/"staged"
    files = []
    with zipfile.ZipFile(archive) as bundle:
        total = 0
        for info in bundle.infolist():
            relative = Path(info.filename)
            target = (stage/relative).resolve()
            total += info.file_size
            if not target.is_relative_to(stage.resolve()) or ":" in info.filename or total > 4*1024**3:
                raise ValueError("Небезопасный архив обновления")
            if info.is_dir() or protected(relative):
                continue
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(bundle.read(info))
            files.append(str(relative))
    if "Capri.exe" not in files:
        raise ValueError("В архиве нет Capri.exe")
    (stage/".native-version").write_text(data["tag_name"],encoding="utf-8")
    files.append(".native-version")
    manifest = root/"manifest.json"
    manifest.write_text(json.dumps({"base":str(base),"stage":str(stage),"pid":int(pid),"files":files}),encoding="utf-8")
    script = root/"update.ps1"
    script.write_text(HELPER,encoding="utf-8-sig")
    return subprocess.Popen(["powershell.exe","-NoProfile","-NonInteractive","-ExecutionPolicy","Bypass",
        "-File",str(script),"-Manifest",str(manifest)],creationflags=0x08000000)


HELPER = r'''
param([Parameter(Mandatory=$true)][string]$Manifest)
$ErrorActionPreference = 'Stop'
$data = Get-Content -LiteralPath $Manifest -Raw -Encoding UTF8 | ConvertFrom-Json
$targetRoot = [IO.Path]::GetFullPath($data.base).TrimEnd('\')
$stageRoot = [IO.Path]::GetFullPath($data.stage).TrimEnd('\')
$expectedExe = Join-Path $targetRoot 'Capri.exe'
$process = Get-Process -Id $data.pid -ErrorAction SilentlyContinue
if ($process) {
    if ($process.Path -ne $expectedExe) { throw 'Process path mismatch' }
    Stop-Process -Id $data.pid
    Wait-Process -Id $data.pid -Timeout 20 -ErrorAction SilentlyContinue
}
$backupRoot = Join-Path (Split-Path -Parent $Manifest) 'backup'
$copied = @()
try {
    foreach ($relative in $data.files) {
        $destination = [IO.Path]::GetFullPath((Join-Path $targetRoot $relative))
        $source = [IO.Path]::GetFullPath((Join-Path $stageRoot $relative))
        if (!$destination.StartsWith($targetRoot+'\',[StringComparison]::OrdinalIgnoreCase) -or !$source.StartsWith($stageRoot+'\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Path escapes root' }
        $backup = Join-Path $backupRoot $relative
        if (Test-Path -LiteralPath $destination) {
            New-Item -ItemType Directory -Path (Split-Path -Parent $backup) -Force | Out-Null
            Copy-Item -LiteralPath $destination -Destination $backup
        }
        New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
        $copied += $relative
        Copy-Item -LiteralPath $source -Destination $destination -Force
    }
} catch {
    foreach ($relative in $copied) {
        $backup = Join-Path $backupRoot $relative
        if (Test-Path -LiteralPath $backup) { Copy-Item -LiteralPath $backup -Destination (Join-Path $targetRoot $relative) -Force }
    }
    $_ | Out-File -LiteralPath (Join-Path $targetRoot 'capri-update.log') -Encoding UTF8
} finally {
    Start-Process -FilePath $expectedExe -WorkingDirectory $targetRoot -WindowStyle Hidden
}
'''
