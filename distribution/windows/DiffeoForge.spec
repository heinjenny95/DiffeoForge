"""Evidence-only PyInstaller one-directory build for Windows x86-64 CPU."""

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

repository = Path(SPEC).resolve().parents[2]
source = repository / "src"
entrypoints = repository / "distribution" / "windows"
schema_directory = source / "diffeoforge" / "schema"
schema_data = [
    (str(path), "diffeoforge/schema")
    for path in sorted(schema_directory.glob("*.json"))
]

# The post-build SBOM and installer-plan tools run from source after the frozen
# bundle has been verified. Their implementations and third-party builder
# dependencies must not become part of any runtime executable merely because
# the clean-runner job installs the ``sbom-builder`` extra before PyInstaller.
builder_only_module_prefixes = (
    "boolean",
    "cyclonedx",
    "defusedxml",
    "diffeoforge.desktop.inno_portable_toolchain_evidence",
    "diffeoforge.desktop.inno_signature_evidence",
    "diffeoforge.desktop.inno_toolchain_evidence",
    "diffeoforge.desktop.installer_build_evidence",
    "diffeoforge.desktop.installer_installation_evidence",
    "diffeoforge.desktop.installer_plan",
    "diffeoforge.desktop.sbom",
    "license_expression",
    "packageurl",
    "py_serializable",
    "sortedcontainers",
)


def is_builder_only_module(module_name):
    return any(
        module_name == prefix or module_name.startswith(f"{prefix}.")
        for prefix in builder_only_module_prefixes
    )


def assert_builder_only_modules_absent(analysis, executable_name):
    embedded = sorted(
        module_name
        for module_name, *_ in analysis.pure
        if is_builder_only_module(module_name)
    )
    if embedded:
        raise RuntimeError(
            f"{executable_name} contains builder-only modules: "
            + ", ".join(embedded)
        )


hidden_imports = [
    module_name
    for module_name in collect_submodules("diffeoforge")
    if not is_builder_only_module(module_name)
]
excluded_modules = [
    "IPython",
    "matplotlib",
    "pip",
    "pytest",
    "tkinter",
    *builder_only_module_prefixes,
]

desktop_analysis = Analysis(
    [str(entrypoints / "diffeoforge_desktop.py")],
    pathex=[str(source)],
    binaries=[],
    datas=schema_data,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excluded_modules,
    noarchive=False,
    optimize=0,
)
assert_builder_only_modules_absent(desktop_analysis, "DiffeoForge")
desktop_pyz = PYZ(desktop_analysis.pure)
desktop_executable = EXE(
    desktop_pyz,
    desktop_analysis.scripts,
    [],
    exclude_binaries=True,
    name="DiffeoForge",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)

worker_analysis = Analysis(
    [str(entrypoints / "diffeoforge_worker.py")],
    pathex=[str(source)],
    binaries=[],
    datas=schema_data,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excluded_modules,
    noarchive=False,
    optimize=0,
)
assert_builder_only_modules_absent(worker_analysis, "DiffeoForgeWorker")
worker_pyz = PYZ(worker_analysis.pure)
worker_executable = EXE(
    worker_pyz,
    worker_analysis.scripts,
    [],
    exclude_binaries=True,
    name="DiffeoForgeWorker",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
)

reference_worker_analysis = Analysis(
    [str(entrypoints / "diffeoforge_reference_worker.py")],
    pathex=[str(source)],
    binaries=[],
    datas=schema_data,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excluded_modules,
    noarchive=False,
    optimize=0,
)
assert_builder_only_modules_absent(
    reference_worker_analysis, "DiffeoForgeReferenceWorker"
)
reference_worker_pyz = PYZ(reference_worker_analysis.pure)
reference_worker_executable = EXE(
    reference_worker_pyz,
    reference_worker_analysis.scripts,
    [],
    exclude_binaries=True,
    name="DiffeoForgeReferenceWorker",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
)

reference_preparation_worker_analysis = Analysis(
    [str(entrypoints / "diffeoforge_reference_preparation_worker.py")],
    pathex=[str(source)],
    binaries=[],
    datas=schema_data,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excluded_modules,
    noarchive=False,
    optimize=0,
)
assert_builder_only_modules_absent(
    reference_preparation_worker_analysis,
    "DiffeoForgeReferencePreparationWorker",
)
reference_preparation_worker_pyz = PYZ(reference_preparation_worker_analysis.pure)
reference_preparation_worker_executable = EXE(
    reference_preparation_worker_pyz,
    reference_preparation_worker_analysis.scripts,
    [],
    exclude_binaries=True,
    name="DiffeoForgeReferencePreparationWorker",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
)

reference_execution_worker_analysis = Analysis(
    [str(entrypoints / "diffeoforge_reference_execution_worker.py")],
    pathex=[str(source)],
    binaries=[],
    datas=schema_data,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excluded_modules,
    noarchive=False,
    optimize=0,
)
assert_builder_only_modules_absent(
    reference_execution_worker_analysis,
    "DiffeoForgeReferenceExecutionWorker",
)
reference_execution_worker_pyz = PYZ(reference_execution_worker_analysis.pure)
reference_execution_worker_executable = EXE(
    reference_execution_worker_pyz,
    reference_execution_worker_analysis.scripts,
    [],
    exclude_binaries=True,
    name="DiffeoForgeReferenceExecutionWorker",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
)

bundle = COLLECT(
    desktop_executable,
    worker_executable,
    reference_worker_executable,
    reference_preparation_worker_executable,
    reference_execution_worker_executable,
    desktop_analysis.binaries,
    desktop_analysis.datas,
    worker_analysis.binaries,
    worker_analysis.datas,
    reference_worker_analysis.binaries,
    reference_worker_analysis.datas,
    reference_preparation_worker_analysis.binaries,
    reference_preparation_worker_analysis.datas,
    reference_execution_worker_analysis.binaries,
    reference_execution_worker_analysis.datas,
    strip=False,
    upx=False,
    name="DiffeoForge",
)
