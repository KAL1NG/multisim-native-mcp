"""Multi-harness MCP client configuration and bundled Agent Skill installer."""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import uuid

from . import __version__

SUPPORTED_CLIENTS = (
    "auto",
    "codex",
    "antigravity",
    "claude-code",
    "claude-desktop",
    "cursor",
    "windsurf",
    "gemini-cli",
    "vscode",
    "copilot",
    "opencode",
    "dsh",
    "project",
    "json",
)

SKILL_CLIENTS = (
    "auto",
    "agents",
    "codex",
    "antigravity",
    "claude-code",
    "cursor",
    "windsurf",
    "gemini-cli",
    "vscode",
    "copilot",
    "opencode",
    "project",
)

CONFIG_FORMATS = ("json", "codex", "dsh", "vscode", "opencode")

_SKILL_NAME = "multisim-native"


def bundled_skill_source() -> Path:
    """Locate the packaged multisim-native Agent Skill directory."""
    package_dir = Path(__file__).resolve().parent
    candidates = [
        package_dir / "bundled_skills" / _SKILL_NAME,
        package_dir.parents[1] / "skills" / _SKILL_NAME,
    ]
    for candidate in candidates:
        if (candidate / "SKILL.md").is_file():
            return candidate
    raise FileNotFoundError("Bundled multisim-native skill files are missing from this installation")


def _appdata_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata).expanduser()
    return Path.home() / "AppData" / "Roaming"


def antigravity_profile_dir() -> Path:
    """Prefer ~/.gemini/config, falling back to legacy ~/.gemini/antigravity only when it alone exists."""
    gemini = Path.home() / ".gemini"
    current = gemini / "config"
    legacy = gemini / "antigravity"
    if not (current / "mcp_config.json").is_file() and (legacy / "mcp_config.json").is_file():
        return legacy
    return current


def codex_home_dir() -> Path:
    return Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser()


def _opencode_config_path() -> Path:
    xdg = Path.home() / ".config" / "opencode"
    appdata = _appdata_dir() / "opencode"
    if (xdg / "opencode.json").is_file():
        return xdg / "opencode.json"
    if (appdata / "opencode.json").is_file() or (appdata.is_dir() and not xdg.is_dir()):
        return appdata / "opencode.json"
    return xdg / "opencode.json"


def _windsurf_config_path() -> Path:
    codeium = Path.home() / ".codeium" / "windsurf" / "mcp_config.json"
    roaming = _appdata_dir() / "Windsurf" / "mcp.json"
    if not codeium.is_file() and roaming.is_file():
        return roaming
    return codeium


def default_config_path(client: str, *, profile: str = "desktop", project_dir: Path | None = None) -> Path:
    from .dsh_config import profile_path

    home = Path.home()
    appdata = _appdata_dir()
    if client == "codex":
        return codex_home_dir() / "config.toml"
    if client == "antigravity":
        return antigravity_profile_dir() / "mcp_config.json"
    if client == "claude-code":
        return home / ".claude.json"
    if client == "claude-desktop":
        return appdata / "Claude" / "claude_desktop_config.json"
    if client == "cursor":
        return home / ".cursor" / "mcp.json"
    if client == "windsurf":
        return _windsurf_config_path()
    if client == "gemini-cli":
        return home / ".gemini" / "settings.json"
    if client == "vscode":
        return appdata / "Code" / "User" / "mcp.json"
    if client == "copilot":
        return home / ".copilot" / "mcp-config.json"
    if client == "opencode":
        return _opencode_config_path()
    if client == "dsh":
        return profile_path(profile)
    if client == "project":
        root = Path(project_dir).expanduser().resolve() if project_dir is not None else Path.cwd().resolve()
        return root / ".mcp.json"
    if client == "json":
        raise ValueError("Provide --config-path for --client json")
    raise ValueError(f"Unsupported MCP client: {client}")


def default_skill_dir(
    client: str,
    *,
    config_path: Path | None = None,
    project_dir: Path | None = None,
) -> Path | None:
    home = Path.home()
    if client == "codex":
        base = config_path.parent if config_path is not None else codex_home_dir()
        return base / "skills" / _SKILL_NAME
    if client == "antigravity":
        base = config_path.parent if config_path is not None else antigravity_profile_dir()
        return base / "skills" / _SKILL_NAME
    if client == "claude-code":
        return home / ".claude" / "skills" / _SKILL_NAME
    if client == "cursor":
        return home / ".cursor" / "skills" / _SKILL_NAME
    if client == "windsurf":
        return home / ".codeium" / "windsurf" / "skills" / _SKILL_NAME
    if client == "gemini-cli":
        return home / ".gemini" / "skills" / _SKILL_NAME
    if client in ("vscode", "copilot"):
        return home / ".copilot" / "skills" / _SKILL_NAME
    if client == "opencode":
        return home / ".config" / "opencode" / "skills" / _SKILL_NAME
    if client == "project":
        root = Path(project_dir).expanduser().resolve() if project_dir is not None else Path.cwd().resolve()
        return root / ".agents" / "skills" / _SKILL_NAME
    if client == "agents":
        return home / ".agents" / "skills" / _SKILL_NAME
    if client in ("claude-desktop", "dsh", "json", "none"):
        return None
    raise ValueError(f"Unsupported skill client: {client}")


def detect_clients(*, profile: str = "desktop") -> list[str]:
    """Conservatively detect installed AI agent harnesses on this machine."""
    from .dsh_config import profile_path

    home = Path.home()
    appdata = _appdata_dir()
    gemini = home / ".gemini"
    detected: list[str] = []

    if (
        (gemini / "config" / "mcp_config.json").is_file()
        or (gemini / "antigravity" / "mcp_config.json").is_file()
        or (gemini / "config" / "skills").is_dir()
    ):
        detected.append("antigravity")
    if os.environ.get("CODEX_HOME") or (home / ".codex").is_dir():
        detected.append("codex")
    if (home / ".claude.json").is_file() or (home / ".claude").is_dir():
        detected.append("claude-code")
    if (appdata / "Claude").is_dir():
        detected.append("claude-desktop")
    if (home / ".cursor").is_dir():
        detected.append("cursor")
    if (home / ".codeium" / "windsurf").is_dir() or (appdata / "Windsurf" / "mcp.json").is_file():
        detected.append("windsurf")
    if (gemini / "settings.json").is_file():
        detected.append("gemini-cli")
    if (home / ".copilot").is_dir():
        detected.append("copilot")
    if (appdata / "Code" / "User" / "mcp.json").is_file():
        detected.append("vscode")
    if (home / ".config" / "opencode").is_dir() or (appdata / "opencode").is_dir():
        detected.append("opencode")
    if os.environ.get("DSH_HOME") or profile_path(profile).parent.is_dir():
        detected.append("dsh")

    return detected


def codex_document(text: str, entry: dict) -> str:
    """Round-trip other Codex settings and servers, replacing the multisim_native table."""
    import tomlkit

    document = tomlkit.parse(text)
    servers = document.get("mcp_servers")
    if servers is None:
        servers = tomlkit.table(is_super_table=True)
        document["mcp_servers"] = servers
    table = tomlkit.table()
    table["command"] = entry["command"]
    table["args"] = entry["args"]
    if "env" in entry:
        environment = tomlkit.table()
        for key, value in entry["env"].items():
            environment[key] = value
        table["env"] = environment
    servers["multisim_native"] = table
    return tomlkit.dumps(document)


def _load_json_object(text: str) -> dict:
    if text.strip():
        try:
            document = json.loads(text)
        except json.JSONDecodeError as error:
            raise ValueError("Invalid JSON MCP configuration") from error
    else:
        document = {}
    if not isinstance(document, dict):
        raise ValueError("MCP JSON configuration must be a JSON object")
    return document


def json_document(text: str, entry: dict, *, root_key: str = "mcpServers", server_type: str | None = None) -> str:
    """Round-trip other JSON settings and servers, replacing the multisim_native entry."""
    document = _load_json_object(text)
    servers = document.get(root_key)
    if servers is None:
        servers = {}
        document[root_key] = servers
    elif not isinstance(servers, dict):
        raise ValueError(f"{root_key} must be a JSON object")
    server_entry = copy.deepcopy(entry)
    if server_type is not None:
        server_entry = {"type": server_type, **server_entry}
    servers["multisim_native"] = server_entry
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def vscode_document(text: str, entry: dict) -> str:
    """Round-trip VS Code mcp.json using the native 'servers' root key and stdio type."""
    return json_document(text, entry, root_key="servers", server_type="stdio")


def opencode_document(text: str, entry: dict) -> str:
    """Round-trip OpenCode opencode.json using the 'mcp' object with local command array."""
    document = _load_json_object(text)
    servers = document.get("mcp")
    if servers is None:
        servers = {}
        document["mcp"] = servers
    elif not isinstance(servers, dict):
        raise ValueError("mcp must be a JSON object")
    local_entry: dict = {
        "type": "local",
        "command": [entry["command"], *entry.get("args", [])],
        "enabled": True,
    }
    if entry.get("env"):
        local_entry["environment"] = copy.deepcopy(entry["env"])
    servers["multisim_native"] = local_entry
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def render_config(entry: dict, fmt: str = "json") -> str:
    from .dsh_config import dsh_document

    if fmt == "dsh":
        return dsh_document("", entry)
    if fmt == "codex":
        return codex_document("", entry)
    if fmt == "vscode":
        return vscode_document("", entry)
    if fmt == "opencode":
        return opencode_document("", entry)
    if fmt == "json":
        return json_document("", entry)
    raise ValueError(f"Unsupported config format: {fmt}")


def _render_client_document(original: str, entry: dict, client: str) -> str:
    from .dsh_config import dsh_document

    if client == "dsh":
        return dsh_document(original, entry)
    if client == "codex":
        return codex_document(original, entry)
    if client == "vscode":
        return vscode_document(original, entry)
    if client == "opencode":
        return opencode_document(original, entry)
    if client in (
        "json",
        "antigravity",
        "claude-code",
        "claude-desktop",
        "cursor",
        "windsurf",
        "gemini-cli",
        "copilot",
        "project",
    ):
        return json_document(original, entry)
    raise ValueError(f"Unsupported MCP client: {client}")


def configure(path: Path, entry: dict, client: str = "codex") -> dict:
    original = path.read_text(encoding="utf-8-sig") if path.exists() else ""
    result = _render_client_document(original, entry, client)
    backup = None
    if original != result:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            backup = path.with_name(f"{path.name}.{stamp}.bak")
            shutil.copy2(path, backup)
        temporary = path.with_name(path.name + ".multisim.tmp")
        temporary.write_text(result, encoding="utf-8", newline="\n")
        temporary.replace(path)
    return {"config": str(path), "client": client, "server": "multisim_native", "backup": str(backup) if backup else None}


def _tree_digest(root: Path) -> dict[str, str]:
    manifest: dict[str, str] = {}
    if not root.is_dir():
        return manifest
    for item in sorted(root.rglob("*")):
        if item.is_file():
            rel = item.relative_to(root).as_posix()
            manifest[rel] = hashlib.sha256(item.read_bytes()).hexdigest()
    return manifest


def install_skill(
    target_dir: Path | None = None,
    *,
    client: str = "codex",
    config_path: Path | None = None,
    project_dir: Path | None = None,
    source: Path | None = None,
) -> dict:
    """Atomically install or sync the bundled multisim-native Agent Skill."""
    src = Path(source).expanduser().resolve() if source is not None else bundled_skill_source()
    if not (src / "SKILL.md").is_file():
        raise FileNotFoundError(f"Skill source does not contain SKILL.md: {src}")

    if target_dir is not None:
        dest = Path(target_dir).expanduser()
        if dest.name.lower() != _SKILL_NAME and not (dest / "SKILL.md").is_file():
            dest = dest / _SKILL_NAME
    else:
        resolved = default_skill_dir(client, config_path=config_path, project_dir=project_dir)
        if resolved is None:
            return {
                "installed": False,
                "skipped": True,
                "client": client,
                "reason": f"Client {client!r} has no default skills directory; pass --skill-dir to install explicitly.",
            }
        dest = resolved

    src_manifest = _tree_digest(src)
    files = sorted(src_manifest)
    dest_resolved = dest.resolve()
    if dest_resolved == src:
        return {
            "installed": True,
            "changed": False,
            "client": client,
            "path": str(dest_resolved),
            "skill_file": str(dest_resolved / "SKILL.md"),
            "version": __version__,
            "files": files,
        }

    if dest.is_dir() and _tree_digest(dest) == src_manifest:
        return {
            "installed": True,
            "changed": False,
            "client": client,
            "path": str(dest_resolved),
            "skill_file": str(dest_resolved / "SKILL.md"),
            "version": __version__,
            "files": files,
        }

    dest.parent.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    staged = dest.parent / f".{_SKILL_NAME}-stage-{token}"
    backup = dest.parent / f".{_SKILL_NAME}-backup-{token}"
    moved_existing = False
    try:
        shutil.copytree(src, staged)
        if dest.exists():
            dest.rename(backup)
            moved_existing = True
        staged.rename(dest)
    except Exception:
        if moved_existing and backup.exists() and not dest.exists():
            try:
                backup.rename(dest)
            except OSError:
                pass
        shutil.rmtree(staged, ignore_errors=True)
        raise
    else:
        if moved_existing:
            shutil.rmtree(backup, ignore_errors=True)

    return {
        "installed": True,
        "changed": True,
        "client": client,
        "path": str(dest.resolve()),
        "skill_file": str((dest / "SKILL.md").resolve()),
        "version": __version__,
        "files": files,
    }


def install_skills_for_client(
    client: str = "auto",
    *,
    skill_dir: Path | None = None,
    project_dir: Path | None = None,
    profile: str = "desktop",
) -> dict:
    if skill_dir is not None:
        return install_skill(skill_dir, client=client, project_dir=project_dir)
    if client != "auto":
        return install_skill(None, client=client, project_dir=project_dir)

    detected = detect_clients(profile=profile)
    targets: list[tuple[str, Path]] = []
    seen: set[Path] = set()
    for name in detected:
        path = default_skill_dir(name, project_dir=project_dir)
        if path is not None:
            resolved = path.resolve()
            if resolved not in seen:
                seen.add(resolved)
                targets.append((name, path))
    agents_root = Path.home() / ".agents"
    if agents_root.is_dir():
        agents_skill = (agents_root / "skills" / _SKILL_NAME).resolve()
        if agents_skill not in seen:
            seen.add(agents_skill)
            targets.append(("agents", agents_skill))

    fallback = False
    if not targets:
        fallback = True
        fallback_path = default_skill_dir("agents")
        assert fallback_path is not None
        targets.append(("agents", fallback_path))

    results = [install_skill(path, client=name) for name, path in targets]
    return {
        "client": "auto",
        "detected": detected,
        "fallback": fallback,
        "skills": results,
    }


def configure_client(
    client: str,
    entry: dict,
    *,
    config_path: Path | None = None,
    profile: str = "desktop",
    project_dir: Path | None = None,
    install_skill_files: bool = True,
    skill_dir: Path | None = None,
) -> dict:
    """Configure one MCP harness or auto-detect and configure all installed harnesses."""
    if client == "auto":
        if config_path is not None:
            raise ValueError("Do not combine --client auto with --config-path; select a specific client.")
        detected = detect_clients(profile=profile)
        fallback = False
        targets = list(detected)
        if not targets:
            fallback = True
            targets = ["codex"]
        configured = []
        for target in targets:
            cfg_path = default_config_path(target, profile=profile, project_dir=project_dir)
            item = configure(cfg_path, entry, client=target)
            if install_skill_files:
                item["skill"] = install_skill(skill_dir, client=target, project_dir=project_dir)
            configured.append(item)
        return {
            "client": "auto",
            "detected": detected,
            "fallback": fallback,
            "configured": configured,
        }

    path = config_path if config_path is not None else default_config_path(client, profile=profile, project_dir=project_dir)
    report = configure(path, entry, client=client)
    if install_skill_files:
        report["skill"] = install_skill(
            skill_dir,
            client=client,
            config_path=config_path,
            project_dir=project_dir,
        )
    return report
