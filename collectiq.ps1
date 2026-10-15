param([ValidateSet('start','verify','core','core-prepare','core-propose','core-replace','demo','state','sync','test','acceptance','isolation','agents','verify-agents','why','configure-cognee','configure-stripe')][string]$Command='start', [ValidateSet('A','B','C','all')][string]$Scenario='all', [string]$WorkflowId='')
$ErrorActionPreference = 'Stop'
$taskPython = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) { $taskPython = 'python' }
Set-Location -LiteralPath $PSScriptRoot
switch ($Command) {
    'start' { & $taskPython -m backend.server }
    'test' { & $taskPython -m unittest discover -s backend/tests -v }
    'acceptance' { & $taskPython -m backend.live_checks --phase acceptance }
    'isolation' { & $taskPython -m backend.live_checks --phase isolation }
    'agents' { & $taskPython -m backend.agent_cli run --scenario $Scenario }
    'verify-agents' { & $taskPython -m backend.agent_cli verify --output artifacts/task2-acceptance.json }
    'why' { & $taskPython -m backend.agent_cli why --workflow-id $WorkflowId --output artifacts/task2-explanation.json }
    'configure-cognee' { & $taskPython -m backend.credentials cognee }
    'configure-stripe' { & $taskPython -m backend.credentials stripe }
    default { & $taskPython -m backend.cli $Command }
}
exit $LASTEXITCODE
