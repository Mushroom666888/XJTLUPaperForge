param([Parameter(Mandatory=$true)][string]$BundlePath)
$ErrorActionPreference = 'Stop'
$packageRoot = (Resolve-Path -LiteralPath $BundlePath).Path
$cli = Join-Path $packageRoot 'paperforge-cli.exe'
if (!(Test-Path -LiteralPath $cli)) { throw 'Select the extracted PaperForge folder.' }
if (Get-Command python,python3,py -ErrorAction SilentlyContinue | Where-Object { $_.Source -notlike '*WindowsApps*' }) {
    throw 'Use a clean VM/Sandbox without an installed Python for this acceptance check.'
}
# PATH isolation alone misses registered Python installations. This is still a
# detection aid: only the VM/image preparation record establishes a clean host.
$pythonRegistryPaths = @(
    'HKCU:\Software\Python', 'HKLM:\Software\Python',
    'HKLM:\Software\WOW6432Node\Python'
)
if ($pythonRegistryPaths | Where-Object { Test-Path -LiteralPath $_ }) {
    throw 'A registered Python installation was found. Use a genuinely clean VM/image.'
}
$dataRoot = Join-Path $env:TEMP ('paperforge-native-check-' + [guid]::NewGuid().ToString('N'))
$env:XJTLUPAPERFORGE_DATA = $dataRoot
$env:XJTLUPAPERFORGE_OUTPUT = Join-Path $dataRoot 'papers'
$env:PYTHONPATH = ''
$env:PYTHONHOME = ''
& $cli --self-test
if ($LASTEXITCODE -ne 0) { throw 'Packaged OCR/export acceptance failed.' }
& $cli --no-browser
if ($LASTEXITCODE -ne 0) { throw 'Packaged launch failed.' }
$state = Get-Content -LiteralPath (Join-Path $dataRoot 'ui.json') -Raw | ConvertFrom-Json
$url = 'http://127.0.0.1:' + $state.port
$page = Invoke-WebRequest -Uri $url -UseBasicParsing
$health = Invoke-RestMethod -Uri ($url + '/health')
$token = [regex]::Match($page.Content, 'name="paperforge-token" content="([^"]+)"').Groups[1].Value
Invoke-RestMethod -Method Post -Uri ($url + '/api/shutdown') -Headers @{'X-PaperForge-Token'=$token} -Body '{}' -ContentType 'application/json'
$deadline = (Get-Date).AddSeconds(15)
while ((Test-Path -LiteralPath (Join-Path $dataRoot 'ui.json')) -and (Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 100
}
if (Test-Path -LiteralPath (Join-Path $dataRoot 'ui.json')) { throw 'Workbench did not finish shutdown.' }
$report = [ordered]@{
    scope = 'synthetic checks only; clean host requires independent VM/image evidence'
    version = $health.version
    source_sha256 = $health.source_sha256
    launcher_sha256 = (Get-FileHash -LiteralPath $cli -Algorithm SHA256).Hash.ToLowerInvariant()
    synthetic_checks = 'passed'
    native_dialogs = 'not_run'
    real_school = 'not_run'
}
$reportPath = Join-Path $dataRoot 'synthetic-acceptance.json'
$report | ConvertTo-Json | Set-Content -LiteralPath $reportPath -Encoding UTF8
Write-Output ('Synthetic export, OCR, launch and shutdown passed. Evidence: ' + $reportPath)
Write-Output 'This script cannot prove that Python was never installed. Retain independent VM/image preparation evidence and complete native dialogs and school acceptance.'
