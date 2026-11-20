[CmdletBinding()]
param(
    [string]$Version = '0.5.3',
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA 'MultisimNativeMCP'),
    [string]$Source,
    [ValidateSet('auto','codex','antigravity','claude-code','claude-desktop','cursor','windsurf','gemini-cli','vscode','copilot','opencode','dsh','project','json','none')]
    [string[]]$Client = @('auto'),
    [string]$Profile = 'desktop',
    [string]$ConfigPath,
    [string]$ProjectDir,
    [string]$SkillDir,
    [string]$MultisimPath,
    [switch]$SkipSkill,
    [switch]$Force,
    [switch]$SkipDoctor
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
} catch {
    # PowerShell 7+ manages TLS automatically.
}

function Invoke-DownloadWithRetry {
    param(
        [Parameter(Mandatory)][string]$Uri,
        [Parameter(Mandatory)][string]$OutFile,
        [int]$Retries = 3
    )
    $lastError = $null
    for ($attempt = 1; $attempt -le $Retries; $attempt++) {
        try {
            Invoke-WebRequest -Uri $Uri -OutFile $OutFile -UseBasicParsing -ErrorAction Stop
            return
        } catch {
            $lastError = $_
            if ($attempt -lt $Retries) {
                Start-Sleep -Seconds (2 * $attempt)
            }
        }
    }
    throw "Download failed after $Retries attempts ($Uri): $lastError"
}

$InstallRoot = [IO.Path]::GetFullPath($InstallRoot)
$toolsDirectory = Join-Path $InstallRoot 'tools'
$binDirectory = Join-Path $InstallRoot 'bin'
$launcher = Join-Path $binDirectory 'multisim-native-mcp.exe'
$pathArguments = @()
if ($MultisimPath) { $pathArguments = @('--multisim-path',$MultisimPath) }
$clientList = @($Client | ForEach-Object { $_ -split ',' } | ForEach-Object { $_.Trim() } | Where-Object { $_ })
if (-not $clientList.Count) { $clientList = @('auto') }
if ($clientList.Count -gt 1 -and ($clientList -contains 'auto' -or $clientList -contains 'none')) {
    throw 'Do not combine auto or none with other -Client values.'
}
if ($ConfigPath -and $clientList.Count -gt 1) {
    throw 'Specify a single -Client when passing -ConfigPath.'
}

$reuseInstallation = $false
$environmentRoot = $null
$tempDownloadDirectory = $null
if (-not $Force -and -not $Source -and -not ($PSScriptRoot -and (Test-Path (Join-Path $PSScriptRoot 'src\multisim_native_mcp\__init__.py'))) -and (Test-Path -LiteralPath $launcher)) {
    try {
        $existingVersion = & $launcher --version 2>$null
        if ($LASTEXITCODE -eq 0 -and $existingVersion.Trim() -eq $Version) {
            $health = & $launcher doctor @pathArguments 2>$null
            if ($LASTEXITCODE -eq 0) {
                $parsedHealth = $health | ConvertFrom-Json
                $reuseInstallation = ($parsedHealth.ready -eq $true -and ($SkipSkill -or $parsedHealth.skill_bundled -eq $true))
            }
        }
    } catch { $reuseInstallation = $false }
}

New-Item -ItemType Directory -Path $toolsDirectory,$binDirectory -Force | Out-Null
$previousToolDir = $env:UV_TOOL_DIR
$previousBinDir = $env:UV_TOOL_BIN_DIR
$previousInstallDir = $env:UV_INSTALL_DIR
$previousModifyPath = $env:UV_NO_MODIFY_PATH
try {
    if (-not $reuseInstallation) {
        $uvCommand = Get-Command uv -ErrorAction SilentlyContinue
        if ($uvCommand) { $uvExecutable = $uvCommand.Source }
        else {
            $env:UV_INSTALL_DIR = $toolsDirectory
            $env:UV_NO_MODIFY_PATH = '1'
            $bootstrapFile = Join-Path $toolsDirectory 'install-uv.ps1'
            Invoke-DownloadWithRetry -Uri 'https://astral.sh/uv/install.ps1' -OutFile $bootstrapFile
            & (Get-Command powershell.exe -ErrorAction Stop).Source -NoProfile -ExecutionPolicy Bypass -File $bootstrapFile
            if ($LASTEXITCODE -ne 0) { throw 'uv installation failed.' }
            $uvExecutable = Join-Path $toolsDirectory 'uv.exe'
        }
        $environmentRoot = Join-Path (Join-Path $toolsDirectory 'environments') ('install-' + [guid]::NewGuid().ToString('N'))
        $env:UV_TOOL_DIR = $environmentRoot
        $env:UV_TOOL_BIN_DIR = $binDirectory
        if (-not $Source) {
            if ($PSScriptRoot -and (Test-Path (Join-Path $PSScriptRoot 'src\multisim_native_mcp\__init__.py'))) {
                $Source = $PSScriptRoot
            } else {
                $tempDownloadDirectory = Join-Path $env:TEMP ('multisim-native-dl-' + [guid]::NewGuid().ToString('N'))
                New-Item -ItemType Directory -Path $tempDownloadDirectory -Force | Out-Null
                $wheelFile = Join-Path $tempDownloadDirectory "multisim_native_mcp-$Version-py3-none-any.whl"
                $wheelUrl = "https://github.com/y-wi/multisim-native-mcp/releases/download/v$Version/multisim_native_mcp-$Version-py3-none-any.whl"
                Invoke-DownloadWithRetry -Uri $wheelUrl -OutFile $wheelFile
                $Source = $wheelFile
            }
        }
        & $uvExecutable tool install --force --python cpython-3.12-windows-x86-none $Source
        if ($LASTEXITCODE -ne 0) { throw 'MCP package installation failed.' }
        if (-not (Test-Path -LiteralPath $launcher)) { throw 'MCP launcher was not created.' }
    }

    if (-not $SkipDoctor) {
        $doctorArguments = @('doctor','--connect') + $pathArguments
        & $launcher @doctorArguments
        if ($LASTEXITCODE -ne 0) { throw 'MCP runtime check failed. See the doctor report above.' }
    }

    $configuredClients = @()
    if ($clientList.Count -eq 1 -and $clientList[0] -eq 'none') {
        & $launcher config @pathArguments
        if (-not $SkipSkill -and $SkillDir) {
            & $launcher install-skill --skill-dir $SkillDir
            if ($LASTEXITCODE -ne 0) { throw 'Skill installation failed.' }
        }
    } else {
        foreach ($targetClient in $clientList) {
            $configArguments = @('configure','--client',$targetClient) + $pathArguments
            if ($targetClient -in @('dsh','auto')) { $configArguments += @('--profile',$Profile) }
            if ($ConfigPath) { $configArguments += @('--config-path',$ConfigPath) }
            if ($ProjectDir) { $configArguments += @('--project-dir',$ProjectDir) }
            if ($SkillDir) { $configArguments += @('--skill-dir',$SkillDir) }
            if ($SkipSkill) { $configArguments += '--skip-skill' }
            $rawReport = & $launcher @configArguments
            if ($LASTEXITCODE -ne 0) { throw "$targetClient configuration failed." }
            $rawReport | Write-Output
            try {
                $parsedReport = ($rawReport -join "`n") | ConvertFrom-Json
                if ($parsedReport.configured) {
                    $configuredClients += @($parsedReport.configured | ForEach-Object { $_.client })
                } elseif ($parsedReport.client) {
                    $configuredClients += $parsedReport.client
                }
            } catch {
                $configuredClients += $targetClient
            }
        }
    }

    $environmentsDirectory = Join-Path $toolsDirectory 'environments'
    if (Test-Path -LiteralPath $environmentsDirectory) {
        $oldEnvironments = Get-ChildItem -LiteralPath $environmentsDirectory -Directory -Filter 'install-*' |
            Sort-Object @{ Expression = { [bool]($environmentRoot -and $_.FullName -eq $environmentRoot) }; Descending = $true }, @{ Expression = { $_.LastWriteTimeUtc }; Descending = $true } |
            Select-Object -Skip 2
        foreach ($oldEnv in $oldEnvironments) {
            try {
                $probe = Join-Path $environmentsDirectory ('.pruning-' + [guid]::NewGuid().ToString('N'))
                [IO.Directory]::Move($oldEnv.FullName, $probe)
                Remove-Item -LiteralPath $probe -Recurse -Force -ErrorAction Stop
            } catch {
                # Ignore environments locked by an active running server.
            }
        }
    }

    Write-Host "Installed: $launcher"
    if ($configuredClients.Count) {
        $uniqueClients = @($configuredClients | Select-Object -Unique)
        Write-Host ("Configured clients: " + ($uniqueClients -join ', '))
        if ($uniqueClients -contains 'antigravity') { Write-Host 'Reload MCP servers in Antigravity to load Multisim Native MCP and the updated skill.' }
        if ($uniqueClients -contains 'codex') { Write-Host 'Restart Codex to load Multisim Native MCP and the multisim-native skill.' }
        if ($uniqueClients -contains 'dsh') { Write-Host "DSH profile '$Profile' reloads the MCP connection automatically." }
        if ($uniqueClients | Where-Object { $_ -notin @('antigravity','codex','dsh') }) {
            Write-Host 'Restart or reload your MCP client/harness to load Multisim Native MCP and the multisim-native skill.'
        }
    }
}
finally {
    if ($tempDownloadDirectory -and (Test-Path -LiteralPath $tempDownloadDirectory)) {
        Remove-Item -LiteralPath $tempDownloadDirectory -Recurse -Force -ErrorAction SilentlyContinue
    }
    $env:UV_TOOL_DIR = $previousToolDir
    $env:UV_TOOL_BIN_DIR = $previousBinDir
    $env:UV_INSTALL_DIR = $previousInstallDir
    $env:UV_NO_MODIFY_PATH = $previousModifyPath
}
