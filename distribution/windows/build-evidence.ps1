param(
    [string]$Python = "python",
    [string]$DistPath = "dist\windows-freeze",
    [string]$WorkPath = "dist\windows-freeze-work",
    [string]$SmokeConfig = "",
    [string]$SmokeDestination = "",
    [Parameter(Mandatory = $true)]
    [string]$PreparationApproval,
    [Parameter(Mandatory = $true)]
    [string]$PreparationConfig,
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-fA-F]{64}$")]
    [string]$PreparationApprovalSha256
)

$ErrorActionPreference = "Stop"
$repository = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Push-Location $repository
try {
    $windows = [System.Runtime.InteropServices.RuntimeInformation]::IsOSPlatform(
        [System.Runtime.InteropServices.OSPlatform]::Windows
    )
    if (-not $windows -or -not [Environment]::Is64BitProcess) {
        throw "The evidence freeze requires a 64-bit Windows Python process."
    }
    $dirty = & git status --porcelain=v1 --untracked-files=all
    if ($LASTEXITCODE -ne 0) {
        throw "Could not inspect the Git worktree."
    }
    if ($dirty) {
        throw "The evidence freeze requires a clean Git worktree."
    }
    if ([bool]$SmokeConfig -ne [bool]$SmokeDestination) {
        throw "SmokeConfig and SmokeDestination must be supplied together."
    }
    $resolvedPreparationApproval = (Resolve-Path -LiteralPath $PreparationApproval).Path
    $resolvedPreparationConfig = (Resolve-Path -LiteralPath $PreparationConfig).Path
    $expectedPreparationApprovalSha256 = $PreparationApprovalSha256.ToLowerInvariant()
    & $Python -c "import platform, PyInstaller, torch; assert platform.python_version_tuple()[:2] == ('3', '12'); assert PyInstaller.__version__ == '6.21.0'; assert torch.version.cuda is None"
    if ($LASTEXITCODE -ne 0) {
        throw "Python 3.12, PyInstaller 6.21.0, or the CPU-only Torch boundary differs."
    }
    $observedPreparationApprovalSha256 = (& $Python -c `
        "import hashlib, pathlib, sys; print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest())" `
        $resolvedPreparationApproval).Trim()
    if ($LASTEXITCODE -ne 0 -or $observedPreparationApprovalSha256 -ne $expectedPreparationApprovalSha256) {
        throw "Preparation approval does not match PreparationApprovalSha256."
    }
    & $Python -m diffeoforge reference-plan-approval-verify `
        $resolvedPreparationApproval --current-config $resolvedPreparationConfig
    if ($LASTEXITCODE -ne 0) {
        throw "Preparation approval/config preverification failed."
    }
    if (Test-Path -LiteralPath $DistPath) {
        throw "DistPath already exists and will not be overwritten: $DistPath"
    }
    if (Test-Path -LiteralPath $WorkPath) {
        throw "WorkPath already exists and will not be overwritten: $WorkPath"
    }
    & $Python -m PyInstaller --clean --noconfirm `
        --distpath $DistPath --workpath $WorkPath `
        distribution\windows\DiffeoForge.spec
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller freeze failed."
    }
    $bundle = (Resolve-Path (Join-Path $DistPath "DiffeoForge")).Path
    $desktop = Join-Path $bundle "DiffeoForge.exe"
    $process = Start-Process -FilePath $desktop -ArgumentList "--smoke" `
        -Wait -PassThru -WindowStyle Hidden
    if ($process.ExitCode -ne 0) {
        throw "Frozen desktop smoke failed with exit code $($process.ExitCode)."
    }
    if ($SmokeConfig) {
        & $Python tools\smoke_frozen_desktop_worker.py `
            (Join-Path $bundle "DiffeoForgeWorker.exe") `
            $SmokeConfig $SmokeDestination
        if ($LASTEXITCODE -ne 0) {
            throw "Frozen worker/controller smoke failed."
        }
    }
    & $Python tools\smoke_frozen_reference_worker.py `
        (Join-Path $bundle "DiffeoForgeReferenceWorker.exe") `
        examples\minimal-atlas-container.yaml
    if ($LASTEXITCODE -ne 0) {
        throw "Frozen nonnumerical reference worker/controller smoke failed."
    }
    & $Python tools\audit_frozen_reference_parent_death.py `
        (Join-Path $bundle "DiffeoForgeReferenceWorker.exe") `
        examples\minimal-atlas-container.yaml
    if ($LASTEXITCODE -ne 0) {
        throw "Frozen reference worker hard-parent-death audit failed."
    }
    & $Python tools\audit_frozen_reference_parent_death.py `
        (Join-Path $bundle "DiffeoForgeReferenceExecutionWorker.exe") `
        examples\minimal-atlas-container.yaml --execution
    if ($LASTEXITCODE -ne 0) {
        throw "Frozen reference execution worker hard-parent-death audit failed."
    }
    & $Python tools\smoke_frozen_reference_execution_worker.py `
        (Join-Path $bundle "DiffeoForgeReferenceExecutionWorker.exe") `
        examples\minimal-atlas-container.yaml
    if ($LASTEXITCODE -ne 0) {
        throw "Frozen reference execution worker cancel-before-prepare smoke failed."
    }
    & $Python tools\audit_frozen_reference_preparation_parent_death.py `
        (Join-Path $bundle "DiffeoForgeReferencePreparationWorker.exe") `
        $resolvedPreparationApproval $resolvedPreparationConfig `
        --expect-request-sha256 $expectedPreparationApprovalSha256
    if ($LASTEXITCODE -ne 0) {
        throw "Frozen preparation worker hard-parent-death audit failed."
    }
    & $Python tools\smoke_frozen_reference_preparation_worker.py `
        (Join-Path $bundle "DiffeoForgeReferencePreparationWorker.exe") `
        $resolvedPreparationApproval $resolvedPreparationConfig `
        --expect-request-sha256 $expectedPreparationApprovalSha256
    if ($LASTEXITCODE -ne 0) {
        throw "Frozen approval-bound reference preparation worker/controller smoke failed."
    }
    $commit = (& git rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0) {
        throw "Could not resolve the source commit."
    }
    & $Python tools\desktop_bundle_evidence.py create $bundle `
        --source-commit $commit
    if ($LASTEXITCODE -ne 0) {
        throw "Desktop evidence creation failed."
    }
    & $Python tools\desktop_bundle_evidence.py verify $bundle
    if ($LASTEXITCODE -ne 0) {
        throw "Desktop evidence verification failed."
    }
    Write-Output "Evidence-only Windows bundle verified: $bundle"
} finally {
    Pop-Location
}
