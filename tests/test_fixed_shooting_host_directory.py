import os
from types import SimpleNamespace

import pytest

from diffeoforge.reference_fixed_shooting import _host_working_directory


def test_non_wsl_command_keeps_its_numerical_current_directory(tmp_path):
    command = SimpleNamespace(argv=('native-runtime', 'compute'), working_directory=str(tmp_path))
    assert _host_working_directory(command) == str(tmp_path)


@pytest.mark.skipif(os.name != 'nt', reason='Windows WSL host directory contract')
def test_long_wsl_directory_stays_in_argv_while_windows_host_uses_drive_root(tmp_path):
    from pathlib import PureWindowsPath

    from diffeoforge.backends.deformetrica_reference import _windows_to_wsl

    folder = tmp_path
    for _ in range(10):
        folder /= 'retained-field-prefix-check'
    folder.mkdir(parents=True)
    assert len(str(folder)) > 260
    argv = ('wsl.exe', '-d', 'Ubuntu', '--cd', _windows_to_wsl(folder), '--', 'engine')
    command = SimpleNamespace(argv=argv, working_directory=str(folder))
    assert _host_working_directory(command) == PureWindowsPath(folder).anchor
    assert command.argv == argv and command.working_directory == str(folder)


@pytest.mark.skipif(os.name != 'nt', reason='Windows WSL host directory contract')
@pytest.mark.parametrize('argv', [('wsl.exe',), ('wsl.exe', '--cd', '/wrong'),
                                 ('wsl.exe', '--cd', '/a', '--cd', '/b')])
def test_missing_or_mismatched_numerical_directory_is_rejected(tmp_path, argv):
    with pytest.raises(ValueError, match='numerical directory'):
        _host_working_directory(SimpleNamespace(argv=argv, working_directory=str(tmp_path)))
