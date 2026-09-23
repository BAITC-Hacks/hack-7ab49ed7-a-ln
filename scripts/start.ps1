$ErrorActionPreference = 'Stop'
if (-not [Console]::IsOutputRedirected) { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 }

$Root = Split-Path -Parent $PSScriptRoot
$AppDir = Join-Path $Root 'app'
$ResultsDir = Join-Path $Root 'results'
$FirstPort = 8080
$LastPort = 8099
$Exports = @('nodes_roles', 'clusters', 'top_nodes', 'features', 'resilience', 'data_requests', 'run_report')
# Exit code 2 tells start-windows.bat that the user has already read the error, so it does not pause again.
$HandledFailure = 2

function Write-Step([string]$Text) {
    Write-Host ''
    Write-Host "==> $Text" -ForegroundColor Cyan
}

function Exit-WithError([string]$Message, [string]$Hint) {
    Write-Host ''
    Write-Host "[Ошибка] $Message" -ForegroundColor Red
    if ($Hint) { Write-Host $Hint }
    [void](Read-Host 'Нажмите Enter, чтобы закрыть окно')
    exit $HandledFailure
}

function Invoke-Quietly([scriptblock]$Command) {
    # Windows PowerShell turns redirected stderr of native tools into errors; only the exit code matters here.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { & $Command *> $null } finally { $ErrorActionPreference = $previous }
    return ($LASTEXITCODE -eq 0)
}

function Wait-Until([int]$Seconds, [scriptblock]$Condition) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        if (& $Condition) { return $true }
        Start-Sleep -Seconds 2
    }
    return $false
}

function Test-DockerReady { Invoke-Quietly { docker info } }

function Add-DockerToPath {
    # Docker Desktop puts its CLI on PATH only for sessions started after the installation.
    if (-not $env:ProgramFiles) { return }
    $bin = Join-Path $env:ProgramFiles 'Docker\Docker\resources\bin'
    if ((Test-Path $bin) -and -not (($env:Path -split ';') -contains $bin)) { $env:Path = "$env:Path;$bin" }
}

function Initialize-Docker {
    Write-Step 'Проверяю Docker'
    Add-DockerToPath
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Exit-WithError 'Docker не найден.' 'Установите Docker Desktop: https://www.docker.com/products/docker-desktop/ — и запустите этот файл снова.'
    }
    if (-not (Test-DockerReady)) {
        $desktop = if ($env:ProgramFiles) { Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe' } else { '' }
        if (-not ($desktop -and (Test-Path $desktop))) {
            Exit-WithError 'Docker установлен, но не запущен.' 'Запустите Docker Desktop и запустите этот файл снова.'
        }
        Write-Host 'Запускаю Docker Desktop и жду его готовности (до 3 минут)...'
        Start-Process $desktop
        if (-not (Wait-Until 180 { Test-DockerReady })) {
            Exit-WithError 'Docker Desktop не запустился за 3 минуты.' 'Дождитесь запуска Docker Desktop и запустите этот файл снова.'
        }
    }
    if (-not (Invoke-Quietly { docker compose version })) {
        Exit-WithError 'Не найден Docker Compose v2 (команда «docker compose»).' 'Обновите Docker Desktop и запустите этот файл снова.'
    }
}

function Test-PortInUse([int]$Port) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $attempt = $client.BeginConnect('127.0.0.1', $Port, $null, $null)
        return ($attempt.AsyncWaitHandle.WaitOne(500) -and $client.Connected)
    } finally {
        $client.Close()
    }
}

function Get-PublishedPort {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { $mapping = docker compose port frontend 8080 2> $null } finally { $ErrorActionPreference = $previous }
    if ($LASTEXITCODE -ne 0 -or -not $mapping) { return $null }
    return [int](($mapping | Select-Object -First 1) -replace '^.*:', '')
}

function Select-Port {
    $running = Get-PublishedPort
    if ($running) {
        Write-Host "Приложение уже запущено — использую порт $running."
        return $running
    }
    for ($port = $FirstPort; $port -le $LastPort; $port++) {
        if (-not (Test-PortInUse $port)) { return $port }
    }
    Exit-WithError "Порты $FirstPort–$LastPort заняты другими программами." "Освободите порт $FirstPort и запустите этот файл снова."
}

function Test-TransientWebError($Exception) {
    return ($Exception -is [System.Net.WebException]) -or
        ($Exception.GetType().Name -in @('HttpRequestException', 'HttpResponseException', 'TaskCanceledException'))
}

function Invoke-Api([string]$Path, [string]$Method = 'Get') {
    try {
        return Invoke-RestMethod -Uri ($script:Base + $Path) -Method $Method -TimeoutSec 30
    } catch {
        if (Test-TransientWebError $_.Exception) { return $null }
        throw
    }
}

function Find-DemoRun {
    $runs = Invoke-Api '/api/v1/runs?limit=200'
    if (-not $runs) { return $null }
    foreach ($status in @('succeeded', 'running', 'queued')) {
        $run = $runs.items | Where-Object { $_.source -eq 'demo' -and $_.status -eq $status } | Select-Object -First 1
        if ($run) { return $run.id }
    }
    return $null
}

function Wait-Run([string]$RunId) {
    $deadline = (Get-Date).AddMinutes(15)
    $shown = ''
    while ((Get-Date) -lt $deadline) {
        $run = Invoke-Api "/api/v1/runs/$RunId"
        if ($run) {
            if ($run.status -eq 'succeeded') { return }
            if ($run.status -in @('failed', 'cancelled')) {
                $reason = if ($run.error) { $run.error.message } else { '' }
                Exit-WithError "Анализ завершился со статусом «$($run.status)»." $reason
            }
            if ($run.stage_label -and $run.stage_label -ne $shown) {
                Write-Host "   $($run.stage_label)"
                $shown = $run.stage_label
            }
        }
        Start-Sleep -Seconds 2
    }
    Exit-WithError 'Анализ не завершился за 15 минут.' 'Журнал сервиса: docker compose logs backend (в папке app).'
}

function Get-DemoRun {
    Write-Step 'Анализ данных кейса: 2 248 клиентов, 4 840 переводов за июль 2026'
    $runId = Find-DemoRun
    if (-not $runId) {
        $created = Invoke-Api '/api/v1/runs/demo' 'Post'
        if ($created) { $runId = $created.id }
    }
    if (-not $runId) {
        Exit-WithError 'Не удалось найти или создать прогон на данных кейса.' 'Журнал сервиса: docker compose logs backend (в папке app).'
    }
    Wait-Run $runId
    return $runId
}

function Save-Export([string]$RunId) {
    New-Item -ItemType Directory -Force -Path $ResultsDir | Out-Null
    foreach ($name in $Exports) {
        $file = if ($name -eq 'run_report') { "$name.md" } else { "$name.csv" }
        $target = Join-Path $ResultsDir $file
        Invoke-WebRequest -Uri "$script:Base/api/v1/runs/$RunId/exports/$name" -OutFile $target -UseBasicParsing -TimeoutSec 120
    }
}

Set-Location $AppDir
Initialize-Docker
if (-not (Test-Path '.env')) { Copy-Item '.env.example' '.env' }
$Port = Select-Port
$env:MG_HTTP_PORT = "$Port"
$script:Base = "http://127.0.0.1:$Port"

Write-Step "Собираю и запускаю приложение на порту $Port (первый запуск — несколько минут: скачиваются образы и зависимости)"
docker compose up -d --build
if ($LASTEXITCODE -ne 0) {
    Exit-WithError 'Не удалось запустить контейнеры.' 'Проверьте интернет и свободное место на диске, затем запустите этот файл снова.'
}

Write-Step 'Жду готовности сервиса'
if (-not (Wait-Until 300 { Invoke-Api '/api/v1/ready' })) {
    Exit-WithError 'Сервис не ответил за 5 минут.' 'Журнал сервиса: docker compose logs (в папке app).'
}

$url = "http://localhost:$Port/"
$meta = Invoke-Api '/api/v1/meta'
if ($meta -and -not $meta.auth_required) {
    $runId = Get-DemoRun
    $url = "http://localhost:$Port/runs/$runId"
    try {
        Save-Export $runId
        Write-Host "Выгрузки сохранены в папку: $ResultsDir"
    } catch {
        if (-not (Test-TransientWebError $_.Exception)) { throw }
        Write-Host 'Не удалось сохранить выгрузки — они есть в интерфейсе (кнопка «↓ Экспорт»).'
    }
} else {
    Write-Host 'В app\.env задан MG_API_TOKEN — войдите в интерфейсе с этим токеном.'
}

Write-Step "Готово: $url"
Start-Process $url
[void](Read-Host 'Приложение работает. Нажмите Enter, чтобы остановить его (результаты сохранятся до следующего запуска)')
Write-Step 'Останавливаю приложение'
docker compose down
