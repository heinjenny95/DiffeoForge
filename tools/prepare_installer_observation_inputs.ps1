param(
    [Parameter(Mandatory = $true)]
    [string]$OutputRoot,
    [Parameter(Mandatory = $true)]
    [string]$SummaryFile,
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$repository = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$output = [IO.Path]::GetFullPath($OutputRoot)
$summary = [IO.Path]::GetFullPath($SummaryFile)
if (Test-Path -LiteralPath $output) {
    throw "OutputRoot already exists and will not be overwritten: $output"
}
if (Test-Path -LiteralPath $summary) {
    throw "SummaryFile already exists and will not be overwritten: $summary"
}
$dirty = & git -C $repository status --porcelain=v1 --untracked-files=all
if ($LASTEXITCODE -ne 0 -or $dirty) {
    throw "Installer observation input preparation requires a clean Git worktree."
}
$commit = (& git -C $repository rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $commit -notmatch "^[0-9a-f]{40}$") {
    throw "Could not resolve the exact source commit."
}
New-Item -ItemType Directory -Path $output | Out-Null
$summaryParent = Split-Path -Parent $summary
if (-not (Test-Path -LiteralPath $summaryParent -PathType Container)) {
    New-Item -ItemType Directory -Path $summaryParent | Out-Null
}

$smokeRoot = Join-Path $output "DiffeoForge Input Käfer"
$synthetic = Join-Path $smokeRoot "synthetic"
New-Item -ItemType Directory -Path $smokeRoot | Out-Null
Copy-Item -LiteralPath (Join-Path $repository "examples\synthetic") `
    -Destination $synthetic -Recurse
$referenceConfig = Join-Path $smokeRoot "reference-atlas.yaml"
$modernConfig = Join-Path $smokeRoot "modern-atlas.yaml"
Copy-Item -LiteralPath (Join-Path $repository "examples\minimal-atlas-container.yaml") `
    -Destination $referenceConfig
Copy-Item -LiteralPath (Join-Path $repository "examples\minimal-modern-atlas.yaml") `
    -Destination $modernConfig

Push-Location $repository
try {
    $approval = Join-Path $smokeRoot "preparation-approval.json"
    $fingerprint = (& $Python -c `
        "import sys; from diffeoforge.reference_preparation_plan import plan_reference_preparation, reference_preparation_plan_fingerprint; print(reference_preparation_plan_fingerprint(plan_reference_preparation(sys.argv[1], run_id='installer-observation-preparation')))" `
        $referenceConfig).Trim()
    if ($LASTEXITCODE -ne 0 -or $fingerprint -notmatch "^[0-9a-f]{64}$") {
        throw "Could not create the synthetic reviewed plan fingerprint."
    }
    & $Python -m diffeoforge reference-plan-approve $referenceConfig `
        --run-id installer-observation-preparation `
        --approve-fingerprint $fingerprint --output $approval | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Could not create the synthetic preparation-only approval."
    }
    $approvalSha256 = (Get-FileHash -LiteralPath $approval -Algorithm SHA256).Hash.ToLowerInvariant()
    $dist = Join-Path $output "freeze-dist"
    $work = Join-Path $output "freeze-work"
    $modernDestination = Join-Path $smokeRoot "Käfer Modern Result"
    & distribution\windows\build-evidence.ps1 `
        -Python $Python -DistPath $dist -WorkPath $work `
        -SmokeConfig $modernConfig -SmokeDestination $modernDestination `
        -PreparationApproval $approval -PreparationConfig $referenceConfig `
        -PreparationApprovalSha256 $approvalSha256
    if ($LASTEXITCODE -ne 0) {
        throw "Frozen bundle evidence build failed."
    }
    $bundle = (Resolve-Path (Join-Path $dist "DiffeoForge")).Path
    & $Python tools\desktop_bundle_evidence.py verify $bundle
    if ($LASTEXITCODE -ne 0) {
        throw "Independent frozen bundle verification failed."
    }

    $evidenceDirectory = Join-Path $output "six-evidence"
    New-Item -ItemType Directory -Path $evidenceDirectory | Out-Null
    Copy-Item -LiteralPath (Join-Path $bundle "freeze-evidence.json") `
        -Destination $evidenceDirectory
    Copy-Item -LiteralPath (Join-Path $bundle "freeze-evidence.sha256") `
        -Destination $evidenceDirectory
    $freezeEvidence = Join-Path $evidenceDirectory "freeze-evidence.json"
    $freezeSha256 = (Get-FileHash -LiteralPath $freezeEvidence -Algorithm SHA256).Hash.ToLowerInvariant()
    & $Python tools\desktop_dependency_metadata_evidence.py create $bundle `
        --expect-freeze-evidence-sha256 $freezeSha256 `
        --output-directory $evidenceDirectory
    if ($LASTEXITCODE -ne 0) {
        throw "Dependency metadata evidence creation failed."
    }
    $dependencyEvidence = Join-Path $evidenceDirectory "freeze-dependency-metadata.json"
    $dependencySha256 = (Get-FileHash -LiteralPath $dependencyEvidence -Algorithm SHA256).Hash.ToLowerInvariant()
    & $Python tools\desktop_dependency_metadata_evidence.py verify $dependencyEvidence `
        --expect-freeze-evidence-sha256 $freezeSha256
    if ($LASTEXITCODE -ne 0) {
        throw "Dependency metadata evidence verification failed."
    }
    & $Python tools\desktop_sbom.py create $bundle $dependencyEvidence `
        --expect-freeze-evidence-sha256 $freezeSha256 `
        --expect-dependency-evidence-sha256 $dependencySha256 `
        --output-directory $evidenceDirectory
    if ($LASTEXITCODE -ne 0) {
        throw "CycloneDX SBOM creation failed."
    }
    $sbom = Join-Path $evidenceDirectory "freeze-sbom.cdx.json"
    $sbomSha256 = (Get-FileHash -LiteralPath $sbom -Algorithm SHA256).Hash.ToLowerInvariant()
    & $Python tools\desktop_sbom.py verify $sbom $freezeEvidence $dependencyEvidence `
        --expect-freeze-evidence-sha256 $freezeSha256 `
        --expect-dependency-evidence-sha256 $dependencySha256 `
        --expect-sbom-sha256 $sbomSha256
    if ($LASTEXITCODE -ne 0) {
        throw "CycloneDX SBOM verification failed."
    }
    $names = @(Get-ChildItem -LiteralPath $evidenceDirectory -File).Name | Sort-Object
    $expectedNames = @(
        "freeze-dependency-metadata.json",
        "freeze-dependency-metadata.sha256",
        "freeze-evidence.json",
        "freeze-evidence.sha256",
        "freeze-sbom.cdx.json",
        "freeze-sbom.cdx.sha256"
    )
    if ((Get-ChildItem -LiteralPath $evidenceDirectory -Force).Count -ne 6 -or
        (Compare-Object $expectedNames $names)) {
        throw "Prepared evidence directory must contain exactly six files."
    }
    $manifest = Get-Content -LiteralPath $freezeEvidence -Raw | ConvertFrom-Json
    $result = [ordered]@{
        schema_version = "0.1"
        source_commit = $commit
        project_file = (Resolve-Path "pyproject.toml").Path
        bundle_directory = $bundle
        bundle_file_count = $manifest.bundle.file_count
        bundle_total_bytes = $manifest.bundle.total_bytes
        bundle_inventory_sha256 = $manifest.bundle.inventory_sha256
        evidence_directory = (Resolve-Path $evidenceDirectory).Path
        freeze_evidence_sha256 = $freezeSha256
        dependency_evidence_sha256 = $dependencySha256
        sbom_sha256 = $sbomSha256
    }
    $encoding = New-Object System.Text.UTF8Encoding($false)
    [IO.File]::WriteAllText(
        $summary,
        (($result | ConvertTo-Json -Depth 6) + "`n"),
        $encoding
    )
    Write-Output "Prepared exact installer observation inputs: $summary"
} finally {
    Pop-Location
}
