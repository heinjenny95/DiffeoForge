param(
    [Parameter(Mandatory = $true)]
    [string]$BuildEvidence,
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-f]{64}$")]
    [string]$ExpectedBuildEvidenceSha256,
    [Parameter(Mandatory = $true)]
    [string]$ProjectFile,
    [Parameter(Mandatory = $true)]
    [string]$InstallRoot,
    [Parameter(Mandatory = $true)]
    [string]$ProjectSentinel,
    [Parameter(Mandatory = $true)]
    [string]$EvidenceOutputDirectory,
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-f]{40}$")]
    [string]$SourceCommit,
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"

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
        throw "$Label must be an existing file: $resolved"
    }
    return $resolved
}

function Resolve-RealDirectory {
    param([string]$Path, [string]$Label)
    Assert-NoReparseChain -Path $Path -Label $Label
    $resolved = (Resolve-Path -LiteralPath $Path).Path
    if (-not (Test-Path -LiteralPath $resolved -PathType Container)) {
        throw "$Label must be an existing directory: $resolved"
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
    param([string]$Path)
    $resolved = Resolve-RealFile -Path $Path -Label "Recorded file"
    return [ordered]@{
        path = $resolved
        bytes = (Get-Item -LiteralPath $resolved).Length
        sha256 = (Get-FileHash -LiteralPath $resolved -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}

function Get-SentinelRecord {
    param([string]$Path)
    $record = Get-FileRecord -Path $Path
    return [ordered]@{
        path = $record.path
        bytes = $record.bytes
        sha256 = $record.sha256
    }
}

function Write-JsonNoBom {
    param([string]$Path, [object]$Value)
    if (Test-Path -LiteralPath $Path) {
        throw "Observation output already exists: $Path"
    }
    $json = $Value | ConvertTo-Json -Depth 12
    $encoding = New-Object System.Text.UTF8Encoding($false)
    [IO.File]::WriteAllText($Path, $json + "`n", $encoding)
}

if ($env:GITHUB_ACTIONS -ne "true" -or $env:RUNNER_OS -ne "Windows" -or
    $env:RUNNER_ARCH -ne "X64" -or -not $env:RUNNER_TEMP -or -not $env:RUNNER_NAME) {
    throw "Installer lifecycle observation is restricted to an ephemeral X64 GitHub Actions Windows runner."
}
if (-not [Environment]::Is64BitProcess) {
    throw "Installer lifecycle observation requires a 64-bit PowerShell process."
}

$project = Resolve-RealFile -Path $ProjectFile -Label "Project file"
$repository = (Get-Item -LiteralPath $project).Directory.FullName
$buildEvidencePath = Resolve-RealFile -Path $BuildEvidence -Label "Installer build evidence"
$sentinelPath = Resolve-RealFile -Path $ProjectSentinel -Label "Project sentinel"
$runnerTemp = Resolve-RealDirectory -Path $env:RUNNER_TEMP -Label "Runner temp"
$installFull = [IO.Path]::GetFullPath($InstallRoot)
$evidenceFull = [IO.Path]::GetFullPath($EvidenceOutputDirectory)
Assert-NoReparseChain -Path $installFull -Label "Install root"
Assert-NoReparseChain -Path $evidenceFull -Label "Evidence output directory"
if (-not (Test-IsWithin -Candidate $installFull -Root $runnerTemp) -or
    -not (Test-IsWithin -Candidate $evidenceFull -Root $runnerTemp) -or
    -not (Test-IsWithin -Candidate $sentinelPath -Root $runnerTemp)) {
    throw "Install root, evidence output, and project sentinel must stay under RUNNER_TEMP."
}
if ((Test-IsWithin -Candidate $sentinelPath -Root $installFull) -or
    (Test-IsWithin -Candidate $sentinelPath -Root $evidenceFull) -or
    (Test-IsWithin -Candidate $installFull -Root $evidenceFull) -or
    (Test-IsWithin -Candidate $evidenceFull -Root $installFull) -or
    (Test-IsWithin -Candidate $installFull -Root $repository) -or
    (Test-IsWithin -Candidate $evidenceFull -Root $repository)) {
    throw "Install, evidence, source, and project-sentinel boundaries must be disjoint."
}
if (Test-Path -LiteralPath $installFull) {
    throw "Install root already exists and will not be overwritten: $installFull"
}
if (Test-Path -LiteralPath $evidenceFull) {
    throw "Evidence output already exists and will not be overwritten: $evidenceFull"
}
$installParent = Split-Path -Parent $installFull
if (-not (Test-Path -LiteralPath $installParent -PathType Container)) {
    New-Item -ItemType Directory -Path $installParent | Out-Null
}
New-Item -ItemType Directory -Path $evidenceFull | Out-Null

$dirty = & git -C $repository status --porcelain=v1 --untracked-files=all
if ($LASTEXITCODE -ne 0 -or $dirty) {
    throw "Installer lifecycle observation requires a clean Git worktree."
}
$observedCommit = (& git -C $repository rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $observedCommit -ne $SourceCommit) {
    throw "Installer lifecycle observation source commit differs."
}

$preflightArguments = @(
    "tools\installer_installation_evidence.py", "preflight", $buildEvidencePath,
    "--expect-build-evidence-sha256", $ExpectedBuildEvidenceSha256,
    "--project-file", $project,
    "--source-commit", $SourceCommit
)
$preflightOutput = @(& $Python @preflightArguments)
if ($LASTEXITCODE -ne 0) {
    throw "Installer lifecycle preflight failed: $($preflightOutput -join ' ')"
}
try {
    $preflight = ($preflightOutput -join "`n") | ConvertFrom-Json
} catch {
    throw "Installer lifecycle preflight did not return one JSON object."
}
$setup = Resolve-RealFile -Path $preflight.setup.path -Label "Setup executable"
if ($preflight.build_evidence.sha256 -ne $ExpectedBuildEvidenceSha256) {
    throw "Installer lifecycle preflight external hash binding differs."
}

$runner = [ordered]@{
    github_actions = $true
    ephemeral = $true
    os = "Windows"
    architecture = "X64"
    runner_name = $env:RUNNER_NAME
}
$sentinelBefore = Get-SentinelRecord -Path $sentinelPath
$installLog = Join-Path $evidenceFull "install.log"
$uninstallLog = Join-Path $evidenceFull "uninstall.log"
$shortcut = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\DiffeoForge\DiffeoForge.lnk"
$registryPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\DiffeoForge.WindowsCPU.x86_64_is1"
$completed = $false

try {
    $installArguments = @(
        "/SP-", "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CURRENTUSER",
        "/DIR=`"$installFull`"", "/GROUP=DiffeoForge", "/LOG=`"$installLog`""
    )
    $installProcess = Start-Process -FilePath $setup -ArgumentList $installArguments `
        -Wait -PassThru -WindowStyle Hidden
    if ($installProcess.ExitCode -ne 0) {
        throw "Setup failed with exit code $($installProcess.ExitCode)."
    }
    $installedRoot = Resolve-RealDirectory -Path $installFull -Label "Installed root"
    $installLogRecord = Get-FileRecord -Path $installLog
    if (-not (Test-Path -LiteralPath $shortcut -PathType Leaf)) {
        throw "Expected Start Menu shortcut was not created: $shortcut"
    }
    $shell = New-Object -ComObject WScript.Shell
    $shortcutObject = $shell.CreateShortcut($shortcut)
    $installedDesktop = Resolve-RealFile -Path (Join-Path $installedRoot "DiffeoForge.exe") `
        -Label "Installed desktop executable"
    if (-not $shortcutObject.TargetPath.Equals($installedDesktop, [StringComparison]::OrdinalIgnoreCase) -or
        -not $shortcutObject.WorkingDirectory.Equals($installedRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Start Menu shortcut target or working directory differs."
    }
    if (-not (Test-Path -LiteralPath $registryPath)) {
        throw "Expected current-user uninstall registration was not created."
    }
    $registration = Get-ItemProperty -LiteralPath $registryPath
    if ($registration.DisplayName -ne "DiffeoForge 0.0.0.dev0 (Windows CPU x86-64)" -or
        -not $registration.UninstallString) {
        throw "Current-user uninstall registration differs."
    }
    $uninstallers = @(Get-ChildItem -LiteralPath $installedRoot -Filter "unins*.exe" -File)
    if ($uninstallers.Count -ne 1 -or
        $registration.UninstallString.IndexOf($uninstallers[0].FullName, [StringComparison]::OrdinalIgnoreCase) -lt 0) {
        throw "Uninstall registration does not bind the exact installed uninstaller."
    }
    $sentinelAfterInstall = Get-SentinelRecord -Path $sentinelPath
    $installObservation = [ordered]@{
        schema_version = "0.1"
        phase = "install"
        observed_at = [DateTimeOffset]::UtcNow.ToString("o")
        runner = $runner
        setup = Get-FileRecord -Path $setup
        arguments = $installArguments
        exit_code = $installProcess.ExitCode
        install_root = $installedRoot
        log = $installLogRecord
        shortcut_path = (Resolve-Path -LiteralPath $shortcut).Path
        shortcut_verified = $true
        registration_path = $registryPath
        registration_verified = $true
        sentinel_before = $sentinelBefore
        sentinel_after = $sentinelAfterInstall
    }
    Write-JsonNoBom -Path (Join-Path $evidenceFull "installer-install-observation.json") `
        -Value $installObservation

    $snapshotArguments = @(
        "tools\installer_installation_evidence.py", "snapshot", $installedRoot,
        $buildEvidencePath,
        "--expect-build-evidence-sha256", $ExpectedBuildEvidenceSha256,
        "--output", (Join-Path $evidenceFull "installed-file-inventory.json")
    )
    & $Python @snapshotArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Installed-file snapshot verification failed."
    }

    $desktopProcess = Start-Process -FilePath $installedDesktop -ArgumentList @("--smoke") `
        -PassThru -WindowStyle Hidden
    $networkObservations = @()
    do {
        $desktopProcess.Refresh()
        $tcp = @(Get-NetTCPConnection -OwningProcess $desktopProcess.Id -ErrorAction SilentlyContinue)
        foreach ($item in $tcp) {
            $networkObservations += "tcp:$($item.LocalAddress):$($item.LocalPort)->$($item.RemoteAddress):$($item.RemotePort):$($item.State)"
        }
        $udp = @(Get-NetUDPEndpoint -OwningProcess $desktopProcess.Id -ErrorAction SilentlyContinue)
        foreach ($item in $udp) {
            $networkObservations += "udp:$($item.LocalAddress):$($item.LocalPort)"
        }
        if (-not $desktopProcess.HasExited) { Start-Sleep -Milliseconds 50 }
    } while (-not $desktopProcess.HasExited)
    $desktopProcess.WaitForExit()
    if ($desktopProcess.ExitCode -ne 0) {
        throw "Installed desktop smoke failed with exit code $($desktopProcess.ExitCode)."
    }
    $networkObservations = @($networkObservations | Sort-Object -Unique)
    if ($networkObservations.Count -ne 0) {
        throw "Installed desktop process opened a sampled network endpoint."
    }
    $sentinelAfterSmoke = Get-SentinelRecord -Path $sentinelPath
    $smokeObservation = [ordered]@{
        schema_version = "0.1"
        phase = "smoke"
        observed_at = [DateTimeOffset]::UtcNow.ToString("o")
        runner = $runner
        program = Get-FileRecord -Path $installedDesktop
        arguments = @("--smoke")
        exit_code = $desktopProcess.ExitCode
        network_scope = "desktop_process_only_not_host_wide_isolation"
        network_connection_count = 0
        network_observations = $networkObservations
        sentinel_after = $sentinelAfterSmoke
    }
    Write-JsonNoBom -Path (Join-Path $evidenceFull "installed-smoke-observation.json") `
        -Value $smokeObservation

    $uninstaller = $uninstallers[0].FullName
    $uninstallArguments = @(
        "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/LOG=`"$uninstallLog`""
    )
    $uninstallProgramRecord = Get-FileRecord -Path $uninstaller
    $uninstallProcess = Start-Process -FilePath $uninstaller -ArgumentList $uninstallArguments `
        -Wait -PassThru -WindowStyle Hidden
    if ($uninstallProcess.ExitCode -ne 0) {
        throw "Uninstaller failed with exit code $($uninstallProcess.ExitCode)."
    }
    for ($attempt = 0; $attempt -lt 100 -and (Test-Path -LiteralPath $installFull); $attempt++) {
        Start-Sleep -Milliseconds 100
    }
    $rootAbsent = -not (Test-Path -LiteralPath $installFull)
    $shortcutAbsent = -not (Test-Path -LiteralPath $shortcut)
    $registrationAbsent = -not (Test-Path -LiteralPath $registryPath)
    if (-not $rootAbsent -or -not $shortcutAbsent -or -not $registrationAbsent) {
        throw "Uninstall did not remove the exact application, shortcut, and registry boundaries."
    }
    $sentinelAfterUninstall = Get-SentinelRecord -Path $sentinelPath
    $uninstallObservation = [ordered]@{
        schema_version = "0.1"
        phase = "uninstall"
        observed_at = [DateTimeOffset]::UtcNow.ToString("o")
        runner = $runner
        program = $uninstallProgramRecord
        arguments = $uninstallArguments
        exit_code = $uninstallProcess.ExitCode
        log = Get-FileRecord -Path $uninstallLog
        install_root = $installFull
        install_root_absent = $rootAbsent
        shortcut_path = $shortcut
        shortcut_absent = $shortcutAbsent
        registration_path = $registryPath
        registration_absent = $registrationAbsent
        sentinel_after = $sentinelAfterUninstall
    }
    Write-JsonNoBom -Path (Join-Path $evidenceFull "installer-uninstall-observation.json") `
        -Value $uninstallObservation

    $createArguments = @(
        "tools\installer_installation_evidence.py", "create", $evidenceFull,
        $buildEvidencePath,
        "--expect-build-evidence-sha256", $ExpectedBuildEvidenceSha256,
        "--project-file", $project,
        "--source-commit", $SourceCommit
    )
    & $Python @createArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Canonical installer lifecycle evidence creation failed."
    }
    $evidencePath = Join-Path $evidenceFull "installer-installation-evidence.json"
    $evidenceSha256 = (Get-FileHash -LiteralPath $evidencePath -Algorithm SHA256).Hash.ToLowerInvariant()
    & $Python tools\installer_installation_evidence.py verify $evidencePath `
        --expect-evidence-sha256 $evidenceSha256
    if ($LASTEXITCODE -ne 0) {
        throw "Independent installer lifecycle evidence verification failed."
    }
    & $Python tools\installer_installation_evidence.py verify-retained $evidencePath `
        --expect-evidence-sha256 $evidenceSha256
    if ($LASTEXITCODE -ne 0) {
        throw "Retained eight-file artifact integrity verification failed."
    }
    $completed = $true
    Write-Output "Verified isolated installer lifecycle evidence: $evidencePath"
    Write-Output "Installer lifecycle evidence SHA-256: $evidenceSha256"
} finally {
    if (-not $completed -and (Test-Path -LiteralPath $installFull)) {
        $cleanup = @(Get-ChildItem -LiteralPath $installFull -Filter "unins*.exe" -File `
            -ErrorAction SilentlyContinue | Select-Object -First 1)
        if ($cleanup.Count -eq 1) {
            try {
                Start-Process -FilePath $cleanup[0].FullName `
                    -ArgumentList @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART") `
                    -Wait -WindowStyle Hidden
            } catch {
                Write-Warning "Best-effort failed-observation cleanup could not run."
            }
        }
    }
}
