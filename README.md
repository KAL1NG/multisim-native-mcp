# Multisim Native MCP

English · [简体中文](README.zh-CN.md)

Multisim Native MCP connects an AI assistant to NI Multisim on Windows. Build and edit schematics, run native simulations, and save designs as editable `.ms14` files.

## What's new in v0.5.3

- **Universal multi-harness install & bundled Agent Skill.** One command installs the 32-bit runtime, verifies the MCP STDIO handshake, registers the server, and automatically syncs the bundled `multisim-native` skill (`SKILL.md` + 22-part cheat sheet + workflow templates) across Antigravity, Codex, Claude Code, Cursor, Windsurf, Gemini CLI, VS Code / GitHub Copilot, OpenCode, DeepSeek Harness, and portable project setups (`.mcp.json` + `.agents/skills/`). The MCP server also exposes the skill docs directly over standard MCP resources (`multisim://skill/SKILL.md`) for harnesses without local skill folders.
- **DC sweeps and signal tracing.** Sweep an independent voltage or current source, export RAW/CSV data, and trace electrical nets from component pins to waveform vectors.
- **Waveform measurements and plots.** Measure transient settling time and AC response. Export SVG or PNG waveform and Bode plots, with overlays for traces that share units.
- **Live circuit indicators.** Read hexadecimal displays, LEDs and digital probes during interactive simulation. Capture a schematic frame when a display shows a selected digit from `0` to `F`.
- **Schematic editing.** Filter the library by manufacturer or simulation model, set parameters by name, fit drawings to their sheets, and route wires around components.

[Release downloads](https://github.com/y-wi/multisim-native-mcp/releases/tag/v0.5.3) · [Changelog](CHANGELOG.md)

## Install (one command, auto-detects harnesses + installs skill)

| Component | Requirement |
| --- | --- |
| Windows | Windows 10 or 11 |
| NI Multisim | 14.3, 32-bit |
| Python | CPython 3.12, 32-bit, installed automatically by `install.ps1` |
| MCP transport | STDIO |

Run the installer in PowerShell. By default (`-Client auto`), it installs the runtime, verifies `doctor --connect`, detects all installed AI harnesses on this machine, registers `multisim_native`, and installs/updates the bundled `multisim-native` Agent Skill automatically:

```powershell
$installer = Join-Path $env:TEMP 'multisim-native-install.ps1'
Invoke-WebRequest 'https://github.com/y-wi/multisim-native-mcp/releases/download/v0.5.3/install.ps1' -OutFile $installer
& $installer
```

From a local source checkout, simply run `.\install.ps1`. Re-run the same script to update or sync a new harness.

### Supported harnesses & installer options

Pass `-Client` explicitly (single harness or comma-separated list such as `-Client antigravity,claude-code`) when you want to target specific harnesses:

| Harness / option | Installer argument | Default MCP config path | Default Agent Skill path |
| --- | --- | --- | --- |
| Auto-detect installed harnesses (default) | `-Client auto` | All detected below (falls back to `codex`) | Matching skill dir for each detected harness |
| Antigravity | `-Client antigravity` | `~/.gemini/config/mcp_config.json` (legacy fallback) | `~/.gemini/config/skills/multisim-native` |
| OpenAI Codex | `-Client codex` | `~/.codex/config.toml` (`$CODEX_HOME`) | `~/.codex/skills/multisim-native` |
| Claude Code | `-Client claude-code` | `~/.claude.json` | `~/.claude/skills/multisim-native` |
| Claude Desktop | `-Client claude-desktop` | `%APPDATA%\Claude\claude_desktop_config.json` | Uses MCP resources (`multisim://skill/SKILL.md`) |
| Cursor | `-Client cursor` | `~/.cursor/mcp.json` | `~/.cursor/skills/multisim-native` |
| Windsurf | `-Client windsurf` | `~/.codeium/windsurf/mcp_config.json` | `~/.codeium/windsurf/skills/multisim-native` |
| Gemini CLI | `-Client gemini-cli` | `~/.gemini/settings.json` | `~/.gemini/skills/multisim-native` |
| VS Code (native MCP) | `-Client vscode` | `%APPDATA%\Code\User\mcp.json` (`servers`) | `~/.copilot/skills/multisim-native` |
| GitHub Copilot CLI | `-Client copilot` | `~/.copilot/mcp-config.json` | `~/.copilot/skills/multisim-native` |
| OpenCode | `-Client opencode` | `~/.config/opencode/opencode.json` or `%APPDATA%\opencode\opencode.json` (`mcp`) | `~/.config/opencode/skills/multisim-native` |
| DeepSeek Harness | `-Client dsh -Profile desktop` | `~/.dsh/profiles/<profile>/cordis.patch.yml` | Optional via `-SkillDir` |
| Portable workspace setup | `-Client project -ProjectDir <dir>` | `<dir>\.mcp.json` | `<dir>\.agents\skills\multisim-native` |
| Standard JSON MCP client | `-Client json -ConfigPath <path>` | `<path>` (`mcpServers`) | Optional via `-SkillDir` |
| Print config without modifying files | `-Client none` | Printed to stdout | Optional via `-SkillDir` |

Additional switches: `-SkipSkill` (MCP only), `-SkillDir <dir>` (custom skill root), `-MultisimPath <dir>` (custom Multisim folder), `-Force` (reinstall same version), `-SkipDoctor` (skip connection test).

### Let your AI agent configure itself

Any terminal-capable AI agent can inspect or configure your harnesses directly via the installed CLI:

```powershell
# Inspect detected harnesses and paths
multisim-native-mcp clients

# Configure MCP + sync bundled skill for one or all detected harnesses
multisim-native-mcp configure --client auto

# Sync only the bundled skill (including cross-agent ~/.agents/skills)
multisim-native-mcp install-skill --client auto
multisim-native-mcp install-skill --client agents

# Print config snippet for manual or custom harnesses (json, codex, dsh, vscode, opencode)
multisim-native-mcp config --format json

# Clean up old installed environments and expired session caches
multisim-native-mcp cleanup
```

Reload MCP servers (or restart your harness) after configuration. The server appears as `multisim_native`.

## Universal Agent Skill & MCP Resources

The `multisim-native` skill follows the open [Agent Skills (`SKILL.md`) specification](https://agentskills.io/) and is bundled directly inside the package wheel—no separate download is required. It includes:

- [SKILL.md](skills/multisim-native/SKILL.md) — workflow-first guidance and native Multisim pitfalls
- [references/editing.md](skills/multisim-native/references/editing.md) — verified Multisim 14.3 22-part pin/parameter/spacing cheat sheet
- [references/workflows.md](skills/multisim-native/references/workflows.md) & [references/analysis.md](skills/multisim-native/references/analysis.md)
- Ready-to-adapt templates in `skills/multisim-native/assets/` (voltage divider, RC AC filter, interactive indicators)

For harnesses that do not read local `SKILL.md` directories (such as Claude Desktop or custom MCP hosts), the server also exposes the same guides as MCP resources (`multisim://skill/SKILL.md`, `multisim://skill/references/editing.md`, `multisim://skill/references/workflows.md`, `multisim://skill/references/analysis.md`).

## Use Multisim from your assistant

> Create a 10 V divider with two 1 kΩ resistors. Sweep the supply from 0 to 10 V, export the midpoint voltage as CSV, and save the circuit as `divider.ms14`.

> Open my amplifier circuit, run an AC analysis, and export a PNG Bode plot of the output relative to the input.

> Start interactive simulation on my counter circuit. Capture a schematic image when the hexadecimal display shows A, and report which LEDs are lit.

Use `native_create_circuit` with a full output path to create a design, or `native_open_circuit` with the source path to open an existing design. Save changes with `native_save_source`. [Python voltage-divider example](examples/voltage_divider.py)

For multi-step tasks, `native_run_workflow` combines schematic edits, sheet selection, analysis, acceptance criteria and exports. Use `native_workflow_status` to check progress and `native_control_workflow` to cancel or resume. [Workflow guide](docs/workflows.md)

## Documentation

- [Schematic editing, wiring and export](docs/schematic.md)
- [Simulation settings and persistence](docs/persistence.md)
- [Measurements, sweeps and reports](docs/experiments.md)
- [MCP tool reference](docs/tools.md)
- [GitHub Issues](https://github.com/y-wi/multisim-native-mcp/issues)

[MIT License](LICENSE)
