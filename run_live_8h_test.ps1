param(
    [string]$ProjectDir = "D:\AI\PM_api_claim",
    [string]$ConfigPath = "D:\AI\PM_api_claim\config.yaml",
    [int]$Runs = 8,
    [int]$IntervalSeconds = 3600
)

$ErrorActionPreference = "Stop"

Set-Location -Path $ProjectDir

$logsDir = Join-Path $ProjectDir "logs"
if (!(Test-Path $logsDir)) {
    New-Item -ItemType Directory -Path $logsDir | Out-Null
}

$summaryLog = Join-Path $logsDir "live_8h_summary.log"
$stopFlag = Join-Path $logsDir "STOP_LIVE_8H.flag"

function Write-LogLine([string]$line) {
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $full = "$timestamp $line"
    Write-Output $full
    Add-Content -Path $summaryLog -Value $full
}

if (!(Test-Path ".\.venv\Scripts\python.exe")) {
    throw "Python virtualenv not found: .\.venv\Scripts\python.exe"
}

if (!(Test-Path $ConfigPath)) {
    throw "Config file not found: $ConfigPath"
}

if (Test-Path ".\.env") {
    Get-Content ".\.env" | ForEach-Object {
        $line = $_.Trim()
        if ($line -eq "" -or $line.StartsWith("#")) { return }
        $parts = $line -split "=", 2
        if ($parts.Length -eq 2) {
            [System.Environment]::SetEnvironmentVariable(
                $parts[0].Trim(),
                $parts[1].Trim(),
                "Process"
            )
        }
    }
}

Write-LogLine "START live test loop runs=$Runs interval_seconds=$IntervalSeconds config=$ConfigPath"

for ($i = 1; $i -le $Runs; $i++) {
    if (Test-Path $stopFlag) {
        Write-LogLine "STOP flag detected, exiting before run=$i"
        break
    }

    $runStart = Get-Date
    $runTag = $runStart.ToString("yyyyMMdd_HHmmss")
    $runLog = Join-Path $logsDir ("live_run_{0}_{1}.log" -f $i, $runTag)

    Write-LogLine "RUN_START run=$i/$Runs run_log=$runLog"
    & ".\.venv\Scripts\python.exe" ".\main.py" --config $ConfigPath --mode live --log-level INFO 2>&1 | Tee-Object -FilePath $runLog -Append | Out-Host
    $exitCode = $LASTEXITCODE
    Write-LogLine "RUN_END run=$i/$Runs exit_code=$exitCode run_log=$runLog"
    if ($exitCode -ne 0) {
        Write-LogLine "ABORT non-zero exit code detected run=$i exit_code=$exitCode"
        break
    }

    if ($i -lt $Runs) {
        Write-LogLine "SLEEP seconds=$IntervalSeconds before next run"
        Start-Sleep -Seconds $IntervalSeconds
    }
}

Write-LogLine "END live test loop"
