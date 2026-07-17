"""Minimal Windows Job Object wrapper for fail-closed worker supervision."""

from __future__ import annotations

import ctypes
import os
import subprocess
from ctypes import wintypes

JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9


class WindowsJobError(OSError):
    """Raised when a kill-on-close Job Object cannot be established."""


class _IoCounters(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class _BasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _ExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimitInformation),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


def _windows_error(operation: str) -> WindowsJobError:
    code = ctypes.get_last_error()
    message = ctypes.FormatError(code).strip()
    return WindowsJobError(code, f"{operation} failed: {message}")


class WindowsKillOnCloseJob:
    """Own one non-inheritable Job handle that terminates its process tree on close."""

    def __init__(self) -> None:
        if os.name != "nt":
            raise WindowsJobError("Windows Job Objects are available only on Windows")
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = (
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        )
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL

        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            raise _windows_error("CreateJobObjectW")
        self._kernel32 = kernel32
        self._handle: int | None = int(handle)
        limits = _ExtendedLimitInformation()
        limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(
            handle,
            JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
            ctypes.byref(limits),
            ctypes.sizeof(limits),
        ):
            error = _windows_error("SetInformationJobObject")
            self.close()
            raise error

    @property
    def closed(self) -> bool:
        return self._handle is None

    def assign(self, process: subprocess.Popen[str]) -> None:
        """Assign a live ``Popen`` process before any reviewed request is written."""

        if self._handle is None:
            raise WindowsJobError("Windows Job Object handle is already closed")
        process_handle = getattr(process, "_handle", None)
        if process_handle is None:
            raise WindowsJobError("Windows worker process handle is unavailable")
        if process.poll() is not None:
            raise WindowsJobError("Windows worker exited before Job Object assignment")
        if not self._kernel32.AssignProcessToJobObject(self._handle, process_handle):
            raise _windows_error("AssignProcessToJobObject")

    def close(self) -> None:
        """Close the owned handle; a live assigned process tree is then terminated."""

        handle, self._handle = self._handle, None
        if handle is not None and not self._kernel32.CloseHandle(handle):
            raise _windows_error("CloseHandle(JobObject)")
