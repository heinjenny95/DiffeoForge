param(
    [Parameter(Mandatory = $true)][string]$Archive,
    [Parameter(Mandatory = $true)][string]$ExpectedSha256,
    [Parameter(Mandatory = $true)][string]$InstallRoot,
    [string]$Distribution = "DiffeoForge-Reference-4.3",
    [string]$Executable = "/opt/diffeoforge/reference/bin/deformetrica",
    [string]$ExpectedVersion = "4.3.0"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ($Distribution -cne "DiffeoForge-Reference-4.3") {
    throw "The installer may manage only the DiffeoForge-Reference-4.3 distribution."
}
if ($Executable -cne "/opt/diffeoforge/reference/bin/deformetrica") {
    throw "The managed Deformetrica executable identity differs."
}
$ExpectedSha256 = $ExpectedSha256.Trim().ToLowerInvariant()
if ($ExpectedSha256 -notmatch "^[0-9a-f]{64}$") {
    throw "Expected runtime SHA-256 must contain 64 lowercase hexadecimal characters."
}

$archivePath = [IO.Path]::GetFullPath($Archive)
if (-not (Test-Path -LiteralPath $archivePath -PathType Leaf)) {
    throw "The bundled reference-runtime archive is missing: $archivePath"
}
$archiveItem = Get-Item -LiteralPath $archivePath -Force
if ($archiveItem.Attributes -band [IO.FileAttributes]::ReparsePoint) {
    throw "The bundled reference-runtime archive must not be a reparse path."
}
$observedSha256 = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($observedSha256 -cne $ExpectedSha256) {
    throw "The bundled reference-runtime archive failed its SHA-256 check."
}

$wsl = Get-Command wsl.exe -ErrorAction SilentlyContinue
if ($null -eq $wsl) {
    throw "Windows Subsystem for Linux is unavailable. Enable WSL, restart Windows if requested, and run DiffeoForge Setup again."
}
$installed = @(& $wsl.Source --list --quiet | ForEach-Object {
    ($_.ToString() -replace "`0", "").Trim()
} | Where-Object { $_ })
if ($LASTEXITCODE -ne 0) {
    throw "Windows Subsystem for Linux could not list installed distributions."
}
if ($installed -contains $Distribution) {
    $existingOutput = @(& $wsl.Source -d $Distribution -- $Executable --help 2>&1) -join "`n"
    if ($LASTEXITCODE -ne 0 -or $existingOutput -notmatch "(?<![0-9])$([regex]::Escape($ExpectedVersion))(?![0-9])") {
        throw "The existing managed runtime is damaged. Use DiffeoForge Repair; it was not overwritten."
    }
    Write-Output "Verified existing managed DiffeoForge reference runtime."
    exit 0
}

$root = [IO.Path]::GetFullPath($InstallRoot)
$target = Join-Path $root $Distribution
$rootPrefix = $root.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
if (-not $target.StartsWith($rootPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "The managed runtime target escaped its dedicated installation root."
}
if (Test-Path -LiteralPath $target) {
    throw "The managed runtime target already exists without a registered distribution: $target"
}
New-Item -ItemType Directory -Path $root -Force | Out-Null

$registered = $false
try {
    & $wsl.Source --import $Distribution $target $archivePath --version 2
    if ($LASTEXITCODE -ne 0) {
        throw "WSL could not import the bundled DiffeoForge reference runtime."
    }
    $registered = $true
    $output = @(& $wsl.Source -d $Distribution -- $Executable --help 2>&1) -join "`n"
    if ($LASTEXITCODE -ne 0 -or $output -notmatch "(?<![0-9])$([regex]::Escape($ExpectedVersion))(?![0-9])") {
        throw "The imported runtime did not verify as Deformetrica $ExpectedVersion."
    }
    Write-Output "Installed and verified Deformetrica $ExpectedVersion in $Distribution."
} catch {
    if ($registered) {
        & $wsl.Source --unregister $Distribution | Out-Null
    }
    if (Test-Path -LiteralPath $target) {
        $resolvedTarget = (Get-Item -LiteralPath $target -Force).FullName
        if (-not $resolvedTarget.StartsWith($rootPrefix, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to clean a failed import outside the managed runtime root."
        }
        Remove-Item -LiteralPath $resolvedTarget -Recurse -Force
    }
    throw
}
