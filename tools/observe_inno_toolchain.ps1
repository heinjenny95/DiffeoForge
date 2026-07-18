param(
    [Parameter(Mandatory = $true)]
    [string]$Asset,
    [Parameter(Mandatory = $true)]
    [string]$ProjectFile,
    [Parameter(Mandatory = $true)]
    [string]$OutputDirectory,
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-f]{40}$")]
    [string]$SourceCommit,
    [string]$Python = "python",
    [string]$GitHub = "gh.exe"
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

$windows = [System.Runtime.InteropServices.RuntimeInformation]::IsOSPlatform(
    [System.Runtime.InteropServices.OSPlatform]::Windows
)
if (-not $windows -or -not [Environment]::Is64BitProcess) {
    throw "The Inno Setup authenticity observation requires 64-bit Windows."
}

$resolvedAsset = Get-RealItem -Path $Asset -Label "Inno Setup asset"
$resolvedProject = Get-RealItem -Path $ProjectFile -Label "Project file"
$resolvedOutput = Get-RealItem -Path $OutputDirectory -Label "Observation output"
if (-not $resolvedAsset.PSIsContainer -and $resolvedAsset.Name -ne "innosetup-7.0.2-x64.exe") {
    throw "Inno Setup asset has the wrong file name."
}
if ($resolvedAsset.PSIsContainer -or $resolvedProject.PSIsContainer -or -not $resolvedOutput.PSIsContainer) {
    throw "Asset and project must be files and output must be a directory."
}
if (@(Get-ChildItem -LiteralPath $resolvedOutput.FullName -Force).Count -ne 0) {
    throw "Observation output must be empty and will not be overwritten."
}
$repository = $resolvedProject.Directory.FullName
$observedCommit = (& git -C $repository rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $observedCommit -ne $SourceCommit) {
    throw "Observed Git commit differs from SourceCommit."
}
$dirty = & git -C $repository status --porcelain=v1 --untracked-files=all
if ($LASTEXITCODE -ne 0 -or $dirty) {
    throw "Toolchain observation requires the exact clean Git worktree."
}

$assetHash = (Get-FileHash -LiteralPath $resolvedAsset.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
if ($resolvedAsset.Length -ne 17020192 -or $assetHash -ne "5ad54ca3def786f8f4212552e54cc6d8d61329e2d24a1cfee0571d42c2684ff1") {
    throw "Inno Setup asset size or SHA-256 differs."
}

$githubCommand = Get-Command $GitHub -CommandType Application -ErrorAction Stop
$githubItem = Get-RealItem -Path $githubCommand.Source -Label "GitHub CLI verifier"
$githubHash = (Get-FileHash -LiteralPath $githubItem.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
$githubVersion = (& $githubItem.FullName version 2>&1) -join "`n"
if ($LASTEXITCODE -ne 0 -or $githubVersion -notmatch "^gh version [0-9]+\.[0-9]+\.[0-9]+") {
    throw "Could not observe a supported GitHub CLI version."
}

$observedAt = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ss.fffffffZ")
$commandArguments = @(
    "release",
    "verify-asset",
    $resolvedAsset.FullName,
    "--repo",
    "jrsoftware/issrc",
    "--format",
    "json"
)
$attestationOutput = (& $githubItem.FullName @commandArguments 2>&1) -join "`n"
$attestationExitCode = $LASTEXITCODE
if ($attestationExitCode -ne 0) {
    throw "GitHub release-attestation verification failed with exit code $attestationExitCode."
}
try {
    $null = $attestationOutput | ConvertFrom-Json
} catch {
    throw "GitHub release-attestation output is not JSON."
}

$signature = Get-AuthenticodeSignature -LiteralPath $resolvedAsset.FullName
if ($signature.Status.ToString() -ne "Valid") {
    throw "Inno Setup Authenticode signature is not valid: $($signature.Status)"
}
$expectedPublisher = "CN=Pyrsys B.V., O=Pyrsys B.V., S=Noord-Holland, C=NL"
if ($signature.SignerCertificate.Subject -ne $expectedPublisher) {
    throw "Inno Setup Authenticode publisher differs: $($signature.SignerCertificate.Subject)"
}
if ($null -eq $signature.TimeStamperCertificate) {
    throw "Inno Setup Authenticode timestamp certificate is missing."
}

$attestationPath = Join-Path $resolvedOutput.FullName "inno-release-attestation.json"
$authenticodePath = Join-Path $resolvedOutput.FullName "inno-authenticode-observation.json"
$verifierPath = Join-Path $resolvedOutput.FullName "inno-release-verifier-observation.json"
Write-NewUtf8File -Path $attestationPath -Content ($attestationOutput.TrimEnd() + "`n")

$authenticode = [ordered]@{
    schema_version = "0.1"
    observed_at = $observedAt
    asset_path = $resolvedAsset.FullName
    asset_sha256 = $assetHash
    status = $signature.Status.ToString()
    status_message = $signature.StatusMessage
    signer_subject = $signature.SignerCertificate.Subject
    signer_issuer = $signature.SignerCertificate.Issuer
    signer_thumbprint = $signature.SignerCertificate.Thumbprint
    signer_not_before = $signature.SignerCertificate.NotBefore.ToUniversalTime().ToString("o")
    signer_not_after = $signature.SignerCertificate.NotAfter.ToUniversalTime().ToString("o")
    timestamp_subject = $signature.TimeStamperCertificate.Subject
    timestamp_thumbprint = $signature.TimeStamperCertificate.Thumbprint
}
Write-NewUtf8File -Path $authenticodePath -Content (($authenticode | ConvertTo-Json -Compress -Depth 4) + "`n")

$verifier = [ordered]@{
    schema_version = "0.1"
    observed_at = $observedAt
    program_path = $githubItem.FullName
    program_bytes = $githubItem.Length
    program_sha256 = $githubHash
    version_output = $githubVersion.TrimEnd()
    command = $commandArguments
    exit_code = $attestationExitCode
}
Write-NewUtf8File -Path $verifierPath -Content (($verifier | ConvertTo-Json -Compress -Depth 4) + "`n")

Push-Location $repository
try {
    & $Python tools\inno_toolchain_evidence.py create $resolvedAsset.FullName `
        --project-file $resolvedProject.FullName `
        --output-directory $resolvedOutput.FullName `
        --source-commit $SourceCommit
    if ($LASTEXITCODE -ne 0) {
        throw "Inno toolchain evidence creation failed."
    }
} finally {
    Pop-Location
}

Write-Output "Observed authentic, non-executed Inno Setup asset: $($resolvedAsset.FullName)"
Write-Output "Toolchain evidence directory: $($resolvedOutput.FullName)"
Write-Output "Downloaded asset execution authorized: false"
