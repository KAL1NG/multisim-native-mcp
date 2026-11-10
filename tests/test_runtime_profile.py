import json
from pathlib import Path
from types import SimpleNamespace

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
