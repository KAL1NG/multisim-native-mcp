import json
import os
from pathlib import Path
import subprocess
import sys
import time
import tomllib

import pytest

from multisim_native_mcp import cli
from multisim_native_mcp.cli import cleanup, client_entry, codex_document, configure, json_document, main


def test_codex_round_trip_preserves_other_servers():
    original = '# workspace settings\nmodel = "gpt-6"\n[mcp_servers.other]\ncommand = "other.exe"\n'
    result = codex_document(original, client_entry(r"C:\NI Suite"))
    data = tomllib.loads(result)
    assert '# workspace settings' in result
    assert data['model'] == 'gpt-6'
    assert data['mcp_servers']['other']['command'] == 'other.exe'
    assert data['mcp_servers']['multisim_native']['env']['MULTISIM_NATIVE_INSTALL'] == str(Path(r'C:\NI Suite').resolve())


def test_replace_existing_server_removes_old_environment():
    result = codex_document('[mcp_servers.multisim_native]\ncommand="old"\n[mcp_servers.multisim_native.env]\nOLD="old"\n', client_entry())
    entry = tomllib.loads(result)['mcp_servers']['multisim_native']
    assert entry['command'] == sys.executable
    assert 'env' not in entry
    assert 'startup_timeout_sec' not in entry and 'tool_timeout_sec' not in entry


def test_normal_configuration_does_not_pin_a_previous_project_globally():
    source='[mcp_servers.multisim_native]\ncommand="old"\n[mcp_servers.multisim_native.env]\nMULTISIM_NATIVE_WORKSPACE="E:/work"\nOLD="old"\n'
    result=tomllib.loads(codex_document(source,client_entry()))
    assert 'env' not in result['mcp_servers']['multisim_native']


def test_configure_backups_and_idempotence(tmp_path):
    path = tmp_path / 'profile with spaces' / 'config.toml'
    path.parent.mkdir();path.write_text('model = "sample"\n', encoding='utf-8')
    entry = client_entry()
    first = configure(path, entry)
    assert Path(first['backup']).read_text(encoding='utf-8') == 'model = "sample"\n'
    assert tomllib.loads(path.read_text())['model'] == 'sample'
    assert configure(path, entry)['backup'] is None


def test_invalid_toml_leaves_original_bytes(tmp_path):
    import pytest
    path = tmp_path/'config.toml';raw=b'[invalid\n';path.write_bytes(raw)
    with pytest.raises(Exception):configure(path, client_entry())
    assert path.read_bytes() == raw
    assert list(tmp_path.iterdir()) == [path]


def test_config_command_emits_launchable_json():
    process = subprocess.run([sys.executable,'-m','multisim_native_mcp','config'],capture_output=True,text=True,check=True)
    entry = json.loads(process.stdout)['mcpServers']['multisim_native']
    assert entry['command'] == sys.executable
    assert entry['args'] == ['-m','multisim_native_mcp']


def test_cli_configure_isolated_home(tmp_path):
    environment = dict(os.environ, CODEX_HOME=str(tmp_path))
    subprocess.run([sys.executable,'-m','multisim_native_mcp','configure'],env=environment,capture_output=True,text=True,check=True)
    assert tomllib.loads((tmp_path/'config.toml').read_text())['mcp_servers']['multisim_native']['command'] == sys.executable


def test_json_configure_preserves_other_keys_and_backups(tmp_path):
    config_file = tmp_path / 'mcp_config.json'
    original_data = {
        'theme': 'dark',
        'mcpServers': {
            'other_server': {'command': 'node', 'args': ['server.js']},
            'multisim_native': {'command': 'stale.exe', 'env': {'OLD': '1'}},
        },
    }
    raw_initial = json.dumps(original_data, indent=2) + '\n'
    config_file.write_text(raw_initial, encoding='utf-8')
    entry = client_entry(r'C:\NI Suite')

    first = configure(config_file, entry, client='json')
    assert first['client'] == 'json' and first['backup'] is not None
    assert Path(first['backup']).read_text(encoding='utf-8') == raw_initial
    parsed = json.loads(config_file.read_text(encoding='utf-8'))
    assert parsed['theme'] == 'dark'
    assert parsed['mcpServers']['other_server'] == {'command': 'node', 'args': ['server.js']}
    assert parsed['mcpServers']['multisim_native']['command'] == sys.executable
    assert 'OLD' not in parsed['mcpServers']['multisim_native'].get('env', {})
    assert configure(config_file, entry, client='json')['backup'] is None

    # Invalid JSON or invalid mcpServers leaves file untouched
    bad = tmp_path / 'bad.json'
    bad.write_bytes(b'{not json')
    with pytest.raises(ValueError, match='Invalid JSON'):
        configure(bad, entry, client='json')
    assert bad.read_bytes() == b'{not json'
    with pytest.raises(ValueError, match='JSON object'):
        json_document('[]', entry)
    with pytest.raises(ValueError, match='mcpServers'):
        json_document('{"mcpServers": []}', entry)

    assert main(['configure', '--client', 'json']) == 1


@pytest.mark.parametrize(('current_exists', 'legacy_exists', 'target_directory'), [
    (False, False, 'config'),
    (True, False, 'config'),
    (False, True, 'antigravity'),
    (True, True, 'config'),
])
def test_antigravity_configure_selects_profile(tmp_path, monkeypatch, current_exists, legacy_exists, target_directory):
    monkeypatch.setattr(Path, 'home', staticmethod(lambda: tmp_path))
    profile = tmp_path / '.gemini'
    for directory, exists in [('config', current_exists), ('antigravity', legacy_exists)]:
        if exists:
            path = profile / directory / 'mcp_config.json'
            path.parent.mkdir(parents=True)
            path.write_text('{}', encoding='utf-8')

    assert main(['configure', '--client', 'antigravity']) == 0
    agy_cfg = profile / target_directory / 'mcp_config.json'
    assert json.loads(agy_cfg.read_text(encoding='utf-8'))['mcpServers']['multisim_native']['command'] == sys.executable
    if current_exists and legacy_exists:
        assert (profile / 'antigravity' / 'mcp_config.json').read_text(encoding='utf-8') == '{}'


def test_cleanup_prunes_old_envs_and_sessions_while_protecting_active_and_referenced(tmp_path, monkeypatch):
    data_dir = tmp_path / 'data'
    envs_dir = data_dir / 'tools' / 'environments'
    sessions_dir = data_dir / 'sessions'
    workflows_dir = data_dir / 'workflows'
    experiments_dir = data_dir / 'experiments'
    for d in (envs_dir, sessions_dir, workflows_dir, experiments_dir):
        d.mkdir(parents=True)

    now = time.time()
    # Create 4 install-* envs: oldest is the active interpreter environment!
    env_active = envs_dir / 'install-active'
    (env_active / 'Scripts').mkdir(parents=True)
    fake_exe = env_active / 'Scripts' / 'python.exe'
    fake_exe.write_bytes(b'x' * 128)
    os.utime(env_active, (now - 4000, now - 4000))

    env_old = envs_dir / 'install-old'
    env_old.mkdir()
    (env_old / 'payload.bin').write_bytes(b'y' * 256)
    os.utime(env_old, (now - 3000, now - 3000))

    env_mid = envs_dir / 'install-mid'
    env_mid.mkdir()
    (env_mid / 'payload.bin').write_bytes(b'z' * 64)
    os.utime(env_mid, (now - 200, now - 200))

    env_new = envs_dir / 'install-new'
    env_new.mkdir()
    (env_new / 'payload.bin').write_bytes(b'w' * 64)
    os.utime(env_new, (now - 100, now - 100))

    # Create 3 session dirs: expired unreferenced, expired referenced by interrupted workflow, and recent
    sess_expired = sessions_dir / 's-expired'
    sess_expired.mkdir()
    (sess_expired / 'checkpoint.ms14').write_bytes(b'a' * 512)
    os.utime(sess_expired, (now - 10 * 86400, now - 10 * 86400))

    sess_protected = sessions_dir / 's-protected'
    sess_protected.mkdir()
    ckpt = sess_protected / 'resume.ms14'
    ckpt.write_bytes(b'b' * 512)
    os.utime(sess_protected, (now - 10 * 86400, now - 10 * 86400))
    (workflows_dir / ('f' * 32 + '.json')).write_text(
        json.dumps({'id': 'f' * 32, 'status': 'interrupted', 'resume_checkpoint': {'path': str(ckpt)}}),
        encoding='utf-8',
    )

    sess_recent = sessions_dir / 's-recent'
    sess_recent.mkdir()
    (sess_recent / 'recent.ms14').write_bytes(b'c' * 64)
    os.utime(sess_recent, (now - 3600, now - 3600))

    monkeypatch.setattr(cli.sys, 'executable', str(fake_exe))
    monkeypatch.setattr(cli.sys, 'prefix', str(env_active))

    # Reject invalid cleanup parameters
    for bad_kwargs in (
        {'keep_environments': True},
        {'keep_environments': -1},
        {'keep_session_days': False},
        {'keep_session_days': -0.5},
        {'dry_run': 1},
    ):
        with pytest.raises(ValueError):
            cleanup(data_dir=data_dir, **bad_kwargs)

    # Dry-run reports without deleting
    dry = cleanup(keep_environments=2, keep_session_days=7.0, dry_run=True, data_dir=data_dir)
    assert dry['dry_run'] is True
    assert dry['removed_environments'] == [str(env_old)]
    assert str(env_active) in dry['kept_environments']
    assert dry['removed_sessions'] == [str(sess_expired)]
    assert any(Path(s['path']) == sess_protected for s in dry['skipped_sessions'])
    assert dry['freed_bytes'] == 256 + 512
    assert env_old.is_dir() and sess_expired.is_dir()

    # Real cleanup via CLI removes only env_old and sess_expired
    monkeypatch.setenv('MULTISIM_NATIVE_DATA_DIR', str(data_dir))
    assert main(['cleanup', '--keep-environments', '2', '--keep-session-days', '7']) == 0
    assert not env_old.exists()
    assert env_active.is_dir() and env_mid.is_dir() and env_new.is_dir()
    assert not sess_expired.exists()
    assert sess_protected.is_dir() and sess_recent.is_dir()


def test_multi_harness_formats_auto_detection_and_bundled_skill_sync(tmp_path, monkeypatch, capsys):
    from multisim_native_mcp.clients import (
        detect_clients,
        install_skill,
        opencode_document,
        vscode_document,
    )

    home = tmp_path / 'home'
    appdata = tmp_path / 'appdata'
    home.mkdir()
    appdata.mkdir()
    monkeypatch.setattr(Path, 'home', staticmethod(lambda: home))
    monkeypatch.setenv('APPDATA', str(appdata))
    monkeypatch.delenv('CODEX_HOME', raising=False)
    monkeypatch.delenv('DSH_HOME', raising=False)

    # 1. VS Code and OpenCode native document schemas round-trip cleanly
    entry = client_entry(r'C:\NI Suite')
    vs_doc = json.loads(vscode_document('{"servers":{"other":{"type":"stdio","command":"x"}}}', entry))
    assert vs_doc['servers']['other']['command'] == 'x'
    assert vs_doc['servers']['multisim_native']['type'] == 'stdio'
    assert vs_doc['servers']['multisim_native']['command'] == sys.executable

    oc_doc = json.loads(opencode_document('{"theme":"light","mcp":{"other":{"type":"local","command":["x"]}}}', entry))
    assert oc_doc['theme'] == 'light' and oc_doc['mcp']['other']['command'] == ['x']
    assert oc_doc['mcp']['multisim_native']['type'] == 'local'
    assert oc_doc['mcp']['multisim_native']['command'] == [sys.executable, '-m', 'multisim_native_mcp']
    assert oc_doc['mcp']['multisim_native']['environment']['MULTISIM_NATIVE_INSTALL'] == str(Path(r'C:\NI Suite').resolve())

    # 2. Conservative detection: Antigravity must NOT false-trigger gemini-cli, and plain VS Code settings must NOT auto-trigger vscode
    (home / '.gemini' / 'config').mkdir(parents=True)
    (home / '.gemini' / 'config' / 'mcp_config.json').write_text('{}', encoding='utf-8')
    (home / '.claude').mkdir()
    (home / '.cursor').mkdir()
    (appdata / 'Code' / 'User').mkdir(parents=True)
    (appdata / 'Code' / 'User' / 'settings.json').write_text('{}', encoding='utf-8')
    (home / '.config' / 'opencode').mkdir(parents=True)

    detected = detect_clients()
    assert detected == ['antigravity', 'claude-code', 'cursor', 'opencode']
    assert 'gemini-cli' not in detected and 'vscode' not in detected

    # 3. configure --client auto configures every detected harness AND installs the bundled skill atomically
    assert main(['configure', '--client', 'auto']) == 0
    report = json.loads(capsys.readouterr().out)
    assert report['client'] == 'auto' and report['fallback'] is False
    assert [c['client'] for c in report['configured']] == ['antigravity', 'claude-code', 'cursor', 'opencode']
    for rel_skill in [
        '.gemini/config/skills/multisim-native/SKILL.md',
        '.claude/skills/multisim-native/SKILL.md',
        '.cursor/skills/multisim-native/SKILL.md',
        '.config/opencode/skills/multisim-native/SKILL.md',
    ]:
        assert (home / rel_skill).is_file()
    assert json.loads((home / '.claude.json').read_text(encoding='utf-8'))['mcpServers']['multisim_native']['command'] == sys.executable
    assert json.loads((home / '.cursor' / 'mcp.json').read_text(encoding='utf-8'))['mcpServers']['multisim_native']['command'] == sys.executable
    assert json.loads((home / '.config' / 'opencode' / 'opencode.json').read_text(encoding='utf-8'))['mcp']['multisim_native']['type'] == 'local'

    # 4. Idempotency + orphan removal on skill sync, plus --skip-skill and --skill-dir parent normalization
    agy_skill_dir = home / '.gemini' / 'config' / 'skills' / 'multisim-native'
    assert install_skill(agy_skill_dir, client='antigravity')['changed'] is False
    stale = agy_skill_dir / 'stale_obsolete.md'
    stale.write_text('old', encoding='utf-8')
    resynced = install_skill(agy_skill_dir.parent, client='antigravity')
    assert resynced['changed'] is True and not stale.exists()
    assert Path(resynced['path']) == agy_skill_dir.resolve()

    # 5. Explicit vscode, gemini-cli, windsurf, claude-desktop, project, agents & --skip-skill
    assert main(['configure', '--client', 'vscode', '--skip-skill']) == 0
    capsys.readouterr()
    assert json.loads((appdata / 'Code' / 'User' / 'mcp.json').read_text(encoding='utf-8'))['servers']['multisim_native']['type'] == 'stdio'
    assert not (home / '.copilot' / 'skills' / 'multisim-native').exists()

    project_root = tmp_path / 'my-project'
    project_root.mkdir()
    assert main(['configure', '--client', 'project', '--project-dir', str(project_root)]) == 0
    capsys.readouterr()
    assert json.loads((project_root / '.mcp.json').read_text(encoding='utf-8'))['mcpServers']['multisim_native']['command'] == sys.executable
    assert (project_root / '.agents' / 'skills' / 'multisim-native' / 'SKILL.md').is_file()

    assert main(['install-skill', '--client', 'agents']) == 0
    capsys.readouterr()
    assert (home / '.agents' / 'skills' / 'multisim-native' / 'SKILL.md').is_file()

    assert main(['clients']) == 0
    clients_report = json.loads(capsys.readouterr().out)
    assert 'vscode' in clients_report['detected'] and 'antigravity' in clients_report['detected']

    for fmt, key in [('vscode', 'servers'), ('opencode', 'mcp'), ('json', 'mcpServers')]:
        assert main(['config', '--format', fmt]) == 0
        out = json.loads(capsys.readouterr().out)
        assert 'multisim_native' in out[key]
