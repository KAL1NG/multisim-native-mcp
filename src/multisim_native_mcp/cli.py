"""Server launcher, runtime checks and MCP client configuration."""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import shutil
import struct
import sys
import time

from . import __version__
from . import paths as _paths
from .clients import (
    CONFIG_FORMATS,
    SKILL_CLIENTS,
    SUPPORTED_CLIENTS,
    bundled_skill_source,
    codex_document,
    configure,
    configure_client,
    default_config_path,
    default_skill_dir,
    detect_clients,
    install_skill,
    install_skills_for_client,
    json_document,
    opencode_document,
    render_config,
    vscode_document,
)

_INITIAL_DATA_DIR = _paths.DATA_DIR


def client_entry(install_path: str | None = None) -> dict:
    entry = {"command": sys.executable, "args": ["-m", "multisim_native_mcp"]}
    if install_path:
        entry["env"] = {"MULTISIM_NATIVE_INSTALL": str(Path(install_path).resolve())}
    return entry


def _resolve_data_dir(data_dir: Path | None = None) -> Path:
    if data_dir is not None:
        return Path(data_dir).expanduser().resolve()
    if _paths.DATA_DIR != _INITIAL_DATA_DIR:
        return Path(_paths.DATA_DIR).expanduser().resolve()
    env_dir = os.environ.get("MULTISIM_NATIVE_DATA_DIR")
    if env_dir:
        return Path(env_dir).expanduser().resolve()
    return Path(_paths.DATA_DIR).expanduser().resolve()


def _dir_size(path: Path) -> int:
    total = 0
    for root, _, files in os.walk(path):
        for name in files:
            try:
                file_path = Path(root) / name
                if not file_path.is_symlink():
                    total += file_path.stat().st_size
            except OSError:
                pass
    return total


def _protected_session_dirs(base: Path, sessions_dir: Path) -> set[Path]:
    protected: set[Path] = set()
    active_statuses = {"queued", "running", "cancel_requested", "interrupted", "needs_input"}

    def collect_paths(value) -> None:
        if isinstance(value, str):
            if len(value) < 1024 and ("/" in value or "\\" in value):
                try:
                    resolved = Path(value).resolve()
                except (OSError, ValueError):
                    return
                if resolved != sessions_dir and resolved.is_relative_to(sessions_dir):
                    parts = resolved.relative_to(sessions_dir).parts
                    if parts:
                        protected.add((sessions_dir / parts[0]).resolve())
        elif isinstance(value, dict):
            for item in value.values():
                collect_paths(item)
        elif isinstance(value, list):
            for item in value:
                collect_paths(item)

    for folder_name in ("workflows", "experiments"):
        folder = base / folder_name
        if not folder.is_dir():
            continue
        for record_path in folder.glob("*.json"):
            try:
                record = json.loads(record_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(record, dict) and record.get("status") in active_statuses:
                collect_paths(record)
    return protected


def cleanup(keep_environments: int = 2, keep_session_days: float = 7.0, dry_run: bool = False,
            data_dir: Path | None = None) -> dict:
    """Safely prune old tool environments and expired session directories."""
    if isinstance(keep_environments, bool) or not isinstance(keep_environments, int) or keep_environments < 0:
        raise ValueError("keep_environments must be a nonnegative integer")
    if (isinstance(keep_session_days, bool) or not isinstance(keep_session_days, (int, float))
            or not math.isfinite(keep_session_days) or keep_session_days < 0):
        raise ValueError("keep_session_days must be a finite nonnegative number")
    if not isinstance(dry_run, bool):
        raise ValueError("dry_run must be boolean")

    base = _resolve_data_dir(data_dir)
    exe_path = Path(sys.executable).resolve()
    prefix_path = Path(sys.prefix).resolve()
    envs_dir = base / "tools" / "environments"
    sessions_dir = base / "sessions"

    removed_environments: list[str] = []
    kept_environments: list[str] = []
    removed_sessions: list[str] = []
    skipped_sessions: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []
    freed_bytes = 0

    if envs_dir.is_dir():
        candidates = [p for p in envs_dir.iterdir() if p.is_dir() and p.name.startswith("install-")]
        candidates.sort(key=lambda p: (p.stat().st_mtime, p.name), reverse=True)
        for index, env_dir in enumerate(candidates):
            resolved = env_dir.resolve()
            is_active = (
                exe_path == resolved or exe_path.is_relative_to(resolved)
                or prefix_path == resolved or prefix_path.is_relative_to(resolved)
            )
            if is_active or index < keep_environments:
                kept_environments.append(str(env_dir))
                continue
            size = _dir_size(env_dir)
            if dry_run:
                removed_environments.append(str(env_dir))
                freed_bytes += size
            else:
                try:
                    shutil.rmtree(env_dir, ignore_errors=False)
                except OSError as error:
                    errors.append({"path": str(env_dir), "error": str(error)})
                else:
                    removed_environments.append(str(env_dir))
                    freed_bytes += size

    if sessions_dir.is_dir():
        protected = _protected_session_dirs(base, sessions_dir.resolve())
        cutoff = time.time() - keep_session_days * 86400.0
        for session_dir in sorted(sessions_dir.iterdir(), key=lambda p: p.name):
            if not session_dir.is_dir():
                continue
            resolved = session_dir.resolve()
            if resolved in protected:
                skipped_sessions.append({"path": str(session_dir), "reason": "referenced_by_active_or_interrupted_job"})
                continue
            try:
                mtime = session_dir.stat().st_mtime
            except OSError as error:
                errors.append({"path": str(session_dir), "error": str(error)})
                continue
            expired = (mtime <= cutoff) if keep_session_days == 0 else (mtime < cutoff)
            if not expired:
                continue
            size = _dir_size(session_dir)
            if dry_run:
                removed_sessions.append(str(session_dir))
                freed_bytes += size
            else:
                try:
                    shutil.rmtree(session_dir, ignore_errors=False)
                except OSError as error:
                    errors.append({"path": str(session_dir), "error": str(error)})
                else:
                    removed_sessions.append(str(session_dir))
                    freed_bytes += size

    return {
        "data_directory": str(base),
        "dry_run": dry_run,
        "keep_environments": keep_environments,
        "keep_session_days": keep_session_days,
        "kept_environments": kept_environments,
        "removed_environments": removed_environments,
        "removed_sessions": removed_sessions,
        "skipped_sessions": skipped_sessions,
        "removed_paths": removed_environments + removed_sessions,
        "freed_bytes": freed_bytes,
        "errors": errors,
    }


def doctor(install_path: str | None = None, connect: bool = False) -> dict:
    if install_path:
        os.environ["MULTISIM_NATIVE_INSTALL"] = str(Path(install_path).resolve())
    from .paths import DATA_DIR, RESOURCE_DIR
    try:
        bundled_skill_source()
        skill_bundled = True
    except FileNotFoundError:
        skill_bundled = False
    report = {
        "version": __version__, "platform": sys.platform,
        "python": sys.version.split()[0], "architecture": struct.calcsize("P") * 8,
        "resources": all((RESOURCE_DIR / name).is_file() for name in (
            "host_agent.js", "editor_agent.js", "simulation_settings.js", "startup_agent.js", "native-profile.json", "assets/blank14.3.ms14")),
        "skill_bundled": skill_bundled,
        "detected_clients": detect_clients(),
        "data_directory": str(DATA_DIR),
    }
    if sys.platform == "win32" and struct.calcsize("P") == 4:
        from .bridge import NativeHost
        host = NativeHost()
        try:
            report["runtime"] = host.runtime_status()
        finally:
            host.close()
    report["ready"] = bool(report["resources"] and report.get("runtime", {}).get("available"))
    if connect:
        import asyncio
        try:
            report['connection']=asyncio.run(check_connection())
        except Exception as error:report['connection']={'ready':False,'error':str(error)[:300]}
        report['ready']=report['ready'] and report['connection']['ready']
    return report


async def check_connection():
    from mcp import ClientSession,types
    from mcp.client.stdio import StdioServerParameters,stdio_client
    from tempfile import TemporaryDirectory
    with TemporaryDirectory(prefix='multisim-native-check-') as data_directory:
      parameters=StdioServerParameters(command=sys.executable,args=['-m','multisim_native_mcp'],
          env={**os.environ,'MULTISIM_NATIVE_DATA_DIR':data_directory})
      async with stdio_client(parameters) as (reader,writer):
        async with ClientSession(reader,writer,read_timeout_seconds=30) as session:
            initialized=await session.initialize();names=set();cursor=None
            while True:
                page=await session.list_tools(params=types.PaginatedRequestParams(cursor=cursor)) if cursor else await session.list_tools()
                names.update(tool.name for tool in page.tools)
                cursor=page.next_cursor
                if not cursor:break
            result=await session.call_tool('native_runtime_status',{})
            if result.is_error:raise RuntimeError('MCP runtime status failed')
            runtime=result.structured_content or json.loads(result.content[0].text)
            required={'native_runtime_status','native_create_circuit','native_open_copy','native_export_image'}
            return {'ready':required<=names and runtime['available'],'server_version':initialized.server_info.version,'tool_count':len(names)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="multisim-native-mcp", description="Native Multisim MCP server")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="action")
    commands.add_parser("serve", help="Run the STDIO MCP server")
    check = commands.add_parser("doctor", help="Check Python, packaged resources and Multisim")
    check.add_argument("--multisim-path")
    check.add_argument("--connect",action='store_true',help='Check the STDIO handshake, tools and runtime status')
    config = commands.add_parser("config", help="Print an MCP configuration")
    config.add_argument("--format", choices=list(CONFIG_FORMATS), default="json")
    config.add_argument("--multisim-path")
    register = commands.add_parser("configure", help="Register the server and bundled skill in one or more MCP clients")
    register.add_argument("--client", choices=list(SUPPORTED_CLIENTS), default="codex")
    register.add_argument("--profile", default="desktop")
    register.add_argument("--config-path", type=Path)
    register.add_argument("--project-dir", type=Path)
    register.add_argument("--skill-dir", type=Path)
    register.add_argument("--skip-skill", action="store_true", help="Configure MCP only without installing the bundled Agent Skill")
    register.add_argument("--multisim-path")
    skill_cmd = commands.add_parser("install-skill", help="Install or update the bundled multisim-native Agent Skill")
    skill_cmd.add_argument("--client", choices=list(SKILL_CLIENTS), default="auto")
    skill_cmd.add_argument("--profile", default="desktop")
    skill_cmd.add_argument("--project-dir", type=Path)
    skill_cmd.add_argument("--skill-dir", type=Path)
    clients_cmd = commands.add_parser("clients", help="Inspect detected AI agent harnesses and their config/skill paths")
    clients_cmd.add_argument("--profile", default="desktop")
    clients_cmd.add_argument("--project-dir", type=Path)
    clean = commands.add_parser("cleanup", help="Prune old tool environments and expired session directories")
    clean.add_argument("--keep-environments", type=int, default=2)
    clean.add_argument("--keep-session-days", type=float, default=7.0)
    clean.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.action == "config":
            entry = client_entry(args.multisim_path)
            print(render_config(entry, args.format).rstrip("\n"))
            return 0
        if args.action == "configure":
            report = configure_client(
                args.client,
                client_entry(args.multisim_path),
                config_path=args.config_path,
                profile=args.profile,
                project_dir=args.project_dir,
                install_skill_files=not args.skip_skill,
                skill_dir=args.skill_dir,
            )
            print(json.dumps(report, indent=2, ensure_ascii=False))
            return 0
        if args.action == "install-skill":
            report = install_skills_for_client(
                args.client,
                skill_dir=args.skill_dir,
                project_dir=args.project_dir,
                profile=args.profile,
            )
            print(json.dumps(report, indent=2, ensure_ascii=False))
            return 0
        if args.action == "clients":
            detected = detect_clients(profile=args.profile)
            items = []
            for name in SUPPORTED_CLIENTS:
                if name in ("auto", "json"):
                    continue
                cfg = default_config_path(name, profile=args.profile, project_dir=args.project_dir)
                skl = default_skill_dir(name, project_dir=args.project_dir)
                items.append({
                    "client": name,
                    "detected": name in detected,
                    "config_path": str(cfg),
                    "skill_dir": str(skl) if skl is not None else None,
                })
            print(json.dumps({"detected": detected, "clients": items}, indent=2, ensure_ascii=False))
            return 0
        if args.action == "cleanup":
            report = cleanup(args.keep_environments, args.keep_session_days, args.dry_run)
            print(json.dumps(report, indent=2, ensure_ascii=False))
            return 0
        if args.action == "doctor":
            report = doctor(args.multisim_path,args.connect)
            print(json.dumps(report, indent=2))
            return 0 if report["ready"] else 1
        if sys.platform != "win32" or struct.calcsize("P") != 4:
            parser.error("Use Windows with 32-bit Python 3.12. Run install.ps1 to set up the runtime.")
        from .server import main as serve
        serve()
        return 0
    except (OSError, ValueError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        return 1
