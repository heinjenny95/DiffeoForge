"""UTF-8 worker commands without a permanently blocked Windows pipe read."""

from __future__ import annotations

import os
import time
from collections.abc import Iterator


class _WindowsPipeReader:
    """Read available bytes only, allowing native DLL initialization to finish."""

    def __init__(self, file_descriptor: int) -> None:
        import ctypes
        import msvcrt
        from ctypes import wintypes

        # Resolve the CRT descriptor and native API before the command thread starts.
        self._ctypes = ctypes
        self._dword = wintypes.DWORD
        self._handle = msvcrt.get_osfhandle(file_descriptor)
        self._api = ctypes.WinDLL("kernel32", use_last_error=True)
        self._peek = self._api.PeekNamedPipe
        self._peek.argtypes = [
            wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
            ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p,
        ]
        self._peek.restype = wintypes.BOOL
        self._read = self._api.ReadFile
        self._read.argtypes = [
            wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p,
        ]
        self._read.restype = wintypes.BOOL

    def _eof_or_raise(self) -> bytes:
        error = self._ctypes.get_last_error()
        if error in (38, 109):  # ERROR_HANDLE_EOF / ERROR_BROKEN_PIPE
            return b""
        raise self._ctypes.WinError(error)

    def read(self, size: int) -> bytes:
        available = self._dword()
        while True:
            if not self._peek(self._handle, None, 0, None, self._ctypes.byref(available), None):
                return self._eof_or_raise()
            if available.value:
                break
            # A synchronous ReadFile/os.read waiting for the next command can
            # block NumPy's Windows extension initialization in another thread.
            # This pipe has exactly one reader, so the available-byte read below
            # cannot consume bytes belonging to a competing consumer.
            time.sleep(0.02)
        size = min(size, available.value)
        buffer = self._ctypes.create_string_buffer(size)
        count = self._dword()
        if not self._read(self._handle, buffer, size, self._ctypes.byref(count), None):
            return self._eof_or_raise()
        return buffer.raw[:count.value]


class UnbufferedUtf8LineInput:
    """Single-reader pipe transport; retain partial UTF-8 and queued commands."""

    def __init__(self, file_descriptor: int) -> None:
        self._file_descriptor = file_descriptor
        self._windows_reader = _WindowsPipeReader(file_descriptor) if os.name == "nt" else None
        self._buffer = bytearray()
        self._eof = False

    def readline(self) -> str:
        while True:
            line = self.pop_buffered_line()
            if line is not None:
                return line
            if self._eof:
                line = bytes(self._buffer)
                self._buffer.clear()
                return line.decode("utf-8")
            chunk = (
                self._windows_reader.read(4096)
                if self._windows_reader is not None
                else os.read(self._file_descriptor, 4096)
            )
            if chunk:
                self._buffer.extend(chunk)
            else:
                self._eof = True

    def pop_buffered_line(self) -> str | None:
        """Return an already-received line without waiting for more pipe input."""

        newline = self._buffer.find(b"\n")
        if newline < 0:
            return None
        line = bytes(self._buffer[:newline + 1])
        del self._buffer[:newline + 1]
        return line.decode("utf-8")

    def __iter__(self) -> Iterator[str]:
        return self

    def __next__(self) -> str:
        line = self.readline()
        if not line:
            raise StopIteration
        return line
