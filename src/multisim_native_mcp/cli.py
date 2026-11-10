"""Server launcher, runtime checks and MCP client configuration."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import struct
import sys

from . import __version__


def client_entry(install_path: str | None = None) -> dict:
    entry = {"command": sys.executable, "args": ["-m", "multisim_native_mcp"]}
    if install_path:
        entry["env"] = {"MULTISIM_NATIVE_INSTALL": str(Path(install_path).resolve())}
    return entry


def codex_document(text: str, entry: dict) -> str:
    """Round-trip other settings, replacing the named server table."""
    import tomlkit
    document = tomlkit.parse(text)
    servers = document.setdefault("mcp_servers", tomlkit.table())
    settings = tomlkit.table()
    settings.update(entry)
    settings["startup_timeout_sec"] = 30
    settings["tool_timeout_sec"] = 90
    servers["multisim_native"] = settings
    return tomlkit.dumps(document)


def configure(path: Path, entry: dict) -> dict:
    original = path.read_text(encoding="utf-8") if path.exists() else ""
    result = codex_document(original, entry)
    backup = None
    if original != result:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            backup = path.with_name(path.name + "." + stamp + ".bak")
            shutil.copy2(path, backup)
        temporary = path.with_name(path.name + ".multisim.tmp")
        temporary.write_text(result, encoding="utf-8", newline="\n")
        temporary.replace(path)
    return {"config": str(path), "server": "multisim_native", "backup": str(backup) if backup else None}


def doctor(install_path: str | None = None) -> dict:
    if install_path:
        os.environ["MULTISIM_NATIVE_INSTALL"] = str(Path(install_path).resolve())
    from .paths import DATA_DIR, RESOURCE_DIR
    report = {
        "version": __version__, "platform": sys.platform,
        "python": sys.version.split()[0], "architecture": struct.calcsize("P") * 8,
        "resources": all((RESOURCE_DIR / name).is_file() for name in (
            "host_agent.js", "editor_agent.js", "startup_agent.js", "native-profile.json", "assets/blank14.3.ms14")),
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
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="multisim-native-mcp", description="Native Multisim MCP server")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="action")
    commands.add_parser("serve", help="Run the STDIO MCP server")
    check = commands.add_parser("doctor", help="Check Python, packaged resources and Multisim")
    check.add_argument("--multisim-path")
    config = commands.add_parser("config", help="Print an MCP configuration")
    config.add_argument("--format", choices=["json", "codex"], default="json")
    config.add_argument("--multisim-path")
    register = commands.add_parser("configure", help="Register the server in Codex")
    register.add_argument("--config-path", type=Path)
    register.add_argument("--multisim-path")
    args = parser.parse_args(argv)
    try:
        if args.action == "config":
            entry = client_entry(args.multisim_path)
            print(codex_document("", entry) if args.format == "codex" else json.dumps({"mcpServers": {"multisim_native": entry}}, indent=2))
            return 0
        if args.action == "configure":
            path = args.config_path or Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "config.toml"
            print(json.dumps(configure(path, client_entry(args.multisim_path)), indent=2))
            return 0
        if args.action == "doctor":
            report = doctor(args.multisim_path)
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
