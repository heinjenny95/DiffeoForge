"""PyInstaller entry point for supervised Deformetrica execution."""
from macos_bootstrap import configure_runtime_path

from diffeoforge.desktop.reference_execution_worker import _process_main

configure_runtime_path()
_process_main()
