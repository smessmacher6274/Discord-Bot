#!/usr/bin/env bash
# Restart by default; also supports start, stop, and status.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
action=${1:-restart}
case "$action" in
  start|stop|restart|status) ;;
  *) echo "Usage: bash bot.sh [start|stop|restart|status]" >&2; exit 2 ;;
esac

# Windows Python processes need Windows process management, including from WSL.
if [[ -f .venv/Scripts/python.exe ]]; then
  if command -v cygpath >/dev/null 2>&1; then
    BOT_SCRIPT_DIR=$(cygpath -w "$PWD")
  elif command -v wslpath >/dev/null 2>&1; then
    BOT_SCRIPT_DIR=$(wslpath -w "$PWD")
  else
    echo "Cannot convert the project path to a Windows path." >&2
    exit 1
  fi
  export BOT_SCRIPT_DIR BOT_SCRIPT_ACTION="$action"
  # Explicitly share these variables with Windows when running under WSL.
  export WSLENV="${WSLENV:+$WSLENV:}BOT_SCRIPT_DIR:BOT_SCRIPT_ACTION"
  powershell.exe -NoProfile -NonInteractive -Command - <<'POWERSHELL'
$ErrorActionPreference = 'Stop'
try {
    $root = $env:BOT_SCRIPT_DIR
    $action = $env:BOT_SCRIPT_ACTION
    $python = Join-Path $root '.venv\Scripts\python.exe'
    $main = Join-Path $root 'main.py'
    $pidFile = Join-Path $root 'bot.pid'
    $mutex = [System.Threading.Mutex]::new($false, 'Local\DiscordBot-' + [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($root)).Replace('\', '_'))
    if (-not $mutex.WaitOne(0)) { throw 'Another bot control command is running.' }
    try {
        $bots = @(Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'" | Where-Object {
            $_.CommandLine -and ($_.ExecutablePath -ieq $python) -and
            ($_.CommandLine.Contains($main) -or $_.CommandLine -match '(?:\s|\x22)main\.py(?:\s|\x22|$)')
        })
        if ($action -eq 'status') {
            if ($bots.Count) { Write-Output "Bot running (PID: $($bots.ProcessId -join ', '))." }
            else { Write-Output 'Bot is stopped.' }
        } elseif ($action -eq 'start' -and $bots.Count) {
            Write-Output "Bot already running (PID: $($bots.ProcessId -join ', '))."
        } else {
            foreach ($bot in $bots) {
                Stop-Process -Id $bot.ProcessId -Force
                Wait-Process -Id $bot.ProcessId -Timeout 15 -ErrorAction SilentlyContinue
            }
            Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
            if ($action -eq 'stop') { Write-Output 'Bot stopped.' }
            else {
                $stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
                $stdout = Join-Path $root "bot.$stamp.stdout.log"
                $stderr = Join-Path $root "bot.$stamp.stderr.log"
                $process = Start-Process -FilePath $python -ArgumentList @('-u', ('"' + $main + '"')) -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
                Set-Content -Path $pidFile -Value $process.Id
                Start-Sleep -Seconds 2
                $process.Refresh()
                if ($process.HasExited) { throw "Bot exited during startup. Check $stderr" }
                Write-Output "Bot started (PID: $($process.Id))."
                Write-Output "Logs: $stdout and $stderr"
            }
        }
    } finally { $mutex.ReleaseMutex(); $mutex.Dispose() }
} catch { [Console]::Error.WriteLine($_.Exception.Message); exit 1 }
POWERSHELL
  exit $?
fi

python="$PWD/.venv/bin/python"
if [[ ! -x "$python" ]]; then
  echo "Missing virtual environment. Create .venv and install requirements.txt first." >&2
  exit 1
fi
mkdir -p .tmp
exec 9>.tmp/bot-control.lock
flock -n 9 || { echo "Another bot control command is running." >&2; exit 1; }
pids=()
# Match both this project's working directory and the Python entry point.
for proc in /proc/[0-9]*; do
  [[ $(readlink "$proc/cwd" 2>/dev/null || true) == "$PWD" ]] || continue
  args=()
  mapfile -d '' -t args < "$proc/cmdline" 2>/dev/null || continue
  [[ ${args[0]##*/} == python* ]] || continue
  for arg in "${args[@]:1}"; do
    if [[ "$arg" == main.py || "$arg" == "$PWD/main.py" ]]; then
      pids+=("${proc##*/}")
      break
    fi
  done
done
if [[ "$action" == status ]]; then
  if ((${#pids[@]})); then echo "Bot running (PID: ${pids[*]})."; else echo "Bot is stopped."; fi
  exit 0
fi
if [[ "$action" == start ]] && ((${#pids[@]})); then
  echo "Bot already running (PID: ${pids[*]})."
  exit 0
fi
for pid in "${pids[@]}"; do
  kill -TERM "$pid" 2>/dev/null || true
  for ((attempt=0; attempt<50; attempt++)); do
    kill -0 "$pid" 2>/dev/null || break
    sleep 0.2
  done
  if kill -0 "$pid" 2>/dev/null; then kill -KILL "$pid"; fi
done
rm -f bot.pid
if [[ "$action" == stop ]]; then echo "Bot stopped."; exit 0; fi
stamp=$(date +%Y%m%d-%H%M%S)-$$
stdout="bot.$stamp.stdout.log"
stderr="bot.$stamp.stderr.log"
nohup "$python" -u "$PWD/main.py" >"$stdout" 2>"$stderr" </dev/null 9>&- &
pid=$!
echo "$pid" > bot.pid
sleep 2
if ! kill -0 "$pid" 2>/dev/null; then
  echo "Bot exited during startup. Check $stderr" >&2
  exit 1
fi
echo "Bot started (PID: $pid)."
echo "Logs: $stdout and $stderr"
