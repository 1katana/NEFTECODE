param(
    [string]$HostAddress = "127.0.0.1",
    [int]$Port = 8000
)

$WorkspaceRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $WorkspaceRoot
& ".\.venv\Scripts\python.exe" -m neftecode_integration.main --host $HostAddress --port $Port
