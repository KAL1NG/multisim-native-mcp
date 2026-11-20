# Multisim Native MCP

English · [简体中文](README.zh-CN.md)

Multisim Native MCP connects an AI assistant to NI Multisim on Windows. Build and edit schematics, run native simulations, and save designs as editable `.ms14` files.

## What's new in v0.5.3

- **DC sweeps and signal tracing.** Sweep an independent voltage or current source, export RAW/CSV data, and trace electrical nets from component pins to waveform vectors.
- **Waveform measurements and plots.** Measure transient settling time and AC response. Export SVG or PNG waveform and Bode plots, with overlays for traces that share units.
- **Live circuit indicators.** Read hexadecimal displays, LEDs and digital probes during interactive simulation. Capture a schematic frame when a display shows a selected digit from `0` to `F`.
- **Schematic editing.** Filter the library by manufacturer or simulation model, set parameters by name, fit drawings to their sheets, and route wires around components.
- **Client setup.** Register the server with Codex, Antigravity, DeepSeek Harness or a standard JSON MCP client.

[Release downloads](https://github.com/y-wi/multisim-native-mcp/releases/tag/v0.5.3) · [Changelog](CHANGELOG.md)

## Install

| Component | Requirement |
| --- | --- |
| Windows | Windows 10 or 11 |
| NI Multisim | 14.3, 32-bit |
| Python | CPython 3.12, 32-bit, installed by the setup script |
| MCP transport | STDIO |

Download and run the Windows installer in PowerShell. It installs the server and registers it with Codex by default.

```powershell
$installer = Join-Path $env:TEMP 'multisim-native-install.ps1'
Invoke-WebRequest 'https://github.com/y-wi/multisim-native-mcp/releases/download/v0.5.3/install.ps1' -OutFile $installer
& $installer
```

Use the same installer for an existing installation. To select another client, run the installer with the corresponding options.

| Client or option | Installer arguments |
| --- | --- |
| Antigravity | `-Client antigravity` |
| DeepSeek Harness | `-Client dsh -Profile desktop` (also supports `web` and `tui`) |
| Standard JSON MCP client | `-Client json -ConfigPath <path>` |
| Print configuration for manual setup | `-Client none` |
| Custom Multisim location | `-MultisimPath <directory>` |
| Reinstall the same version | `-Force` |

Restart Codex or reload MCP servers in Antigravity. DeepSeek Harness reloads the selected profile automatically. The server appears as `multisim_native`.

The [release page](https://github.com/y-wi/multisim-native-mcp/releases/tag/v0.5.3) also provides a wheel, source distribution and SHA-256 checksums. From a source checkout, run `.\install.ps1`.

## Use Multisim from your assistant

> Create a 10 V divider with two 1 kΩ resistors. Sweep the supply from 0 to 10 V, export the midpoint voltage as CSV, and save the circuit as `divider.ms14`.

> Open my amplifier circuit, run an AC analysis, and export a PNG Bode plot of the output relative to the input.

> Start interactive simulation on my counter circuit. Capture a schematic image when the hexadecimal display shows A, and report which LEDs are lit.

Use `native_create_circuit` with a full output path to create a design, or `native_open_circuit` with the source path to open an existing design. Save changes with `native_save_source`. [Python voltage-divider example](examples/voltage_divider.py)

For multi-step tasks, `native_run_workflow` combines schematic edits, sheet selection, analysis, acceptance criteria and exports. Use `native_workflow_status` to check progress and `native_control_workflow` to cancel or resume. [Workflow guide](docs/workflows.md)

## Agent skill

The optional `multisim-native` skill gives compatible assistants tool guidance and example workflows. Install it for Codex as follows.

```powershell
$skillRoot = if ($env:CODEX_HOME) { Join-Path $env:CODEX_HOME 'skills' } else { Join-Path $env:USERPROFILE '.codex\skills' }
$skillArchive = Join-Path $env:TEMP 'multisim-native-skill-0.5.3.zip'
Invoke-WebRequest 'https://github.com/y-wi/multisim-native-mcp/releases/download/v0.5.3/multisim-native-skill-0.5.3.zip' -OutFile $skillArchive
Expand-Archive -LiteralPath $skillArchive -DestinationPath $skillRoot -Force
```

Restart Codex and invoke `$multisim-native` or describe the circuit task. Other skill-enabled clients can use the same `multisim-native` folder. [Skill reference](skills/multisim-native/SKILL.md)

## Documentation

- [Schematic editing, wiring and export](docs/schematic.md)
- [Simulation settings and persistence](docs/persistence.md)
- [Measurements, sweeps and reports](docs/experiments.md)
- [MCP tool reference](docs/tools.md)
- [GitHub Issues](https://github.com/y-wi/multisim-native-mcp/issues)

[MIT License](LICENSE)
