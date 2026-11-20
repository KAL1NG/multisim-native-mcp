import ctypes
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from multisim_native_mcp import bridge
from multisim_native_mcp.cli import main


@pytest.fixture
def different_runtime(tmp_path, monkeypatch):
    installation=tmp_path/'Multisim';installation.mkdir()
    (installation/'multisim.exe').write_bytes(b'installed-runtime')
    resources=tmp_path/'resources';resources.mkdir()
    (resources/'native-profile.json').write_text(json.dumps({
        'version':'different-reference-version','modules':{'multisim.exe':'0'*64},
    }),encoding='utf-8')
    monkeypatch.setattr(bridge,'INSTALL',installation)
    monkeypatch.setattr(bridge,'ROOT',resources)
    monkeypatch.setattr(bridge,'DATA_DIR',tmp_path/'sessions')
    return installation


def test_profile_mismatch_is_diagnostic(different_runtime):
    host=bridge.NativeHost()
    try:
        status=host.runtime_status()
        assert status['available']
        assert not status['compatible']
        assert not status['profile_enforced']
        assert status['tested_version']=='different-reference-version'
        assert status['checks'][0]['match'] is False
    finally:host.close()


def test_doctor_succeeds_with_different_hash_and_version(different_runtime,capsys):
    assert main(['doctor'])==0
    status=json.loads(capsys.readouterr().out)
    assert status['ready']
    assert not status['runtime']['compatible']


def test_unreadable_hash_remains_diagnostic(different_runtime,monkeypatch,capsys):
    def inaccessible(path):raise PermissionError('Fingerprint unavailable')
    monkeypatch.setattr(bridge,'sha256',inaccessible)
    assert main(['doctor'])==0
    status=json.loads(capsys.readouterr().out)
    assert status['ready']
    assert status['runtime']['checks'][0]['error']=='Fingerprint unavailable'


def test_open_copy_reaches_launch_with_mismatched_profile(different_runtime,tmp_path,monkeypatch):
    source=tmp_path/'source.ms14';source.write_bytes(b'circuit')
    monkeypatch.setattr(bridge.frida,'get_local_device',lambda:SimpleNamespace(enumerate_processes=lambda:[]))
    def launch(*args,**kwargs):raise RuntimeError('launch reached')
    monkeypatch.setattr(bridge.subprocess,'Popen',launch)
    host=bridge.NativeHost()
    try:
        with pytest.raises(RuntimeError,match='launch reached'):host.open_copy(str(source))
    finally:host.close()


def test_missing_executable_is_reported(different_runtime,capsys):
    (different_runtime/'multisim.exe').unlink()
    assert main(['doctor'])==1
    assert not json.loads(capsys.readouterr().out)['ready']


@pytest.mark.skipif(not hasattr(ctypes, 'WINFUNCTYPE'), reason='Uses Win32 window enumeration')
def test_modal_detection_distinguishes_splash_and_user_prompt(monkeypatch):
    windows = {
        1: ('#32770', 'Multisim', 7, True),
        2: ('#32770', 'Resolve Duplicate Net Name', 7, True),
        3: ('Static', 'Initializing', 7, True),
        4: ('Static', 'Choose a net name', 7, True),
        5: ('Button', 'OK', 7, True),
        6: ('Button', 'Hidden', 7, False),
        7: ('#32770', 'Other process', 8, True),
    }

    def copy_text(text, buffer):
        buffer.value = text
        return len(text)

    def get_pid(hwnd, pointer):
        ctypes.cast(pointer, ctypes.POINTER(bridge.w.DWORD)).contents.value = windows[hwnd][2]
        return 1

    def enumerate_windows(ids, callback):
        for hwnd in ids:
            if not callback(hwnd, 0):
                break
        return True

    user = SimpleNamespace(
        IsWindowVisible=Mock(side_effect=lambda hwnd: windows[hwnd][3]),
        GetWindowThreadProcessId=Mock(side_effect=get_pid),
        GetClassNameW=Mock(side_effect=lambda hwnd, buffer, size: copy_text(windows[hwnd][0], buffer)),
        GetWindowTextLengthW=Mock(side_effect=lambda hwnd: len(windows[hwnd][1])),
        GetWindowTextW=Mock(side_effect=lambda hwnd, buffer, size: copy_text(windows[hwnd][1], buffer)),
        EnumWindows=Mock(side_effect=lambda callback, _: enumerate_windows((1, 2, 7), callback)),
        EnumChildWindows=Mock(side_effect=lambda hwnd, callback, _: enumerate_windows({1: (3, 6), 2: (4, 5)}[hwnd], callback)),
    )
    monkeypatch.setattr(bridge.ctypes, 'WinDLL', lambda *args, **kwargs: user)

    assert bridge.detect_modal_dialogs(7) == [
        {'title': 'Resolve Duplicate Net Name', 'messages': ['Choose a net name'], 'buttons': ['OK']},
    ]


@pytest.mark.parametrize('timeout', ['0', 'nan', 'inf'])
def test_invalid_startup_timeout_fails_before_launch(different_runtime, tmp_path, monkeypatch, timeout):
    source = tmp_path / 'source.ms14'
    source.write_bytes(b'circuit')
    monkeypatch.setattr(bridge.frida, 'get_local_device', lambda: SimpleNamespace(enumerate_processes=lambda: []))
    monkeypatch.setenv('MULTISIM_NATIVE_STARTUP_TIMEOUT', timeout)
    launch = Mock()
    monkeypatch.setattr(bridge.subprocess, 'Popen', launch)

    with pytest.raises(ValueError, match='MULTISIM_NATIVE_STARTUP_TIMEOUT'):
        bridge.NativeHost().open_copy(str(source))

    launch.assert_not_called()
