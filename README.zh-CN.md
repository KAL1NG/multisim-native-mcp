# Multisim Native MCP

[English](README.md) · 简体中文

Multisim Native MCP 将 AI 助手连接到 Windows 上的 NI Multisim。可搭建和修改原理图、运行原生仿真，并将设计保存为可在 Multisim 中继续编辑的 `.ms14` 文件。

## v0.5.3 更新

- **DC 扫描与信号追踪。** 扫描独立电压源或电流源，导出 RAW/CSV 数据，并从元件引脚查找电气网络和波形向量。
- **波形测量与绘图。** 测量瞬态稳定时间和交流响应，将波形图或伯德图导出为 SVG 或 PNG。单位相同的曲线可在同一坐标系叠加。
- **实时显示读数。** 在交互仿真中读取十六进制数码管、LED 和数字探针。可在数码管显示指定字符（`0` 至 `F`）时捕获原理图画面。
- **原理图编辑。** 按制造商或仿真模型筛选元件库，按名称设置元件参数，调整图纸以容纳电路，并规划绕开元件的走线。
- **客户端安装。** 支持在 Codex、Antigravity、DeepSeek Harness 和使用标准 JSON 配置的 MCP 客户端中注册服务。

[发行下载](https://github.com/y-wi/multisim-native-mcp/releases/tag/v0.5.3) · [更新日志](CHANGELOG.md)

## 安装

| 项目 | 要求 |
| --- | --- |
| Windows | Windows 10 或 11 |
| NI Multisim | 14.3，32 位 |
| Python | CPython 3.12，32 位，由安装脚本配置 |
| MCP 通信方式 | STDIO |

在 PowerShell 中下载并运行安装脚本。脚本默认安装服务并注册到 Codex。

```powershell
$installer = Join-Path $env:TEMP 'multisim-native-install.ps1'
Invoke-WebRequest 'https://github.com/y-wi/multisim-native-mcp/releases/download/v0.5.3/install.ps1' -OutFile $installer
& $installer
```

更新已有安装时可运行同一脚本。使用其他客户端时，添加对应的安装参数。

| 客户端或选项 | 安装参数 |
| --- | --- |
| Antigravity | `-Client antigravity` |
| DeepSeek Harness | `-Client dsh -Profile desktop`（也支持 `web` 和 `tui`） |
| 标准 JSON MCP 客户端 | `-Client json -ConfigPath <path>` |
| 输出配置以便手动安装 | `-Client none` |
| 自定义 Multisim 安装位置 | `-MultisimPath <directory>` |
| 重新安装同一版本 | `-Force` |

安装后重启 Codex，或在 Antigravity 中重新加载 MCP 服务。DeepSeek Harness 会自动重新加载所选配置。服务名称为 `multisim_native`。

[发行页面](https://github.com/y-wi/multisim-native-mcp/releases/tag/v0.5.3)同时提供 wheel、源码包和 SHA-256 校验文件。从源码安装可在仓库目录运行 `.\install.ps1`。

## 通过助手操作 Multisim

> 用 10 V 电源和两个 1 kΩ 电阻搭建分压电路。将电源从 0 V 扫到 10 V，把中点电压导出为 CSV，并保存为 `divider.ms14`。

> 打开我的放大器电路，运行交流分析，将输出相对输入的伯德图导出为 PNG。

> 启动计数器的交互仿真，在十六进制数码管显示 A 时导出一张原理图，并告诉我哪些 LED 点亮了。

使用 `native_create_circuit` 和完整的输出路径创建电路，或使用 `native_open_circuit` 打开已有设计。修改后通过 `native_save_source` 保存。[Python 分压电路示例](examples/voltage_divider.py)

使用 `native_run_workflow` 串联原理图编辑、图纸切换、仿真、验收和导出。通过 `native_workflow_status` 查询进度，通过 `native_control_workflow` 取消或续跑。[工作流指南](docs/workflows.md)

## Agent 技能

可选的 `multisim-native` 技能提供工具用法和工作流示例。在 Codex 中可用以下命令安装。

```powershell
$skillRoot = if ($env:CODEX_HOME) { Join-Path $env:CODEX_HOME 'skills' } else { Join-Path $env:USERPROFILE '.codex\skills' }
$skillArchive = Join-Path $env:TEMP 'multisim-native-skill-0.5.3.zip'
Invoke-WebRequest 'https://github.com/y-wi/multisim-native-mcp/releases/download/v0.5.3/multisim-native-skill-0.5.3.zip' -OutFile $skillArchive
Expand-Archive -LiteralPath $skillArchive -DestinationPath $skillRoot -Force
```

重启 Codex 后，可调用 `$multisim-native` 或直接描述电路任务。其他支持技能的客户端也可使用同一个 `multisim-native` 文件夹。[技能说明](skills/multisim-native/SKILL.md)

## 文档

- [原理图编辑、连线与导出](docs/schematic.md)
- [仿真设置与持久保存](docs/persistence.md)
- [测量、扫描与报告](docs/experiments.md)
- [MCP 工具参考](docs/tools.md)
- [GitHub Issues](https://github.com/y-wi/multisim-native-mcp/issues)

[MIT 许可证](LICENSE)
