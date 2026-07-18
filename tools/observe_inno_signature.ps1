param(
    [Parameter(Mandatory = $true)]
    [string]$Installer,
    [Parameter(Mandatory = $true)]
    [string]$Signature,
    [Parameter(Mandatory = $true)]
    [string]$PublicKey,
    [Parameter(Mandatory = $true)]
    [string]$SignatureTool,
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

function Get-LowerSha256 {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Invoke-GitHubJson {
    param(
        [Parameter(Mandatory = $true)]
        [System.IO.FileInfo]$Program,
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,
        [Parameter(Mandatory = $true)]
        [string]$Label
    )
    $output = (& $Program.FullName @Arguments 2>&1) -join "`n"
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "$Label failed with exit code $exitCode."
    }
    try {
        $null = $output | ConvertFrom-Json
    } catch {
        throw "$Label output is not JSON."
    }
    return $output.TrimEnd() + "`n"
}

$windows = [System.Runtime.InteropServices.RuntimeInformation]::IsOSPlatform(
    [System.Runtime.InteropServices.OSPlatform]::Windows
)
if (-not $windows -or -not [Environment]::Is64BitProcess) {
    throw "The ISSigTool signature observation requires 64-bit Windows."
}

$resolvedInstaller = Get-RealItem -Path $Installer -Label "Inno Setup installer"
$resolvedSignature = Get-RealItem -Path $Signature -Label "Inno Setup signature"
$resolvedKey = Get-RealItem -Path $PublicKey -Label "Inno public key"
$resolvedTool = Get-RealItem -Path $SignatureTool -Label "ISSigTool"
$resolvedProject = Get-RealItem -Path $ProjectFile -Label "Project file"
$resolvedOutput = Get-RealItem -Path $OutputDirectory -Label "Observation output"

$expectedNames = [ordered]@{
    Installer = "innosetup-7.0.2-x64.exe"
    Signature = "innosetup-7.0.2-x64.exe.issig"
    PublicKey = "def02.ispublickey"
    SignatureTool = "ISSigTool.exe"
}
$resolvedInputs = [ordered]@{
    Installer = $resolvedInstaller
    Signature = $resolvedSignature
    PublicKey = $resolvedKey
    SignatureTool = $resolvedTool
}
foreach ($name in $resolvedInputs.Keys) {
    $item = $resolvedInputs[$name]
    if ($item.PSIsContainer -or $item.Name -ne $expectedNames[$name]) {
        throw "$name has the wrong type or file name."
    }
}
if (-not $resolvedOutput.PSIsContainer -or $resolvedProject.PSIsContainer) {
    throw "Project must be a file and output must be a directory."
}
if ($resolvedSignature.Directory.FullName -ne $resolvedInstaller.Directory.FullName) {
    throw "The .issig file must be adjacent to the installer."
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
    throw "ISSigTool observation requires the exact clean Git worktree."
}

$expectedFiles = [ordered]@{
    Installer = @{ Bytes = 17020192; Sha256 = "5ad54ca3def786f8f4212552e54cc6d8d61329e2d24a1cfee0571d42c2684ff1" }
    Signature = @{ Bytes = 380; Sha256 = "b85f4a9c527ee573d308840e859ff3ca99c8a750acb259d51f111301c7ef71bd" }
    PublicKey = @{ Bytes = 248; Sha256 = "32bea6bceb4ac7c4e6b3becdf3fb38de77378c5e76d494ab907d87cfab9e597b" }
    SignatureTool = @{ Bytes = 919184; Sha256 = "aea490d45665a88c0c832d25647d21c1b87962efedb25668caec05678e0fd7c6" }
}
foreach ($name in $resolvedInputs.Keys) {
    $item = $resolvedInputs[$name]
    $hash = Get-LowerSha256 -Path $item.FullName
    if ($item.Length -ne $expectedFiles[$name].Bytes -or $hash -ne $expectedFiles[$name].Sha256) {
        throw "$name size or SHA-256 differs."
    }
}

$githubCommand = Get-Command $GitHub -CommandType Application -ErrorAction Stop
$githubItem = Get-RealItem -Path $githubCommand.Source -Label "GitHub CLI verifier"
$githubHash = Get-LowerSha256 -Path $githubItem.FullName
$githubVersion = (& $githubItem.FullName version 2>&1) -join "`n"
if ($LASTEXITCODE -ne 0 -or $githubVersion -notmatch "^gh version [0-9]+\.[0-9]+\.[0-9]+") {
    throw "Could not observe a supported GitHub CLI version."
}

$observedAt = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ss.fffffffZ")
$toolReleaseArguments = @(
    "release", "verify-asset", "is-6_7_3", $resolvedTool.FullName,
    "--repo", "jrsoftware/issrc", "--format", "json"
)
$signatureReleaseArguments = @(
    "release", "verify-asset", "is-7_0_2", $resolvedSignature.FullName,
    "--repo", "jrsoftware/issrc", "--format", "json"
)
$tagArguments = @(
    "api",
    "repos/jrsoftware/issrc/git/tags/d2509df69f828a7148294e29b2ca252c3250210c"
)
$keyArguments = @(
    "api",
    "repos/jrsoftware/issrc/contents/def02.ispublickey?ref=c25dc6479cdc3be28e682a025fcf60765bba3de0"
)

$toolAttestation = Invoke-GitHubJson `
    -Program $githubItem -Arguments $toolReleaseArguments -Label "ISSigTool release verification"
$signatureAttestation = Invoke-GitHubJson `
    -Program $githubItem -Arguments $signatureReleaseArguments -Label "Signature release verification"
$tagObservation = Invoke-GitHubJson `
    -Program $githubItem -Arguments $tagArguments -Label "Inno release tag observation"
$keyObservation = Invoke-GitHubJson `
    -Program $githubItem -Arguments $keyArguments -Label "Public-key content observation"

$toolAuthenticode = Get-AuthenticodeSignature -LiteralPath $resolvedTool.FullName
if ($toolAuthenticode.Status.ToString() -ne "Valid") {
    throw "ISSigTool Authenticode signature is not valid: $($toolAuthenticode.Status)"
}
$expectedPublisher = "CN=Pyrsys B.V., O=Pyrsys B.V., S=Noord-Holland, C=NL"
if ($toolAuthenticode.SignerCertificate.Subject -ne $expectedPublisher) {
    throw "ISSigTool Authenticode publisher differs: $($toolAuthenticode.SignerCertificate.Subject)"
}
if ($null -eq $toolAuthenticode.TimeStamperCertificate) {
    throw "ISSigTool Authenticode timestamp certificate is missing."
}

$toolAttestationPath = Join-Path $resolvedOutput.FullName "issigtool-release-attestation.json"
$toolAuthenticodePath = Join-Path $resolvedOutput.FullName "issigtool-authenticode-observation.json"
$toolVerifierPath = Join-Path $resolvedOutput.FullName "issigtool-release-verifier-observation.json"
$signatureAttestationPath = Join-Path $resolvedOutput.FullName "inno-signature-release-attestation.json"
$signatureVerifierPath = Join-Path $resolvedOutput.FullName "inno-signature-release-verifier-observation.json"
$tagPath = Join-Path $resolvedOutput.FullName "inno-release-tag-observation.json"
$keyPath = Join-Path $resolvedOutput.FullName "inno-public-key-content-observation.json"
$apiVerifierPath = Join-Path $resolvedOutput.FullName "inno-release-api-verifier-observation.json"
$executionPath = Join-Path $resolvedOutput.FullName "issigtool-verification-observation.json"

Write-NewUtf8File -Path $toolAttestationPath -Content $toolAttestation
Write-NewUtf8File -Path $signatureAttestationPath -Content $signatureAttestation
Write-NewUtf8File -Path $tagPath -Content $tagObservation
Write-NewUtf8File -Path $keyPath -Content $keyObservation

$authenticode = [ordered]@{
    schema_version = "0.1"
    observed_at = $observedAt
    asset_path = $resolvedTool.FullName
    asset_sha256 = $expectedFiles.SignatureTool.Sha256
    status = $toolAuthenticode.Status.ToString()
    status_message = $toolAuthenticode.StatusMessage
    signer_subject = $toolAuthenticode.SignerCertificate.Subject
    signer_issuer = $toolAuthenticode.SignerCertificate.Issuer
    signer_thumbprint = $toolAuthenticode.SignerCertificate.Thumbprint
    signer_not_before = $toolAuthenticode.SignerCertificate.NotBefore.ToUniversalTime().ToString("o")
    signer_not_after = $toolAuthenticode.SignerCertificate.NotAfter.ToUniversalTime().ToString("o")
    timestamp_subject = $toolAuthenticode.TimeStamperCertificate.Subject
    timestamp_thumbprint = $toolAuthenticode.TimeStamperCertificate.Thumbprint
}
Write-NewUtf8File `
    -Path $toolAuthenticodePath `
    -Content (($authenticode | ConvertTo-Json -Compress -Depth 4) + "`n")

function New-ReleaseVerifierRecord {
    param([string[]]$Arguments)
    return [ordered]@{
        schema_version = "0.1"
        observed_at = $observedAt
        program_path = $githubItem.FullName
        program_bytes = $githubItem.Length
        program_sha256 = $githubHash
        version_output = $githubVersion.TrimEnd()
        command = $Arguments
        exit_code = 0
    }
}
$toolVerifier = New-ReleaseVerifierRecord -Arguments $toolReleaseArguments
$signatureVerifier = New-ReleaseVerifierRecord -Arguments $signatureReleaseArguments
Write-NewUtf8File `
    -Path $toolVerifierPath `
    -Content (($toolVerifier | ConvertTo-Json -Compress -Depth 5) + "`n")
Write-NewUtf8File `
    -Path $signatureVerifierPath `
    -Content (($signatureVerifier | ConvertTo-Json -Compress -Depth 5) + "`n")

$apiVerifier = [ordered]@{
    schema_version = "0.1"
    observed_at = $observedAt
    program_path = $githubItem.FullName
    program_bytes = $githubItem.Length
    program_sha256 = $githubHash
    version_output = $githubVersion.TrimEnd()
    commands = @(
        [ordered]@{
            arguments = $tagArguments
            exit_code = 0
            output_file = "inno-release-tag-observation.json"
            output_sha256 = Get-LowerSha256 -Path $tagPath
        },
        [ordered]@{
            arguments = $keyArguments
            exit_code = 0
            output_file = "inno-public-key-content-observation.json"
            output_sha256 = Get-LowerSha256 -Path $keyPath
        }
    )
}
Write-NewUtf8File `
    -Path $apiVerifierPath `
    -Content (($apiVerifier | ConvertTo-Json -Compress -Depth 6) + "`n")

Push-Location $repository
try {
    & $Python tools\inno_signature_evidence.py preflight $resolvedInstaller.FullName `
        --signature $resolvedSignature.FullName `
        --public-key $resolvedKey.FullName `
        --signature-tool $resolvedTool.FullName `
        --project-file $resolvedProject.FullName `
        --output-directory $resolvedOutput.FullName `
        --source-commit $SourceCommit
    if ($LASTEXITCODE -ne 0) {
        throw "ISSigTool prerequisite preflight failed; verifier execution is forbidden."
    }
} finally {
    Pop-Location
}

$hashesBefore = [ordered]@{
    installer_sha256 = Get-LowerSha256 -Path $resolvedInstaller.FullName
    signature_sha256 = Get-LowerSha256 -Path $resolvedSignature.FullName
    public_key_sha256 = Get-LowerSha256 -Path $resolvedKey.FullName
    signature_tool_sha256 = Get-LowerSha256 -Path $resolvedTool.FullName
}
$executionArguments = @(
    "--key-file=$($resolvedKey.FullName)",
    "verify",
    $resolvedInstaller.FullName
)
$rawExecutionOutput = & $resolvedTool.FullName @executionArguments 2>&1
$executionExitCode = $LASTEXITCODE
$outputLines = @($rawExecutionOutput | ForEach-Object { $_.ToString() })
$hashesAfter = [ordered]@{
    installer_sha256 = Get-LowerSha256 -Path $resolvedInstaller.FullName
    signature_sha256 = Get-LowerSha256 -Path $resolvedSignature.FullName
    public_key_sha256 = Get-LowerSha256 -Path $resolvedKey.FullName
    signature_tool_sha256 = Get-LowerSha256 -Path $resolvedTool.FullName
}
if ($executionExitCode -ne 0) {
    throw "ISSigTool verification failed with exit code $executionExitCode."
}
$expectedOutput = "$($resolvedInstaller.FullName): OK"
if ($outputLines.Count -ne 1 -or $outputLines[0] -ne $expectedOutput) {
    throw "ISSigTool verification output differs from the exact success record."
}
foreach ($name in $hashesBefore.Keys) {
    if ($hashesBefore[$name] -ne $hashesAfter[$name]) {
        throw "Input changed during ISSigTool verification: $name"
    }
}

$execution = [ordered]@{
    schema_version = "0.1"
    observed_at = $observedAt
    program_path = $resolvedTool.FullName
    program_bytes = $resolvedTool.Length
    program_sha256 = $hashesBefore.signature_tool_sha256
    signature_path = $resolvedSignature.FullName
    command = $executionArguments
    exit_code = $executionExitCode
    output_lines = $outputLines
    inputs_before = $hashesBefore
    inputs_after = $hashesAfter
    signature_tool_execution_scope = "verify_exact_installer_signature_only"
    installer_execution = $false
}
Write-NewUtf8File `
    -Path $executionPath `
    -Content (($execution | ConvertTo-Json -Compress -Depth 6) + "`n")

Push-Location $repository
try {
    & $Python tools\inno_signature_evidence.py create $resolvedInstaller.FullName `
        --signature $resolvedSignature.FullName `
        --public-key $resolvedKey.FullName `
        --signature-tool $resolvedTool.FullName `
        --project-file $resolvedProject.FullName `
        --output-directory $resolvedOutput.FullName `
        --source-commit $SourceCommit
    if ($LASTEXITCODE -ne 0) {
        throw "Inno signature evidence creation failed."
    }
} finally {
    Pop-Location
}

Write-Output "Verified exact Inno installer signature with authenticated ISSigTool."
Write-Output "Signature evidence directory: $($resolvedOutput.FullName)"
Write-Output "Inno Setup installer execution authorized: false"
Write-Output "Downloaded installer execution authorized: false"
