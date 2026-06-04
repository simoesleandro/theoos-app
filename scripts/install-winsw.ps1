# Instala os serviços ThéoOS (Web + Bot) com WinSW — executar como Administrador
# Uso: powershell -ExecutionPolicy Bypass -File scripts\install-winsw.ps1

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$WinswUrl = 'https://github.com/winsw/winsw/releases/download/v2.12.0/WinSW-x64.exe'

function Ensure-WinswExe($name) {
    $exe = Join-Path $Root "$name.exe"
    $xml = Join-Path $Root "$name.xml"
    if (-not (Test-Path $xml)) {
        throw "Arquivo nao encontrado: $xml"
    }
    if (-not (Test-Path $exe)) {
        Write-Host "Baixando WinSW para $name.exe ..."
        Invoke-WebRequest -Uri $WinswUrl -OutFile $exe -UseBasicParsing
    }
    return $exe
}

if (-not (Test-Path (Join-Path $Root 'logs'))) {
    New-Item -ItemType Directory -Path (Join-Path $Root 'logs') | Out-Null
}

if (-not (Test-Path (Join-Path $Root '.env'))) {
    Write-Warning "Arquivo .env nao encontrado. Copie .env.example para .env antes de iniciar os servicos."
}

$web = Ensure-WinswExe 'theoos-web'
$bot = Ensure-WinswExe 'theoos-bot'

Write-Host "Instalando servico Web..."
& $web uninstall 2>$null
& $web install
& $web start

Write-Host "Instalando servico Bot..."
& $bot uninstall 2>$null
& $bot install
& $bot start

Write-Host ""
Write-Host "Concluido. Verifique em services.msc:"
Write-Host "  - ThéoOS - Painel Web"
Write-Host "  - ThéoOS - Bot Telegram"
Write-Host ""
Write-Host "Logs em: $Root\logs"
Write-Host "Painel: http://127.0.0.1:5000"
