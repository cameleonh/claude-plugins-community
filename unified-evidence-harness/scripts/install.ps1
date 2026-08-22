param([ValidateSet('all','codex','antigravity','zcode')][string]$Platform='all')
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$targets = @{
  codex = 'C:\Users\hh\.agents\plugins\plugins\unified-evidence-harness'
  antigravity = 'C:\Users\hh\.gemini\config\plugins\unified-evidence-harness'
  zcode = 'C:\Users\hh\.zcode\plugin-workspace\unified-evidence-harness'
}
$selected = if($Platform -eq 'all'){@('codex','antigravity','zcode')}else{@($Platform)}
foreach($name in $selected){
  $target = $targets[$name]
  New-Item -ItemType Directory -Force -Path $target | Out-Null
  Copy-Item -Recurse -Force -Path (Join-Path $repo "adapters\$name\*") -Destination $target
  $scriptDir = if($name -eq 'zcode'){Join-Path $target 'hooks'}else{Join-Path $target 'scripts'}
  New-Item -ItemType Directory -Force -Path $scriptDir | Out-Null
  Copy-Item -Force -LiteralPath (Join-Path $repo 'core\evidence_core.py'),(Join-Path $repo 'core\hook_adapter.py'),(Join-Path $repo 'core\scholar_bridge.py') -Destination $scriptDir
  python (Join-Path $repo 'scripts\build_hashes.py') --root $target
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
