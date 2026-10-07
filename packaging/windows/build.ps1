# Build Kit-Desk-Setup-<version>.exe on Windows.
#
#   powershell -ExecutionPolicy Bypass -File packaging\windows\build.ps1
#
# Needs Python 3.11+ and Inno Setup 6 (winget install JRSoftware.InnoSetup).
# The installer lands in packaging\windows\build\installer. GitHub Actions runs
# this same script for every change, so a ready-made installer can also be
# downloaded from the "Desk app" workflow run.

param([string]$Python = "python")
$ErrorActionPreference = "Stop"

function Run {
    param([string]$Exe, [string[]]$Arguments)
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Exe failed with exit code $LASTEXITCODE" }
}

$here = $PSScriptRoot
$root = (Resolve-Path "$here\..\..").Path
$build = Join-Path $here "build"

# The build number makes every published build newer than the last, which is how
# the app's update check knows there's something new. GitHub's run number on
# GitHub Actions, 0 for a build made by hand (which never offers itself as an update).
$build_no = if ($env:GITHUB_RUN_NUMBER) { $env:GITHUB_RUN_NUMBER } else { "0" }
Set-Content -Path "$root\src\kit\desk\_build.py" -Encoding utf8 -Value @(
    '"""Written by packaging/windows/build.ps1: which build of the desk app this is."""',
    "",
    "BUILD = $build_no"
)
Run $Python @("-m", "pip", "install", "--upgrade", "$root[desk]", "pyinstaller>=6.6")
$version = (& $Python -c "from kit.desk.update import VERSION; print(VERSION)").Trim()
if (-not $version.EndsWith(".$build_no")) { throw "Kit reports version $version, not build ${build_no}: _build.py wasn't packed" }
Run $Python @("$here\make_icon.py", "$build\kit.ico")

# One folder rather than one file: Kit starts faster and antivirus is happier.
Run $Python @(
    "-m", "PyInstaller", "$here\kit_desk.py",
    "--name", "Kit", "--windowed", "--noconfirm", "--clean",
    "--icon", "$build\kit.ico",
    "--distpath", "$build\dist", "--workpath", "$build\work", "--specpath", "$build",
    # The brain's server side isn't part of the desk app.
    "--exclude-module", "fastapi", "--exclude-module", "uvicorn",
    "--exclude-module", "anthropic", "--exclude-module", "numpy"
)
# A windowed exe doesn't block PowerShell, so wait for the self-test explicitly.
$test = Start-Process "$build\dist\Kit\Kit.exe" -ArgumentList "--selftest" -Wait -PassThru
if ($test.ExitCode -ne 0) { throw "Kit.exe --selftest failed with exit code $($test.ExitCode)" }

$iscc = (Get-Command iscc.exe -ErrorAction SilentlyContinue).Source
if (-not $iscc) { $iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" }
if (-not (Test-Path $iscc)) { throw "Inno Setup 6 isn't installed: winget install JRSoftware.InnoSetup" }
Run $iscc @("/DAppVersion=$version", "$here\kit-desk.iss")
Write-Host "Built $build\installer\Kit-Desk-Setup-$version.exe"
if ($env:GITHUB_OUTPUT) { "version=$version" | Out-File -FilePath $env:GITHUB_OUTPUT -Append -Encoding utf8 }
