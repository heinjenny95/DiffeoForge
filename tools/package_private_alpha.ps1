param(
    [ValidateSet("Create", "Verify")]
    [string]$Mode = "Create",
    [string]$BuildEvidence,
    [ValidatePattern("^[0-9a-f]{64}$")]
    [string]$ExpectedBuildEvidenceSha256,
    [string]$ProjectFile,
    [ValidatePattern("^[0-9a-f]{40}$")]
    [string]$SourceCommit,
    [string]$OutputDirectory,
    [ValidatePattern("^[0-9a-f]{64}$")]
    [string]$ExpectedManifestSha256,
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$SetupName = "DiffeoForge-0.0.0.dev0-Windows-CPU-x86_64-Setup.exe"
$ManifestName = "private-alpha-manifest.json"
$SidecarName = "private-alpha-manifest.sha256"
$ReadmeName = "PRIVATE-ALPHA-README.txt"
$LicenseName = "LICENSE.txt"
$SecurityName = "windows-security-observation.json"
$ExactNames = @(
    $SetupName,
    $LicenseName,
    $ReadmeName,
    $ManifestName,
    $SidecarName,
    $SecurityName
) | Sort-Object

function Assert-NoReparseChain {
    param([string]$Path, [string]$Label)
    $current = [IO.Path]::GetFullPath($Path)
    while ($true) {
        if (Test-Path -LiteralPath $current) {
            $item = Get-Item -LiteralPath $current -Force
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw "$Label must not use a reparse path: $current"
            }
        }
        $parent = [IO.Directory]::GetParent($current)
        if ($null -eq $parent) { break }
        $current = $parent.FullName
    }
}

function Resolve-RealFile {
    param([string]$Path, [string]$Label)
    Assert-NoReparseChain -Path $Path -Label $Label
    $resolved = (Resolve-Path -LiteralPath $Path).Path
    if (-not (Test-Path -LiteralPath $resolved -PathType Leaf)) {
        throw "$Label must be an existing real file: $resolved"
    }
    return $resolved
}

function Resolve-RealDirectory {
    param([string]$Path, [string]$Label)
    Assert-NoReparseChain -Path $Path -Label $Label
    $resolved = (Resolve-Path -LiteralPath $Path).Path
    if (-not (Test-Path -LiteralPath $resolved -PathType Container)) {
        throw "$Label must be an existing real directory: $resolved"
    }
    return $resolved
}

function Test-IsWithin {
    param([string]$Candidate, [string]$Root)
    $candidateFull = [IO.Path]::GetFullPath($Candidate).TrimEnd('\')
    $rootFull = [IO.Path]::GetFullPath($Root).TrimEnd('\')
    return $candidateFull.Equals($rootFull, [StringComparison]::OrdinalIgnoreCase) -or
        $candidateFull.StartsWith($rootFull + '\', [StringComparison]::OrdinalIgnoreCase)
}

function Get-FileRecord {
    param([string]$Path, [string]$RecordedPath = "")
    $resolved = Resolve-RealFile -Path $Path -Label "Recorded file"
    $recordPath = if ($RecordedPath) { [IO.Path]::GetFullPath($RecordedPath) } else { $resolved }
    return [ordered]@{
        path = $recordPath
        bytes = (Get-Item -LiteralPath $resolved).Length
        sha256 = (Get-FileHash -LiteralPath $resolved -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}

function Write-JsonNoBom {
    param([string]$Path, [object]$Value)
    if (Test-Path -LiteralPath $Path) {
        throw "Output already exists: $Path"
    }
    $encoding = New-Object System.Text.UTF8Encoding($false)
    [IO.File]::WriteAllText(
        $Path,
        (($Value | ConvertTo-Json -Depth 16) + "`n"),
        $encoding
    )
}

function Assert-RecordContent {
    param([string]$Path, [object]$Record, [string]$ExpectedName, [string]$Label)
    $resolved = Resolve-RealFile -Path $Path -Label $Label
    if ($null -eq $Record -or
        [IO.Path]::GetFileName([string]$Record.path) -ne $ExpectedName -or
        [long]$Record.bytes -ne (Get-Item -LiteralPath $resolved).Length -or
        [string]$Record.sha256 -cne (Get-FileHash -LiteralPath $resolved -Algorithm SHA256).Hash.ToLowerInvariant()) {
        throw "$Label content record differs."
    }
}

function Test-Handoff {
    param([string]$Directory, [string]$ExpectedSha256)
    if ($ExpectedSha256 -notmatch "^[0-9a-f]{64}$") {
        throw "Expected manifest SHA-256 must contain 64 lowercase hex characters."
    }
    $root = Resolve-RealDirectory -Path $Directory -Label "Private-alpha handoff"
    $entries = @(Get-ChildItem -LiteralPath $root -Force)
    if ($entries.Count -ne 6 -or @($entries | Where-Object { -not $_.PSIsContainer }).Count -ne 6) {
        throw "Private-alpha handoff must contain exactly six regular files."
    }
    $names = @($entries.Name | Sort-Object)
    if (Compare-Object $ExactNames $names) {
        throw "Private-alpha handoff filenames differ."
    }
    foreach ($entry in $entries) {
        if ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw "Private-alpha handoff contains a reparse path."
        }
    }
    $manifestPath = Join-Path $root $ManifestName
    $observedSha256 = (Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($observedSha256 -cne $ExpectedSha256) {
        throw "Private-alpha manifest differs from the external SHA-256."
    }
    $sidecar = [IO.File]::ReadAllText((Join-Path $root $SidecarName), [Text.Encoding]::UTF8)
    if ($sidecar -cne "$ExpectedSha256  $ManifestName`n") {
        throw "Private-alpha manifest sidecar differs."
    }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    if ($manifest.schema_version -ne "0.1" -or
        $manifest.status -ne "same_owner_local_private_alpha_handoff_not_signed_distributable_or_released" -or
        $manifest.target -ne "windows-x86_64-cpu" -or
        $manifest.setup_authenticode_status -ne "NotSigned" -or
        $manifest.setup_execution_performed -ne $false -or
        $manifest.public_upload_authorized -ne $false -or
        $manifest.public_distribution_authorized -ne $false -or
        $manifest.release_authorized -ne $false) {
        throw "Private-alpha manifest identity or authorization boundary differs."
    }
    Assert-RecordContent -Path (Join-Path $root $SetupName) `
        -Record $manifest.files.setup -ExpectedName $SetupName -Label "Setup"
    Assert-RecordContent -Path (Join-Path $root $ReadmeName) `
        -Record $manifest.files.readme -ExpectedName $ReadmeName -Label "README"
    Assert-RecordContent -Path (Join-Path $root $LicenseName) `
        -Record $manifest.files.license -ExpectedName $LicenseName -Label "License"
    Assert-RecordContent -Path (Join-Path $root $SecurityName) `
        -Record $manifest.files.security_observation -ExpectedName $SecurityName `
        -Label "Security observation"
    if ($manifest.files.setup.bytes -ne $manifest.installer_build.setup_source.bytes -or
        $manifest.files.setup.sha256 -cne $manifest.installer_build.setup_source.sha256) {
        throw "Private-alpha setup differs from retained installer build evidence."
    }
    $security = Get-Content -LiteralPath (Join-Path $root $SecurityName) -Raw | ConvertFrom-Json
    if ($security.schema_version -ne "0.1" -or
        $security.setup.sha256 -cne $manifest.files.setup.sha256 -or
        $security.setup.authenticode_status -ne "NotSigned" -or
        $security.malware_clearance_claim -ne $false -or
        -not $security.microsoft_defender.scan_status) {
        throw "Private-alpha security observation differs."
    }
    Write-Output "Verified private-alpha handoff: $root"
    Write-Output "Private-alpha manifest SHA-256: $ExpectedSha256"
}

if ($Mode -eq "Verify") {
    if (-not $OutputDirectory -or -not $ExpectedManifestSha256) {
        throw "Verify mode requires OutputDirectory and ExpectedManifestSha256."
    }
    Test-Handoff -Directory $OutputDirectory -ExpectedSha256 $ExpectedManifestSha256
    exit 0
}

foreach ($required in @(
    $BuildEvidence,
    $ExpectedBuildEvidenceSha256,
    $ProjectFile,
    $SourceCommit,
    $OutputDirectory
)) {
    if (-not $required) { throw "Create mode is missing a required argument." }
}
if ($env:GITHUB_ACTIONS -eq "true") {
    throw "Same-owner private-alpha handoff creation must not run in GitHub Actions."
}
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT -or
    -not [Environment]::Is64BitProcess) {
    throw "Private-alpha handoff creation requires 64-bit Windows PowerShell."
}

$project = Resolve-RealFile -Path $ProjectFile -Label "Project file"
if ([IO.Path]::GetFileName($project) -ne "pyproject.toml") {
    throw "Project file must be named pyproject.toml."
}
$repository = (Get-Item -LiteralPath $project).Directory.FullName
$contract = Resolve-RealFile `
    -Path (Join-Path $repository "distribution\windows\private-alpha-handoff-contract-v0.1.json") `
    -Label "Private-alpha handoff contract"
$wrapper = Resolve-RealFile -Path $PSCommandPath -Label "Private-alpha handoff wrapper"
$license = Resolve-RealFile -Path (Join-Path $repository "LICENSE") -Label "License"
$buildEvidencePath = Resolve-RealFile -Path $BuildEvidence -Label "Installer build evidence"
if ((Get-FileHash -LiteralPath $buildEvidencePath -Algorithm SHA256).Hash.ToLowerInvariant() -cne
    $ExpectedBuildEvidenceSha256) {
    throw "Installer build evidence differs from the external SHA-256."
}
$dirty = & git -C $repository status --porcelain=v1 --untracked-files=all
if ($LASTEXITCODE -ne 0 -or $dirty) {
    throw "Private-alpha packaging requires a clean Git worktree."
}
$observedCommit = (& git -C $repository rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $observedCommit -cne $SourceCommit) {
    throw "Private-alpha source commit differs."
}

Push-Location $repository
try {
    $verification = @(& $Python tools\installer_build_evidence.py verify `
        $buildEvidencePath --expect-evidence-sha256 $ExpectedBuildEvidenceSha256)
    if ($LASTEXITCODE -ne 0) {
        throw "Installer build evidence verification failed: $($verification -join ' ')"
    }
} finally {
    Pop-Location
}
$build = Get-Content -LiteralPath $buildEvidencePath -Raw | ConvertFrom-Json
if ($build.observer_source.commit_sha -cne $SourceCommit -or
    $build.distribution_authorized -ne $false -or
    $build.release_authorized -ne $false -or
    $build.setup_execution_authorized -ne $false -or
    $build.plan.release_candidate -ne $false -or
    $build.compiler_execution.setup_execution -ne $false -or
    $build.compiler_execution.setup_authenticode_status -ne "NotSigned") {
    throw "Installer build evidence does not retain the exact private non-release boundary."
}
$setupSource = Resolve-RealFile -Path $build.compiler_execution.setup.path -Label "Setup source"
if ([IO.Path]::GetFileName($setupSource) -ne $SetupName) {
    throw "Setup source filename differs."
}
$setupSourceRecord = Get-FileRecord -Path $setupSource
if ($setupSourceRecord.bytes -ne $build.compiler_execution.setup.bytes -or
    $setupSourceRecord.sha256 -cne $build.compiler_execution.setup.sha256) {
    throw "Setup source differs from installer build evidence."
}
$signature = Get-AuthenticodeSignature -LiteralPath $setupSource
if ($signature.Status.ToString() -ne "NotSigned") {
    throw "Private-alpha setup must retain Authenticode status NotSigned."
}

$output = [IO.Path]::GetFullPath($OutputDirectory)
Assert-NoReparseChain -Path $output -Label "Private-alpha output"
$profile = Resolve-RealDirectory -Path $env:USERPROFILE -Label "Current user profile"
if (-not (Test-IsWithin -Candidate $output -Root $profile) -or
    (Test-IsWithin -Candidate $output -Root $repository)) {
    throw "Private-alpha output must be under the current user profile and outside the source repository."
}
if (Test-Path -LiteralPath $output) {
    throw "Private-alpha output already exists and will not be overwritten: $output"
}
$parent = Split-Path -Parent $output
if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
    throw "Private-alpha output parent must already exist: $parent"
}
$staging = "$output.tmp-$([Guid]::NewGuid().ToString('N'))"
if (Test-Path -LiteralPath $staging) {
    throw "Private-alpha staging directory already exists."
}
New-Item -ItemType Directory -Path $staging | Out-Null
$published = $false
try {
    $setupDestination = Join-Path $staging $SetupName
    Copy-Item -LiteralPath $setupSource -Destination $setupDestination
    Copy-Item -LiteralPath $license -Destination (Join-Path $staging $LicenseName)

    $defenderCommand = Get-Command Start-MpScan -ErrorAction SilentlyContinue
    $defenderStatus = Get-MpComputerStatus -ErrorAction SilentlyContinue
    $scanStatus = "not_performed_microsoft_defender_unavailable"
    $scanError = $null
    if ($null -ne $defenderStatus -and $defenderStatus.AntivirusEnabled) {
        if ($null -eq $defenderCommand) {
            $scanStatus = "not_performed_microsoft_defender_scan_command_unavailable"
        } else {
            try {
                Start-MpScan -ScanType CustomScan -ScanPath $setupSource -ErrorAction Stop
                $detections = @(Get-MpThreatDetection -ErrorAction SilentlyContinue | Where-Object {
                    @($_.Resources) -contains $setupSource
                })
                if ($detections.Count -ne 0) {
                    throw "Microsoft Defender reported a matching threat detection."
                }
                $scanStatus = "completed_no_matching_defender_detection_observed"
            } catch {
                $scanStatus = "failed"
                $scanError = $_.Exception.Message
            }
        }
    } elseif ($null -ne $defenderStatus) {
        $scanStatus = "not_performed_microsoft_defender_disabled"
    }
    $products = @(Get-CimInstance -Namespace root/SecurityCenter2 `
        -ClassName AntiVirusProduct -ErrorAction SilentlyContinue | ForEach-Object {
        [ordered]@{
            display_name = $_.displayName
            product_state = $_.productState
            timestamp = $_.timestamp
        }
    })
    $security = [ordered]@{
        schema_version = "0.1"
        observed_at = [DateTimeOffset]::UtcNow.ToString("o")
        host = [ordered]@{
            computer_name = $env:COMPUTERNAME
            windows_version = [Environment]::OSVersion.Version.ToString()
            architecture = "X64"
        }
        setup = [ordered]@{
            path = $setupSourceRecord.path
            bytes = $setupSourceRecord.bytes
            sha256 = $setupSourceRecord.sha256
            authenticode_status = $signature.Status.ToString()
        }
        microsoft_defender = [ordered]@{
            command_available = ($null -ne $defenderCommand)
            antivirus_enabled = if ($null -ne $defenderStatus) { [bool]$defenderStatus.AntivirusEnabled } else { $false }
            real_time_protection_enabled = if ($null -ne $defenderStatus) { [bool]$defenderStatus.RealTimeProtectionEnabled } else { $false }
            signature_version = if ($null -ne $defenderStatus) { $defenderStatus.AntivirusSignatureVersion } else { $null }
            signature_last_updated = if ($null -ne $defenderStatus -and $defenderStatus.AntivirusSignatureLastUpdated) { ([DateTimeOffset]$defenderStatus.AntivirusSignatureLastUpdated).ToString("o") } else { $null }
            scan_status = $scanStatus
            scan_error = $scanError
        }
        security_center_products = $products
        malware_clearance_claim = $false
    }
    Write-JsonNoBom -Path (Join-Path $staging $SecurityName) -Value $security
    if ($scanStatus -eq "failed") {
        throw "Microsoft Defender targeted scan failed: $scanError"
    }

    $readme = @"
DiffeoForge private alpha - same-owner local test candidate

Source commit: $SourceCommit
Target: Windows CPU x86-64
Setup SHA-256: $($setupSourceRecord.sha256)
Setup Authenticode status: NotSigned

IMPORTANT
- This unsigned setup is for Jenny Hein's private testing on this same machine.
- Windows SmartScreen may warn because the setup is not code-signed.
- Do not publish, redistribute, or cite this build as a released version.
- Formal third-party license review and redistribution approval are incomplete.
- Scientific validity, numerical release validation, production suitability, and performance for 300 specimens are not established.
- Keep an independent backup of every source mesh and landmark file.
- The packaging process did not execute the setup.

Integrity check
Compare the setup SHA-256 with private-alpha-manifest.json and the value above.
The complete six-file directory can be verified with tools/package_private_alpha.ps1 in Verify mode and the externally recorded manifest SHA-256.
"@
    $encoding = New-Object System.Text.UTF8Encoding($false)
    [IO.File]::WriteAllText((Join-Path $staging $ReadmeName), $readme.Replace("`r`n", "`n"), $encoding)

    $manifest = [ordered]@{
        schema_version = "0.1"
        status = "same_owner_local_private_alpha_handoff_not_signed_distributable_or_released"
        target = "windows-x86_64-cpu"
        created_at = [DateTimeOffset]::UtcNow.ToString("o")
        source = [ordered]@{
            commit_sha = $SourceCommit
            project = Get-FileRecord -Path $project
            contract = Get-FileRecord -Path $contract
            wrapper = Get-FileRecord -Path $wrapper
        }
        installer_build = [ordered]@{
            evidence = Get-FileRecord -Path $buildEvidencePath
            expected_evidence_sha256 = $ExpectedBuildEvidenceSha256
            setup_source = $setupSourceRecord
        }
        files = [ordered]@{
            setup = Get-FileRecord -Path $setupDestination `
                -RecordedPath (Join-Path $output $SetupName)
            readme = Get-FileRecord -Path (Join-Path $staging $ReadmeName) `
                -RecordedPath (Join-Path $output $ReadmeName)
            license = Get-FileRecord -Path (Join-Path $staging $LicenseName) `
                -RecordedPath (Join-Path $output $LicenseName)
            security_observation = Get-FileRecord -Path (Join-Path $staging $SecurityName) `
                -RecordedPath (Join-Path $output $SecurityName)
        }
        setup_authenticode_status = "NotSigned"
        setup_execution_performed = $false
        public_upload_authorized = $false
        public_distribution_authorized = $false
        release_authorized = $false
        scientific_boundary = "This same-owner local private alpha is an unsigned test candidate. It does not establish malware clearance, license or redistribution approval, numerical correctness, scientific validity, usability, 300-specimen performance, production suitability, or release readiness."
        missing_release_gates = @(
            "authenticode_signature",
            "code_signing_identity",
            "cpu_numerical_release_validation_on_exact_setup",
            "external_usability_evaluation",
            "formal_license_compatibility_review",
            "malware_clearance",
            "public_redistribution_approval",
            "scientific_validation",
            "three_hundred_specimen_performance_validation"
        )
    }
    $manifestPath = Join-Path $staging $ManifestName
    Write-JsonNoBom -Path $manifestPath -Value $manifest
    $manifestSha256 = (Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash.ToLowerInvariant()
    [IO.File]::WriteAllText(
        (Join-Path $staging $SidecarName),
        "$manifestSha256  $ManifestName`n",
        $encoding
    )
    [IO.Directory]::Move($staging, $output)
    $published = $true
    Test-Handoff -Directory $output -ExpectedSha256 $manifestSha256 | Out-Null
    Write-Output "Created same-owner local private-alpha handoff: $output"
    Write-Output "Private-alpha setup SHA-256: $($setupSourceRecord.sha256)"
    Write-Output "Private-alpha manifest SHA-256: $manifestSha256"
} finally {
    if (-not $published -and (Test-Path -LiteralPath $staging)) {
        [IO.Directory]::Delete($staging, $true)
    }
}
