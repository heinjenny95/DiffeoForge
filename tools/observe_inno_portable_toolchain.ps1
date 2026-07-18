param(
    [Parameter(Mandatory = $true)]
    [string]$Installer,
    [Parameter(Mandatory = $true)]
    [string]$ToolchainEvidence,
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-f]{64}$")]
    [string]$ExpectedToolchainEvidenceSha256,
    [Parameter(Mandatory = $true)]
    [string]$SignatureEvidence,
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-f]{64}$")]
    [string]$ExpectedSignatureEvidenceSha256,
    [Parameter(Mandatory = $true)]
    [string]$ProjectFile,
    [Parameter(Mandatory = $true)]
    [string]$ToolchainDirectory,
    [Parameter(Mandatory = $true)]
    [string]$ProbeOutputDirectory,
    [Parameter(Mandatory = $true)]
    [string]$EvidenceOutputDirectory,
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-f]{40}$")]
    [string]$SourceCommit,
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Assert-RealPath {
    param(
        [Parameter(Mandatory = $true)]
        [System.IO.FileSystemInfo]$Item,
        [Parameter(Mandatory = $true)]
        [string]$Label
    )
    if (($Item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "$Label must not be a symbolic path or junction: $($Item.FullName)"
    }
}

function Get-RealItem {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [string]$Label
    )
    $absolute = [System.IO.Path]::GetFullPath($Path)
    $item = Get-Item -LiteralPath $absolute -Force -ErrorAction Stop
    $cursor = $item
    while ($null -ne $cursor) {
        Assert-RealPath -Item $cursor -Label $Label
        if ($cursor -is [System.IO.DirectoryInfo]) {
            $cursor = $cursor.Parent
        } else {
            $cursor = $cursor.Directory
        }
    }
    return $item
}

function Write-NewUtf8File {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [string]$Content
    )
    if (Test-Path -LiteralPath $Path) {
        throw "Observation file already exists and will not be overwritten: $Path"
    }
    $encoding = New-Object System.Text.UTF8Encoding($false)
    $stream = [System.IO.File]::Open($Path, [System.IO.FileMode]::CreateNew)
    try {
        $writer = New-Object System.IO.StreamWriter($stream, $encoding)
        try {
            $writer.Write($Content)
            $writer.Flush()
            $stream.Flush($true)
        } finally {
            $writer.Dispose()
        }
    } finally {
        $stream.Dispose()
    }
}

function Get-LowerSha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Get-InstalledInventory {
    param([Parameter(Mandatory = $true)][System.IO.DirectoryInfo]$Root)
    $prefixLength = $Root.FullName.TrimEnd("\").Length + 1
    return @(
        Get-ChildItem -LiteralPath $Root.FullName -File -Recurse -Force |
            Sort-Object FullName |
            ForEach-Object {
                [pscustomobject][ordered]@{
                    path = $_.FullName.Substring($prefixLength).Replace("\", "/")
                    bytes = $_.Length
                    sha256 = Get-LowerSha256 -Path $_.FullName
                }
            }
    )
}

$windows = [System.Runtime.InteropServices.RuntimeInformation]::IsOSPlatform(
    [System.Runtime.InteropServices.OSPlatform]::Windows
)
if (-not $windows -or -not [Environment]::Is64BitProcess) {
    throw "Portable Inno toolchain observation requires 64-bit Windows."
}

$resolvedInstaller = Get-RealItem -Path $Installer -Label "Inno Setup installer"
$resolvedToolchainEvidence = Get-RealItem `
    -Path $ToolchainEvidence -Label "Inno toolchain prerequisite evidence"
$resolvedSignatureEvidence = Get-RealItem `
    -Path $SignatureEvidence -Label "Inno signature prerequisite evidence"
$resolvedProject = Get-RealItem -Path $ProjectFile -Label "Project file"
$resolvedToolchain = Get-RealItem -Path $ToolchainDirectory -Label "Portable toolchain directory"
$resolvedProbeOutput = Get-RealItem `
    -Path $ProbeOutputDirectory -Label "Compiler-probe output directory"
$resolvedEvidenceOutput = Get-RealItem `
    -Path $EvidenceOutputDirectory -Label "Portable evidence output directory"

if (
    $resolvedInstaller.PSIsContainer -or
    $resolvedToolchainEvidence.PSIsContainer -or
    $resolvedSignatureEvidence.PSIsContainer -or
    $resolvedProject.PSIsContainer
) {
    throw "Installer, prerequisite evidence, and project inputs must be files."
}
foreach ($directory in @($resolvedToolchain, $resolvedProbeOutput, $resolvedEvidenceOutput)) {
    if (-not $directory.PSIsContainer) {
        throw "Toolchain, probe output, and evidence output must be directories."
    }
    if (@(Get-ChildItem -LiteralPath $directory.FullName -Force).Count -ne 0) {
        throw "All three output directories must be empty and will not be overwritten."
    }
}

$repository = $resolvedProject.Directory.FullName
$observedCommit = (& git -C $repository rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $observedCommit -ne $SourceCommit) {
    throw "Observed Git commit differs from SourceCommit."
}
$dirty = & git -C $repository status --porcelain=v1 --untracked-files=all
if ($LASTEXITCODE -ne 0 -or $dirty) {
    throw "Portable Inno toolchain observation requires the exact clean Git worktree."
}

$commonArguments = @(
    $resolvedInstaller.FullName,
    "--toolchain-evidence", $resolvedToolchainEvidence.FullName,
    "--expect-toolchain-evidence-sha256", $ExpectedToolchainEvidenceSha256,
    "--signature-evidence", $resolvedSignatureEvidence.FullName,
    "--expect-signature-evidence-sha256", $ExpectedSignatureEvidenceSha256,
    "--project-file", $resolvedProject.FullName,
    "--toolchain-directory", $resolvedToolchain.FullName,
    "--probe-output-directory", $resolvedProbeOutput.FullName,
    "--evidence-output-directory", $resolvedEvidenceOutput.FullName,
    "--source-commit", $SourceCommit
)

# This is deliberately before Start-Process: failed prerequisite evidence forbids execution.
Push-Location $repository
try {
    & $Python tools\inno_portable_toolchain_evidence.py preflight @commonArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Portable Inno prerequisite preflight failed; installer execution is forbidden."
    }
} finally {
    Pop-Location
}

$observedAt = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ss.fffffffZ")
$logPath = Join-Path $resolvedEvidenceOutput.FullName "inno-portable-install.log"
$installObservationPath = Join-Path `
    $resolvedEvidenceOutput.FullName "inno-portable-install-observation.json"
$authenticodeObservationPath = Join-Path `
    $resolvedEvidenceOutput.FullName "inno-portable-authenticode-observation.json"
$probeObservationPath = Join-Path `
    $resolvedEvidenceOutput.FullName "inno-compiler-probe-observation.json"

$installerArguments = @(
    "/PORTABLE=1",
    "/CURRENTUSER",
    "/VERYSILENT",
    "/SUPPRESSMSGBOXES",
    "/NORESTART",
    "/SP-",
    "/NOICONS",
    "/LANG=english",
    "/DIR=`"$($resolvedToolchain.FullName)`"",
    "/LOG=`"$logPath`""
)
$process = Start-Process `
    -FilePath $resolvedInstaller.FullName `
    -ArgumentList $installerArguments `
    -Wait `
    -PassThru `
    -WindowStyle Hidden
if ($process.ExitCode -ne 0) {
    throw "Portable Inno preparation failed with exit code $($process.ExitCode)."
}
if (-not (Test-Path -LiteralPath $logPath -PathType Leaf)) {
    throw "Portable Inno preparation did not create the required log."
}

$inventory = Get-InstalledInventory -Root $resolvedToolchain
$directoryCount = @(
    Get-ChildItem -LiteralPath $resolvedToolchain.FullName -Directory -Recurse -Force
).Count
$totalBytes = ($inventory | Measure-Object -Property bytes -Sum).Sum
$uninstallerCount = @(
    $inventory | Where-Object { $_.path -match "(^|/)unins.*\.(exe|dat|msg)$" }
).Count
$installObservation = [ordered]@{
    schema_version = "0.1"
    observed_at = $observedAt
    installer_path = $resolvedInstaller.FullName
    installer_bytes = $resolvedInstaller.Length
    installer_sha256 = Get-LowerSha256 -Path $resolvedInstaller.FullName
    command = $installerArguments
    exit_code = $process.ExitCode
    installation_directory = $resolvedToolchain.FullName
    log_path = $logPath
    installed_inventory = $inventory
    installed_file_count = $inventory.Count
    installed_directory_count = $directoryCount
    installed_total_bytes = $totalBytes
    uninstaller_file_count = $uninstallerCount
    portable_mode = $true
    current_user = $true
    restart = $false
    system_install_claim = $false
}
Write-NewUtf8File `
    -Path $installObservationPath `
    -Content (($installObservation | ConvertTo-Json -Compress -Depth 7) + "`n")

$components = @()
foreach ($name in @("ISCC.exe", "ISCmplr.dll", "ISPP.dll", "ISSigTool.exe")) {
    $path = Join-Path $resolvedToolchain.FullName $name
    $item = Get-RealItem -Path $path -Label "Portable Inno component $name"
    $signature = Get-AuthenticodeSignature -LiteralPath $item.FullName
    if ($signature.Status.ToString() -ne "Valid") {
        throw "Portable Inno component Authenticode signature differs: $name"
    }
    if ($null -eq $signature.SignerCertificate -or $null -eq $signature.TimeStamperCertificate) {
        throw "Portable Inno component certificate observation is incomplete: $name"
    }
    $components += [ordered]@{
        name = $name
        path = $item.FullName
        bytes = $item.Length
        sha256 = Get-LowerSha256 -Path $item.FullName
        status = $signature.Status.ToString()
        signer_subject = $signature.SignerCertificate.Subject
        signer_issuer = $signature.SignerCertificate.Issuer
        signer_thumbprint = $signature.SignerCertificate.Thumbprint
        timestamp_subject = $signature.TimeStamperCertificate.Subject
        timestamp_thumbprint = $signature.TimeStamperCertificate.Thumbprint
    }
}
$authenticodeObservation = [ordered]@{
    schema_version = "0.1"
    observed_at = $observedAt
    components = $components
}
Write-NewUtf8File `
    -Path $authenticodeObservationPath `
    -Content (($authenticodeObservation | ConvertTo-Json -Compress -Depth 6) + "`n")

$probeScript = Get-RealItem `
    -Path (Join-Path $repository "distribution\windows\InnoCompilerProbe.iss") `
    -Label "Inno compiler probe script"
$iscc = Get-RealItem `
    -Path (Join-Path $resolvedToolchain.FullName "ISCC.exe") `
    -Label "ISCC compiler"
$probeArguments = @(
    "/Qp",
    "/O+",
    "/O$($resolvedProbeOutput.FullName)",
    "/FDiffeoForge-Compiler-Probe",
    $probeScript.FullName
)
$rawProbeOutput = & $iscc.FullName @probeArguments 2>&1
$probeExitCode = $LASTEXITCODE
$probeOutputLines = @($rawProbeOutput | ForEach-Object { $_.ToString() })
if ($probeExitCode -ne 0) {
    throw "Inno compiler probe failed with exit code $probeExitCode."
}
$probeOutputs = @(Get-ChildItem -LiteralPath $resolvedProbeOutput.FullName -Force)
if (
    $probeOutputs.Count -ne 1 -or
    $probeOutputs[0].PSIsContainer -or
    $probeOutputs[0].Name -ne "DiffeoForge-Compiler-Probe.exe"
) {
    throw "Inno compiler probe output differs from the exact one-file boundary."
}
$probeOutput = $probeOutputs[0]
$probeObservation = [ordered]@{
    schema_version = "0.1"
    observed_at = $observedAt
    program_path = $iscc.FullName
    program_bytes = $iscc.Length
    program_sha256 = Get-LowerSha256 -Path $iscc.FullName
    script_path = $probeScript.FullName
    script_bytes = $probeScript.Length
    script_sha256 = Get-LowerSha256 -Path $probeScript.FullName
    command = $probeArguments
    exit_code = $probeExitCode
    output_lines = $probeOutputLines
    output_path = $probeOutput.FullName
    output_bytes = $probeOutput.Length
    output_sha256 = Get-LowerSha256 -Path $probeOutput.FullName
    payload_free = $true
    distribution_authorized = $false
}
Write-NewUtf8File `
    -Path $probeObservationPath `
    -Content (($probeObservation | ConvertTo-Json -Compress -Depth 6) + "`n")

Push-Location $repository
try {
    & $Python tools\inno_portable_toolchain_evidence.py create @commonArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Portable Inno toolchain evidence creation failed."
    }
} finally {
    Pop-Location
}

Write-Output "Prepared the exact portable Inno toolchain and compiled the payload-free probe."
Write-Output "Portable toolchain directory: $($resolvedToolchain.FullName)"
Write-Output "Portable evidence directory: $($resolvedEvidenceOutput.FullName)"
Write-Output "DiffeoForge installer built: false"
Write-Output "Release or distribution authorized: false"
