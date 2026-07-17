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
hidden_imports = collect_submodules("diffeoforge")
excluded_modules = ["IPython", "matplotlib", "pip", "pytest", "tkinter"]

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

bundle = COLLECT(
    desktop_executable,
    worker_executable,
    desktop_analysis.binaries,
    desktop_analysis.datas,
    worker_analysis.binaries,
    worker_analysis.datas,
    strip=False,
    upx=False,
    name="DiffeoForge",
)
