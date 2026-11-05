# SPDX-License-Identifier: MPL-2.0
# Starts only the local demo. Does not install host software or reboot Windows.
[CmdletBinding()]
param([string]$AIHubArchive, [ValidateSet(109, 154)][int]$IRISBuild = 109)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$dockerCommand = Get-Command docker -ErrorAction SilentlyContinue
if (-not $dockerCommand) {
    foreach ($candidate in @(
        (Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\resources\bin\docker.exe'),
        'C:\Program Files\Docker\Docker\resources\bin\docker.exe'
    )) {
        if (Test-Path -LiteralPath $candidate) { $dockerCommand = Get-Item -LiteralPath $candidate; break }
    }
}
if (-not $dockerCommand) { throw 'Docker Desktop is not installed. Complete host setup first; this script does not install it.' }
$dockerPath = $dockerCommand.Source
if (-not $dockerPath) { $dockerPath = $dockerCommand.FullName }
$version = if ($IRISBuild -eq 109) { '2027.1.0AI.109.0' } else { '2026.3.0AI.154.0' }
$localImage = 'recall-guard-aihub:' + $version
python scripts/check_docker.py --docker-path $dockerPath
if ($LASTEXITCODE -ne 0) { throw 'A running Linux Docker engine is required. Complete host setup first; this script does not open the dashboard.' }
if ($AIHubArchive) {
    $archive = (Resolve-Path -LiteralPath $AIHubArchive).Path
    if (-not $archive.EndsWith('.tar.gz')) { throw "Expected the build $IRISBuild docker.tar.gz archive." }
    $loadResult = & $dockerPath image load --input $archive 2>&1
    if ($LASTEXITCODE -ne 0) { throw 'Docker could not load the EAP archive.' }
    $imageNames = @($loadResult | ForEach-Object { if ($_ -match '^Loaded image: (.+)$') { $Matches[1] } })
    $expectedImage = 'iris-community:' + [regex]::Escape($version) + '$'
    $matchedImageNames = @($imageNames | Where-Object { $_ -match $expectedImage })
    if ($matchedImageNames.Count -ne 1) { throw "The archive did not expose exactly one expected IRIS Community build $IRISBuild image." }
    & $dockerPath tag $matchedImageNames[0] $localImage
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the local EAP image tag.' }
}
& $dockerPath image inspect $localImage --format '{{.Id}}'
if ($LASTEXITCODE -ne 0) { throw 'Load the EAP archive first with -AIHubArchive. No image will be pulled from a public registry.' }
# Use the same isolated keyless path documented for evaluators. PATH is local to this process.
$env:PATH = (Split-Path -Parent $dockerPath) + [IO.Path]::PathSeparator + $env:PATH
python scripts/judge_demo.py start --iris-build $IRISBuild --build
if ($LASTEXITCODE -ne 0) { throw 'Keyless first-visit setup failed; existing data was retained.' }
Write-Output 'Local demo: http://localhost:52773/recall-guard/auth/RecallGuard.Home.cls'
Write-Output 'Sign in as SuperUser using IRIS_PASSWORD from .env. No paid provider is configured.'
