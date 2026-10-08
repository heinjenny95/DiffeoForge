from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from diffeoforge.desktop.pipe_input import UnbufferedUtf8LineInput
from diffeoforge.subprocess_policy import hidden_windows_process_kwargs


def test_pipe_preserves_queued_commands_and_final_line() -> None:
    read_fd, write_fd = os.pipe()
    try:
        stream = UnbufferedUtf8LineInput(read_fd)
        assert stream.pop_buffered_line() is None
        os.write(write_fd, "Käfer\ncancel\nfinal".encode())
        assert stream.readline() == "Käfer\n"
        assert stream.pop_buffered_line() == "cancel\n"
        os.close(write_fd)
        write_fd = -1
        assert stream.readline() == "final"
        assert list(stream) == []
    finally:
        os.close(read_fd)
        if write_fd >= 0:
            os.close(write_fd)


def test_pipe_waits_for_a_split_utf8_character() -> None:
    read_fd, write_fd = os.pipe()
    stream = UnbufferedUtf8LineInput(read_fd)
    lines = []
    reader = threading.Thread(target=lambda: lines.append(stream.readline()), daemon=True)
    try:
        reader.start()
        os.write(write_fd, b"K\xc3")
        assert lines == []
        os.write(write_fd, b"\xa4fer\n")
        reader.join(timeout=5)
        assert not reader.is_alive()
        assert lines == ["Käfer\n"]
    finally:
        os.close(write_fd)
        reader.join(timeout=5)
        os.close(read_fd)


def test_pipe_rejects_invalid_utf8() -> None:
    read_fd, write_fd = os.pipe()
    try:
        stream = UnbufferedUtf8LineInput(read_fd)
        os.write(write_fd, b"\xff\n")
        with pytest.raises(UnicodeError):
            stream.readline()
    finally:
        os.close(write_fd)
        os.close(read_fd)


def test_native_import_finishes_while_command_pipe_remains_open(tmp_path: Path) -> None:
    pytest.importorskip("numpy")
    # A fresh interpreter is essential: importing NumPy in the pytest process
    # masks the Windows extension-load deadlock. A delayed command also checks
    # that the new pipe wait still wakes and preserves exact UTF-8 transport.
    script = tmp_path / "native-import.py"
    script.write_text(
        "import os, sys, threading, time\n"
        "sys.stdout.reconfigure(encoding='utf-8', errors='strict')\n"
        "from diffeoforge.desktop.pipe_input import UnbufferedUtf8LineInput\n"
        "stream = UnbufferedUtf8LineInput(sys.stdin.fileno())\n"
        "waiting = threading.Event()\n"
        "def read():\n"
        "    waiting.set()\n"
        "    command = stream.readline()\n"
        "    print(command.strip(), flush=True)\n"
        "thread = threading.Thread(target=read, daemon=True)\n"
        "thread.start()\n"
        "waiting.wait()\n"
        "time.sleep(0.1)\n"
        "import numpy\n"
        "print('native-ready', flush=True)\n"
        "thread.join()\n"
        "sys.stdout.flush()\n"
        "os._exit(0)\n",
        encoding="utf-8",
    )
    process = subprocess.Popen(
        [sys.executable, str(script)], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
        **hidden_windows_process_kwargs(),
    )
    output = []
    ready = threading.Event()

    def drain() -> None:
        for line in process.stdout:
            output.append(line.strip())
            if line.strip() == "native-ready":
                ready.set()

    thread = threading.Thread(target=drain, daemon=True)
    thread.start()
    try:
        assert ready.wait(timeout=20), "Native import stalled with an open command pipe"
        process.stdin.write("cancel Käfer\n")
        process.stdin.flush()
        assert process.wait(timeout=10) == 0
        thread.join(timeout=5)
        assert output == ["native-ready", "cancel Käfer"]
        assert process.stderr.read() == ""
    finally:
        if process.poll() is None:
            process.kill()  # Only this explicitly created transport-test child.
            process.wait(timeout=10)
        for stream in (process.stdin, process.stdout, process.stderr):
            stream.close()
