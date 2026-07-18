param(
    [Parameter(Mandatory = $true)]
    [string]$Plan,
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-f]{64}$")]
    [string]$ExpectedPlanSha256,
    [Parameter(Mandatory = $true)]
    [string]$PortableEvidence,
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-f]{64}$")]
    [string]$ExpectedPortableEvidenceSha256,
    [Parameter(Mandatory = $true)]
    [string]$ProjectFile,
    [Parameter(Mandatory = $true)]
    [string]$EvidenceOutputDirectory,
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-f]{40}$")]
    [string]$ObserverSourceCommit,
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
        throw "Evidence file already exists and will not be overwritten: $Path"
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

$windows = [System.Runtime.InteropServices.RuntimeInformation]::IsOSPlatform(
    [System.Runtime.InteropServices.OSPlatform]::Windows
)
if (-not $windows -or -not [Environment]::Is64BitProcess) {
    throw "Installer build observation requires 64-bit Windows."
}

$resolvedPlan = Get-RealItem -Path $Plan -Label "Installer build plan"
$resolvedPortableEvidence = Get-RealItem `
    -Path $PortableEvidence -Label "Portable Inno toolchain evidence"
$resolvedProject = Get-RealItem -Path $ProjectFile -Label "Project file"
$resolvedEvidenceOutput = Get-RealItem `
    -Path $EvidenceOutputDirectory -Label "Installer build evidence output"
if (
    $resolvedPlan.PSIsContainer -or
    $resolvedPortableEvidence.PSIsContainer -or
    $resolvedProject.PSIsContainer -or
    -not $resolvedEvidenceOutput.PSIsContainer
) {
    throw "Plan, portable evidence, and project must be files; evidence output must be a directory."
}
if (@(Get-ChildItem -LiteralPath $resolvedEvidenceOutput.FullName -Force).Count -ne 0) {
    throw "Installer build evidence output must be empty and will not be overwritten."
}

$repository = $resolvedProject.Directory.FullName
$observedCommit = (& git -C $repository rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $observedCommit -ne $ObserverSourceCommit) {
    throw "Observed Git commit differs from ObserverSourceCommit."
}
$dirty = & git -C $repository status --porcelain=v1 --untracked-files=all
if ($LASTEXITCODE -ne 0 -or $dirty) {
    throw "Installer build observation requires the exact clean Git worktree."
}

$commonArguments = @(
    $resolvedPlan.FullName,
    "--expect-plan-sha256", $ExpectedPlanSha256,
    "--portable-evidence", $resolvedPortableEvidence.FullName,
    "--expect-portable-evidence-sha256", $ExpectedPortableEvidenceSha256,
    "--project-file", $resolvedProject.FullName,
    "--evidence-output-directory", $resolvedEvidenceOutput.FullName,
    "--observer-source-commit", $ObserverSourceCommit
)

# This must remain before ISCC: failed retained evidence forbids compilation.
Push-Location $repository
try {
    & $Python tools\installer_build_evidence.py preflight @commonArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Installer build preflight failed; compiler execution is forbidden."
    }
} finally {
    Pop-Location
}

$planDocument = Get-Content -LiteralPath $resolvedPlan.FullName -Raw | ConvertFrom-Json
$portableDocument = Get-Content `
    -LiteralPath $resolvedPortableEvidence.FullName -Raw | ConvertFrom-Json
if ($planDocument.source.release_candidate -ne $false) {
    throw "Engineering wrapper refuses a release-candidate plan."
}
$compilerPath = Join-Path `
    $portableDocument.portable_install.installation_directory "ISCC.exe"
$compiler = Get-RealItem -Path $compilerPath -Label "Portable ISCC compiler"
if ($compiler.PSIsContainer -or $compiler.Name -ne "ISCC.exe") {
    throw "Portable compiler path differs."
}
$compilerArguments = @($planDocument.compiler.arguments | ForEach-Object { $_.ToString() })
if ($compilerArguments.Count -ne 9) {
    throw "Installer plan compiler vector must contain exactly nine arguments."
}

$setupPath = [System.IO.Path]::GetFullPath($planDocument.output.setup_path)
$setupFilename = $planDocument.output.setup_filename.ToString()
$setupSidecarPath = "$setupPath.sha256"
if (
    (Test-Path -LiteralPath $setupPath) -or
    (Test-Path -LiteralPath $setupSidecarPath)
) {
    throw "Setup output or sidecar already exists and will not be overwritten."
}

$observedAt = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ss.fffffffZ")
$rawCompilerOutput = & $compiler.FullName @compilerArguments 2>&1
$compilerExitCode = $LASTEXITCODE
$outputLines = @($rawCompilerOutput | ForEach-Object { $_.ToString() })
if ($compilerExitCode -ne 0) {
    throw "ISCC installer build failed with exit code $compilerExitCode."
}
$setup = Get-RealItem -Path $setupPath -Label "Engineering setup output"
if ($setup.PSIsContainer -or $setup.Name -ne $setupFilename) {
    throw "ISCC output differs from the exact setup filename."
}
$setupAuthenticode = Get-AuthenticodeSignature -LiteralPath $setup.FullName
if ($setupAuthenticode.Status.ToString() -ne "NotSigned") {
    throw "Engineering setup unexpectedly has Authenticode status $($setupAuthenticode.Status)."
}
$setupSha256 = Get-LowerSha256 -Path $setup.FullName
Write-NewUtf8File `
    -Path $setupSidecarPath `
    -Content "$setupSha256  $setupFilename`n"
$setupSidecar = Get-RealItem -Path $setupSidecarPath -Label "Setup SHA-256 sidecar"

$observationPath = Join-Path `
    $resolvedEvidenceOutput.FullName "installer-compiler-observation.json"
$observation = [ordered]@{
    schema_version = "0.1"
    observed_at = $observedAt
    observer_source_commit = $ObserverSourceCommit
    program_path = $compiler.FullName
    program_bytes = $compiler.Length
    program_sha256 = Get-LowerSha256 -Path $compiler.FullName
    plan_path = $resolvedPlan.FullName
    plan_sha256 = Get-LowerSha256 -Path $resolvedPlan.FullName
    command = $compilerArguments
    exit_code = $compilerExitCode
    output_lines = $outputLines
    setup_path = $setup.FullName
    setup_bytes = $setup.Length
    setup_sha256 = $setupSha256
    setup_authenticode_status = $setupAuthenticode.Status.ToString()
    setup_execution = $false
    distribution_authorized = $false
}
Write-NewUtf8File `
    -Path $observationPath `
    -Content (($observation | ConvertTo-Json -Compress -Depth 6) + "`n")

Push-Location $repository
try {
    & $Python tools\installer_build_evidence.py create @commonArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Installer build evidence creation failed."
    }
} finally {
    Pop-Location
}

Write-Output "Built and hashed one engineering-only DiffeoForge setup executable."
Write-Output "Setup path: $($setup.FullName)"
Write-Output "Setup SHA-256: $setupSha256"
Write-Output "Setup executed: false"
Write-Output "Distribution or release authorized: false"
