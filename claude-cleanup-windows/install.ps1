param([ValidateSet('Claude', 'Codex')][string]$Target = 'Codex')
$ErrorActionPreference = 'Stop'
$base = if ($Target -eq 'Claude') { Join-Path $env:USERPROFILE '.claude\skills' } else {
    if ($env:CODEX_HOME) { Join-Path $env:CODEX_HOME 'skills' } else { Join-Path $env:USERPROFILE '.codex\skills' }
}
$destination = Join-Path $base 'claude-cleanup-windows'
if (Test-Path -LiteralPath $destination) { throw "Already exists; refusing overwrite: $destination" }
New-Item -ItemType Directory -Path $destination -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'SKILL.md') -Destination $destination
New-Item -ItemType Directory -Path (Join-Path $destination 'scripts') | Out-Null
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'scripts\claude_cleanup.py') -Destination (Join-Path $destination 'scripts')
Write-Host "Installed: $destination"
Write-Host 'Open a new chat to load the skill. Cleanup was NOT executed.'
