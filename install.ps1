<#
.SYNOPSIS
Installer for coding-agents-kit on Windows (PowerShell 5.1 or 7).

.DESCRIPTION
Copies the kit into $HOME\.local\share\agentkit (the same layout as on
macOS and Linux), puts ak.cmd and agentkit.cmd in its bin directory, adds
that directory to your USER Path, and creates the env file
$HOME\.config\agentkit\env from the template when it does not exist
(readable by you only). Idempotent: rerunning upgrades in place. It never
overwrites the env file, never touches profiles, never installs a coding
agent CLI (that is `ak install`) and never uses the network.

The python core needs Python 3.9 or newer (the `py` launcher or `python`).
Aliases (`ak alias`) are for POSIX shells; on Windows run `ak <kind> --auto`.

.PARAMETER NoPath
Do not modify your user Path.

.PARAMETER Uninstall
Remove the install and its Path entry. Keeps the env file and profiles.

.PARAMETER Prefix
Install root (default: $HOME\.local\share\agentkit).

.PARAMETER EnvFile
Env file path (default: $env:AGENTKIT_ENV, else $HOME\.config\agentkit\env).

.EXAMPLE
.\install.ps1
#>
[CmdletBinding()]
param(
    [switch]$NoPath,
    [switch]$Uninstall,
    [string]$Prefix = '',
    [string]$EnvFile = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Src = $PSScriptRoot
if (-not $Prefix) {
    if ($env:AGENTKIT_HOME) { $Prefix = $env:AGENTKIT_HOME } else { $Prefix = Join-Path $HOME '.local\share\agentkit' }
}
if (-not $EnvFile) {
    if ($env:AGENTKIT_ENV) { $EnvFile = $env:AGENTKIT_ENV } else { $EnvFile = Join-Path $HOME '.config\agentkit\env' }
}
$BinDir = Join-Path $Prefix 'bin'
$Marker = Join-Path $Prefix '.agentkit-install'

# Components are deleted and replaced below, so the prefix must be the kit's
# own directory (a -Prefix of $HOME\.local would otherwise wipe its bin and lib).
if ((Test-Path -LiteralPath $Prefix) -and -not (Test-Path -LiteralPath $Marker)) {
    $foreign = @(Get-ChildItem -LiteralPath $Prefix -Force | Where-Object { $_.Name -notin @('profiles', 'aliases.sh') -and $_.Name -notlike '.install.*' })
    if ($foreign.Count -gt 0) {
        throw "refusing to use ${Prefix}: it is not a coding-agents-kit install (found $($foreign[0].Name)). Choose an empty or dedicated directory."
    }
}
$Components = @('lib', 'skills', 'docs', 'providers.toml', 'LICENSE', 'README.md', 'CREDITS.md', 'CHANGELOG.md')

function Get-UserPathEntries {
    $current = [Environment]::GetEnvironmentVariable('Path', 'User')
    if (-not $current) { return @() }
    return @($current -split ';' | Where-Object { $_ -ne '' })
}

function Set-UserPathEntries([string[]]$Entries) {
    [Environment]::SetEnvironmentVariable('Path', ($Entries -join ';'), 'User')
}

if ($Uninstall) {
    if (-not (Test-Path -LiteralPath $Marker)) { throw "no coding-agents-kit install at $Prefix; nothing removed" }
    if (-not $NoPath) {
        Set-UserPathEntries @(Get-UserPathEntries | Where-Object { $_ -ne $BinDir })
    }
    foreach ($c in @('bin') + $Components) {
        $target = Join-Path $Prefix $c
        if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Recurse -Force }
    }
    Remove-Item -LiteralPath $Marker -Force
    Write-Output "removed coding-agents-kit from $Prefix"
    Write-Output "kept: $EnvFile and $(Join-Path $Prefix 'profiles') (delete them yourself if you want them gone)"
    exit 0
}

# Python 3.9+ is the core's only runtime dependency.
$py = $null
foreach ($candidate in @(@('py', '-3'), @('python'))) {
    $exe = Get-Command $candidate[0] -ErrorAction SilentlyContinue
    if (-not $exe) { continue }
    $pyArgs = @($candidate | Select-Object -Skip 1) + @('-c', 'import sys; sys.exit(sys.version_info < (3, 9))')
    & $exe.Source @pyArgs 2>$null
    if ($LASTEXITCODE -eq 0) { $py = $candidate; break }
}
if (-not $py) {
    throw 'Python 3.9 or newer is required: winget install Python.Python.3.13 (then open a new terminal)'
}

New-Item -ItemType Directory -Force -Path $Prefix | Out-Null
$stage = Join-Path $Prefix ('.install.' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $stage | Out-Null
try {
    foreach ($c in $Components) {
        $from = Join-Path $Src $c
        if (Test-Path -LiteralPath $from) { Copy-Item -LiteralPath $from -Destination (Join-Path $stage $c) -Recurse -Force }
    }
    New-Item -ItemType Directory -Force -Path (Join-Path $stage 'bin') | Out-Null
    foreach ($shim in @('ak.cmd', 'agentkit.cmd')) {
        Copy-Item -LiteralPath (Join-Path $Src "win\$shim") -Destination (Join-Path $stage "bin\$shim") -Force
    }
    Get-ChildItem -Path $stage -Recurse -Directory -Filter '__pycache__' | Remove-Item -Recurse -Force
    # Swap component by component so no stale file from an older version survives.
    foreach ($c in @('bin') + $Components) {
        $staged = Join-Path $stage $c
        if (-not (Test-Path -LiteralPath $staged)) { continue }
        $target = Join-Path $Prefix $c
        if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Recurse -Force }
        Move-Item -LiteralPath $staged -Destination $target
    }
}
finally {
    if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
}
Set-Content -LiteralPath $Marker -Value 'coding-agents-kit install marker: this directory is managed by install.ps1'


# The env file is created once, readable by the current user only, and never overwritten.
if (-not (Test-Path -LiteralPath $EnvFile)) {
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $EnvFile) | Out-Null
    Copy-Item -LiteralPath (Join-Path $Src 'lib\env.template') -Destination $EnvFile
    $who = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    & icacls $EnvFile /inheritance:r /grant:r "${who}:(R,W)" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "could not restrict $EnvFile to $who (icacls exit $LASTEXITCODE); restrict it yourself before adding keys" }
    $envNote = "created $EnvFile (readable by you only) - fill keys there, never in a chat"
} else {
    $envNote = "kept $EnvFile"
}

if (-not $NoPath) {
    $entries = Get-UserPathEntries
    if ($entries -notcontains $BinDir) { Set-UserPathEntries (@($BinDir) + $entries) }
    $pathNote = "added $BinDir to your user Path - open a NEW terminal"
} else {
    $pathNote = "Path not modified (-NoPath): run $BinDir\ak.cmd, or add $BinDir to Path"
}

$version = & (Join-Path $BinDir 'ak.cmd') --version
Write-Output "installed coding-agents-kit $version into $Prefix"
Write-Output $envNote
Write-Output $pathNote
Write-Output 'next: ak doctor      (and: ak install <cli> for any CLI you do not have yet)'
