param([ValidateSet('all','codex','antigravity','zcode')][string]$Platform='all')
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$targets = @{
  codex = 'C:\Users\hh\.agents\plugins\plugins\unified-evidence-harness'
  antigravity = 'C:\Users\hh\.gemini\config\plugins\unified-evidence-harness'
  zcode = 'C:\Users\hh\.zcode\plugin-workspace\unified-evidence-harness'
}
$selected = if($Platform -eq 'all'){@('codex','antigravity','zcode')}else{@($Platform)}

$legacyRoot = 'C:\Users\hh\.agents\plugins\plugins\codex-' + ('evidence' + '-harness')
$legacyHooks = Join-Path $legacyRoot 'hooks\hooks.json'
if(Test-Path -LiteralPath $legacyHooks){
  $backup = "$legacyHooks.pre-v4.json"
  if(-not (Test-Path -LiteralPath $backup)){ Copy-Item -LiteralPath $legacyHooks -Destination $backup }
  $retired = [ordered]@{
    description = 'Legacy Codex gate retired; Unified v4 is the canonical gate.'
    hooks = [ordered]@{}
    policy = 'v4-canonical'
  }
  $retired | ConvertTo-Json -Depth 10 | Set-Content -Encoding utf8 -LiteralPath $legacyHooks
  Write-Output "codex-v3`tretired`t$legacyHooks"
}

$configPath = 'C:\Users\hh\.codex\config.toml'
$legacyPlugin = 'codex-' + ('evidence' + '-harness') + '@personal'
if(Test-Path -LiteralPath $configPath){
  $configText = Get-Content -Raw -LiteralPath $configPath
  $pluginPattern = '(?ms)(\[plugins\."' + [regex]::Escape($legacyPlugin) + '"\]\s*enabled\s*=\s*)true'
  $updatedConfig = [regex]::Replace($configText, $pluginPattern, '${1}false')
  if($updatedConfig -ne $configText){ Set-Content -Encoding utf8 -LiteralPath $configPath -Value $updatedConfig }
  Write-Output "codex-v3`tconfig-disabled`t$legacyPlugin"
}

foreach($name in $selected){
  $target = $targets[$name]
  New-Item -ItemType Directory -Force -Path $target | Out-Null
  Copy-Item -Recurse -Force -Path (Join-Path $repo "adapters\$name\*") -Destination $target
  $scriptDir = if($name -eq 'zcode'){Join-Path $target 'hooks'}else{Join-Path $target 'scripts'}
  New-Item -ItemType Directory -Force -Path $scriptDir | Out-Null
  Copy-Item -Force -LiteralPath (Join-Path $repo 'core\antigravity_transcript.py'),(Join-Path $repo 'core\evidence_core.py'),(Join-Path $repo 'core\hook_adapter.py'),(Join-Path $repo 'core\scholar_bridge.py') -Destination $scriptDir
  python (Join-Path $repo 'scripts\build_hashes.py') --root $target
  if($name -eq 'codex'){
    $cacheRoot = 'C:\Users\hh\.codex\plugins\cache\personal\unified-evidence-harness'
    if(Test-Path -LiteralPath $cacheRoot){
      Get-ChildItem -LiteralPath $cacheRoot -Directory | ForEach-Object {
        $dst = $_.FullName
        Copy-Item -Recurse -Force -Path (Join-Path $repo "adapters\codex\*") -Destination $dst
        New-Item -ItemType Directory -Force -Path (Join-Path $dst 'scripts') | Out-Null
        Copy-Item -Force -LiteralPath (Join-Path $repo 'core\antigravity_transcript.py'),(Join-Path $repo 'core\evidence_core.py'),(Join-Path $repo 'core\hook_adapter.py'),(Join-Path $repo 'core\scholar_bridge.py') -Destination (Join-Path $dst 'scripts')
        python (Join-Path $repo 'scripts\build_hashes.py') --root $dst
        Write-Output "codex-cache`t$dst"
      }
    }
  }
  if($name -eq 'zcode'){
    $configPath = 'C:\Users\hh\.zcode\cli\config.json'
    if(Test-Path -LiteralPath $configPath){
      $config = Get-Content -Raw -LiteralPath $configPath | ConvertFrom-Json
      $hookText = Get-Content -Raw -LiteralPath (Join-Path $target 'hooks\hooks.json')
      $hookText = $hookText.Replace('${ZCODE_PLUGIN_ROOT}', $target.Replace('\','\\'))
      $hookConfig = $hookText | ConvertFrom-Json
      $config.hooks.events = $hookConfig.hooks
      $config | ConvertTo-Json -Depth 30 | Set-Content -Encoding utf8 -LiteralPath $configPath
    }
  }
  Write-Output "$name`t$target"
}
