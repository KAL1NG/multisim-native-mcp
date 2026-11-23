# Multisim Native MCP

[English](README.md) · 简体中文

Multisim Native MCP 将 AI 助手连接到 Windows 上的 NI Multisim。可搭建和修改原理图、运行原生仿真，并将设计保存为可在 Multisim 中继续编辑的 `.ms14` 文件。

## v0.5.4 更新

- **自动配置客户端。** Windows 安装器可检测已安装的 MCP 客户端、注册服务，并同步内置的 Multisim 技能。
- **内置技能和示例。** 提供常用器件引脚与参数速查，以及分压、RC 滤波和实时显示读数的工作流模板。客户端也可以通过 MCP 资源读取技能文档。
- **信号解析与网络命名。** 波形工作流在拓扑刷新后重新匹配元件 ID，设置导线网络名时会检查跨图纸命名冲突。

[发行下载](https://github.com/y-wi/multisim-native-mcp/releases/tag/v0.5.4) · [更新日志](CHANGELOG.md)

## 安装（一条命令自动识别 Harness 并安装 Skill）

| 项目 | 要求 |
| --- | --- |
| Windows | Windows 10 或 11 |
| NI Multisim | 14.3，32 位 |
| Python | CPython 3.12，32 位，由 `install.ps1` 自动安装 |
| MCP 通信方式 | STDIO |

在 PowerShell 中下载并运行安装脚本。默认使用 `-Client auto`：自动安装 32 位运行时、执行 `doctor --connect` 验证、检测本机已安装的 AI Harness、注册 `multisim_native` 并自动安装/更新内置的 `multisim-native` Skill：

```powershell
$installer = Join-Path $env:TEMP 'multisim-native-install.ps1'
Invoke-WebRequest 'https://github.com/y-wi/multisim-native-mcp/releases/download/v0.5.4/install.ps1' -OutFile $installer
& $installer
```

在本地源码仓库目录直接运行 `.\install.ps1` 即可从本地安装或升级。

### 支持的 Harness 与安装参数

如需指定单个或多个客户端（支持逗号分隔，如 `-Client antigravity,claude-code`），传入 `-Client` 即可：

| Harness / 选项 | 安装参数 | 默认 MCP 配置路径 | 默认 Agent Skill 路径 |
| --- | --- | --- | --- |
| 自动检测全部已装客户端（默认） | `-Client auto` | 自动配置下方已检测项（均未检测到时回退 `codex`） | 同步写入各已检测客户端的 Skill 目录 |
| Antigravity | `-Client antigravity` | `~/.gemini/config/mcp_config.json`（兼容旧路径） | `~/.gemini/config/skills/multisim-native` |
| OpenAI Codex | `-Client codex` | `~/.codex/config.toml`（支持 `$CODEX_HOME`） | `~/.codex/skills/multisim-native` |
| Claude Code | `-Client claude-code` | `~/.claude.json` | `~/.claude/skills/multisim-native` |
| Claude Desktop | `-Client claude-desktop` | `%APPDATA%\Claude\claude_desktop_config.json` | 通过 MCP Resource（`multisim://skill/SKILL.md`）提供 |
| Cursor | `-Client cursor` | `~/.cursor/mcp.json` | `~/.cursor/skills/multisim-native` |
| Windsurf | `-Client windsurf` | `~/.codeium/windsurf/mcp_config.json` | `~/.codeium/windsurf/skills/multisim-native` |
| Gemini CLI | `-Client gemini-cli` | `~/.gemini/settings.json` | `~/.gemini/skills/multisim-native` |
| VS Code（原生 MCP） | `-Client vscode` | `%APPDATA%\Code\User\mcp.json`（`servers` 键） | `~/.copilot/skills/multisim-native` |
| GitHub Copilot CLI | `-Client copilot` | `~/.copilot/mcp-config.json` | `~/.copilot/skills/multisim-native` |
| OpenCode | `-Client opencode` | `~/.config/opencode/opencode.json` 或 `%APPDATA%\opencode\opencode.json`（`mcp` 键） | `~/.config/opencode/skills/multisim-native` |
| DeepSeek Harness | `-Client dsh -Profile desktop` | `~/.dsh/profiles/<profile>/cordis.patch.yml` | 可通过 `-SkillDir` 指定 |
| 跨工具项目级标准 | `-Client project -ProjectDir <dir>` | `<dir>\.mcp.json` | `<dir>\.agents\skills\multisim-native` |
| 标准 JSON MCP 客户端 | `-Client json -ConfigPath <path>` | `<path>`（`mcpServers` 键） | 可通过 `-SkillDir` 指定 |
| 仅输出配置不改文件 | `-Client none` | 打印到标准输出 | 可通过 `-SkillDir` 指定 |

常用附加开关：`-SkipSkill`（跳过 Skill 安装）、`-SkillDir <dir>`（自定义 Skill 目录）、`-MultisimPath <dir>`（自定义 Multisim 安装目录）、`-Force`（强制重装同版本）、`-SkipDoctor`（跳过连接校验）。

### 让用户的 Agent 自动完成配置

任何具备终端执行能力的 Agent 都可以直接调用 CLI 完成检测与配置：

```powershell
# 查看本机已检测到的 Harness 及其配置/Skill 路径
multisim-native-mcp clients

# 自动配置所有已检测到的 Harness 并同步 Skill
multisim-native-mcp configure --client auto

# 仅同步内置 Skill（支持通用的 ~/.agents/skills 标准目录）
multisim-native-mcp install-skill --client auto
multisim-native-mcp install-skill --client agents

# 导出任意格式配置片段（json / codex / dsh / vscode / opencode）
multisim-native-mcp config --format json

# 清理旧版本安装环境与过期会话缓存
multisim-native-mcp cleanup
```

配置完成后重启客户端或在 Antigravity 中重载 MCP 服务即可生效，服务名为 `multisim_native`。

## 通用 Agent 技能与 MCP Resource 兜底

`multisim-native` 遵循开放的 [Agent Skills (`SKILL.md`) 规范](https://agentskills.io/)，且已直接打包进 wheel，**无需额外下载独立 zip**，安装和升级始终与 MCP 版本保持一致：

- [SKILL.md](skills/multisim-native/SKILL.md) — 工作流优先策略与 Multisim 避坑要点
- [references/editing.md](skills/multisim-native/references/editing.md) — Multisim 14.3 实机核对的 22 种常用器件引脚/命名参数/跨距速查表
- [references/workflows.md](skills/multisim-native/references/workflows.md) 与 [references/analysis.md](skills/multisim-native/references/analysis.md)
- `skills/multisim-native/assets/` 内置可直接改写的分压电路、RC 低通滤波（AC/Bode）、交互式数码管/LED 模板

对于不支持本地 `SKILL.md` 目录的客户端（如 Claude Desktop 或自定义 MCP 宿主），服务端同时通过标准 MCP Resource 暴露完整文档（`multisim://skill/SKILL.md`、`multisim://skill/references/editing.md`、`multisim://skill/references/workflows.md`、`multisim://skill/references/analysis.md`），确保跨 Harness 开箱即用。

## 通过助手操作 Multisim

> 用 10 V 电源和两个 1 kΩ 电阻搭建分压电路。将电源从 0 V 扫到 10 V，把中点电压导出为 CSV，并保存为 `divider.ms14`。

> 打开我的放大器电路，运行交流分析，将输出相对输入的伯德图导出为 PNG。

> 启动计数器的交互仿真，在十六进制数码管显示 A 时导出一张原理图，并告诉我哪些 LED 点亮了。

使用 `native_create_circuit` 和完整的输出路径创建电路，或使用 `native_open_circuit` 打开已有设计。修改后通过 `native_save_source` 保存。[Python 分压电路示例](examples/voltage_divider.py)

使用 `native_run_workflow` 串联原理图编辑、图纸切换、仿真、验收和导出。通过 `native_workflow_status` 查询进度，通过 `native_control_workflow` 取消或续跑。[工作流指南](docs/workflows.md)

## 文档

- [原理图编辑、连线与导出](docs/schematic.md)
- [仿真设置与持久保存](docs/persistence.md)
- [测量、扫描与报告](docs/experiments.md)
- [MCP 工具参考](docs/tools.md)
- [GitHub Issues](https://github.com/y-wi/multisim-native-mcp/issues)

[MIT 许可证](LICENSE)
