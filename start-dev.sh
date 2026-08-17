#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

ENV_FILE="${ENV_FILE:-$PROJECT_DIR/.env}"

API_APP="${API_APP:-api.main:app}"
API_HOST="${API_HOST:-127.0.0.1}"
API_PORT="${API_PORT:-8000}"

CELERY_APP="${CELERY_APP:-api.celery_app.celery_app}"
CELERY_LOGLEVEL="${CELERY_LOGLEVEL:-info}"
CELERY_CONCURRENCY="${CELERY_CONCURRENCY:-1}"
FLOWER_HOST="${FLOWER_HOST:-127.0.0.1}"
FLOWER_PORT="${FLOWER_PORT:-5555}"

FRONTEND_DIR="${FRONTEND_DIR:-frontend}"
FRONTEND_HOST="${FRONTEND_HOST:-127.0.0.1}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"

STOP_INFRA_ON_EXIT="${STOP_INFRA_ON_EXIT:-true}"

PIDS=()
CLEANED_UP=false
UV_CMD=()
NPM_FRONTEND_DIR=""
POWERSHELL_CMD=""
WINDOWS_PROJECT_DIR=""
RUN_ID="${RUN_ID:-$$-$RANDOM}"

info() {
    printf '\n\033[1;36m%s\033[0m\n' "$*"
}

error() {
    printf '\n\033[1;31mERROR: %s\033[0m\n' "$*" >&2
    exit 1
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || error "Command '$1' was not found."
}

to_bash_path() {
    local path="$1"

    if command -v wslpath >/dev/null 2>&1; then
        wslpath -u "$path" 2>/dev/null && return 0
    fi

    if command -v cygpath >/dev/null 2>&1; then
        cygpath -u "$path" 2>/dev/null && return 0
    fi

    printf '%s\n' "$path"
}

find_powershell() {
    local candidate

    for candidate in \
        powershell.exe \
        powershell \
        /mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe
    do
        if command -v "$candidate" >/dev/null 2>&1 || [[ -x "$candidate" ]]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done

    return 1
}

to_windows_path() {
    local path="$1"

    if command -v wslpath >/dev/null 2>&1; then
        wslpath -w "$path" 2>/dev/null && return 0
    fi

    if command -v cygpath >/dev/null 2>&1; then
        cygpath -w "$path" 2>/dev/null && return 0
    fi

    printf '%s\n' "$path"
}

resolve_uv() {
    local candidate powershell_command windows_uv bash_uv windows_home bash_home

    for candidate in uv uv.exe; do
        if command -v "$candidate" >/dev/null 2>&1; then
            UV_CMD=("$candidate")
            return 0
        fi
    done

    # Git Bash/WSL can have a different PATH from PowerShell. Ask PowerShell for
    # the exact Windows executable path, then convert it to a Bash path.
    powershell_command="$(find_powershell || true)"
    if [[ -n "$powershell_command" ]]; then
        windows_uv="$(
            "$powershell_command" -NoProfile -Command \
                '$command = Get-Command uv -ErrorAction SilentlyContinue; if ($command) { $command.Source }' \
                2>/dev/null | tr -d '\r' | head -n 1
        )"

        if [[ -n "$windows_uv" ]]; then
            bash_uv="$(to_bash_path "$windows_uv")"
            if [[ -f "$bash_uv" ]]; then
                UV_CMD=("$bash_uv")
                return 0
            fi
        fi

        windows_home="$(
            "$powershell_command" -NoProfile -Command \
                '[Environment]::GetFolderPath("UserProfile")' \
                2>/dev/null | tr -d '\r' | head -n 1
        )"

        if [[ -n "$windows_home" ]]; then
            bash_home="$(to_bash_path "$windows_home")"
            for candidate in \
                "$bash_home/.local/bin/uv.exe" \
                "$bash_home/.cargo/bin/uv.exe" \
                "$bash_home/AppData/Local/Microsoft/WinGet/Links/uv.exe"
            do
                if [[ -f "$candidate" ]]; then
                    UV_CMD=("$candidate")
                    return 0
                fi
            done
        fi
    fi

    # Final fallback for installations where uv is available as a Python module.
    for candidate in python python.exe py py.exe; do
        if command -v "$candidate" >/dev/null 2>&1 \
            && "$candidate" -m uv --version >/dev/null 2>&1; then
            UV_CMD=("$candidate" -m uv)
            return 0
        fi
    done

    error "uv was not found in Bash or Windows PowerShell. Install it in PowerShell with: winget install --id=astral-sh.uv -e"
}

resolve_npm_frontend_dir() {
    local frontend_dir npm_path

    frontend_dir="$PROJECT_DIR/$FRONTEND_DIR"
    npm_path="$(command -v npm)"

    # When this script is launched with `bash` from PowerShell, that Bash is
    # commonly WSL while npm comes from Windows. Passing /mnt/d/... directly to
    # Windows Node makes it look for D:\mnt\d\..., so convert only in that case.
    if [[ "$npm_path" == /mnt/[a-zA-Z]/* ]] \
        && command -v wslpath >/dev/null 2>&1; then
        NPM_FRONTEND_DIR="$(wslpath -w "$frontend_dir")"
        return 0
    fi

    # The equivalent case for Git Bash/MSYS (for example /c/Program Files/...).
    if [[ "$npm_path" == /[a-zA-Z]/* ]] \
        && command -v cygpath >/dev/null 2>&1; then
        NPM_FRONTEND_DIR="$(cygpath -w "$frontend_dir")"
        return 0
    fi

    # Native Linux/macOS npm expects the Bash path unchanged.
    NPM_FRONTEND_DIR="$frontend_dir"
}

load_env_file() {
    local line key value

    [[ -f "$ENV_FILE" ]] || error ".env file not found: $ENV_FILE"

    while IFS= read -r line || [[ -n "$line" ]]; do
        line="${line%$'\r'}"

        [[ "$line" =~ ^[[:space:]]*$ ]] && continue
        [[ "$line" =~ ^[[:space:]]*# ]] && continue

        line="${line#export }"
        [[ "$line" == *"="* ]] || continue

        key="${line%%=*}"
        value="${line#*=}"

        key="${key#"${key%%[![:space:]]*}"}"
        key="${key%"${key##*[![:space:]]}"}"
        value="${value#"${value%%[![:space:]]*}"}"
        value="${value%"${value##*[![:space:]]}"}"

        [[ "$key" =~ ^[a-zA-Z_][a-zA-Z0-9_]*$ ]] || continue

        if [[ ${#value} -ge 2 ]]; then
            if [[ "${value:0:1}" == '"' && "${value: -1}" == '"' ]]; then
                value="${value:1:${#value}-2}"
            elif [[ "${value:0:1}" == "'" && "${value: -1}" == "'" ]]; then
                value="${value:1:${#value}-2}"
            fi
        fi

        export "$key=$value"
        export WSLENV="${WSLENV:+$WSLENV:}$key"
    done < "$ENV_FILE"
}

stop_process_tree() {
    local pid="$1" child windows_pid

    if [[ "$OSTYPE" == msys* || "$OSTYPE" == cygwin* ]]; then
        read -r _ _ _ windows_pid _ < <(ps -p "$pid" -l | tail -n 1) || true
        if [[ -n "$windows_pid" ]]; then
            taskkill.exe //PID "$windows_pid" //T //F >/dev/null 2>&1 || true
        fi
    fi

    # Kill descendants first. This handles Uvicorn's reload child and the
    # npm -> node -> Vite chain on native Linux/macOS.
    while IFS= read -r child; do
        [[ -n "$child" ]] && stop_process_tree "$child"
    done < <(
        ps -eo pid=,ppid= 2>/dev/null \
            | awk -v parent="$pid" '$2 == parent { print $1 }'
    )

    # Services started through start_background have their own process group
    # whenever setsid is available. Fall back to the individual PID otherwise.
    kill -TERM -- "-$pid" >/dev/null 2>&1 \
        || kill -TERM "$pid" >/dev/null 2>&1 \
        || true
}

stop_windows_project_processes() {
    local ports

    [[ -n "$POWERSHELL_CMD" ]] || return 0
    [[ -n "$WINDOWS_PROJECT_DIR" ]] || return 0

    ports="${API_PORT},${FLOWER_PORT},${FRONTEND_PORT}"

    # uv.exe/npm.exe started from WSL are Windows processes. A Linux `kill`
    # only terminates their WSL launcher, so also find this project's Windows
    # service trees and terminate them from Windows itself. Matching is scoped
    # to this project path and the three local service ports.
    WSLENV="${WSLENV:+$WSLENV:}EDA_CLEANUP_PROJECT:EDA_CLEANUP_PORTS" \
    EDA_CLEANUP_PROJECT="$WINDOWS_PROJECT_DIR" \
    EDA_CLEANUP_PORTS="$ports" \
        "$POWERSHELL_CMD" -NoProfile -NonInteractive -Command '
            $project = $env:EDA_CLEANUP_PROJECT
            $ports = @(
                $env:EDA_CLEANUP_PORTS -split "," |
                    Where-Object { $_ -match "^\d+$" } |
                    ForEach-Object { [int]$_ }
            )

            if ([string]::IsNullOrWhiteSpace($project)) { exit 0 }

            $escapedProject = [regex]::Escape($project.TrimEnd("\\"))
            $servicePattern = "(?i)(uvicorn|celery|flower|vite|npm(?:\.cmd)?\s+.*run\s+dev)"
            $all = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)
            $selected = [System.Collections.Generic.HashSet[int]]::new()

            foreach ($process in $all) {
                $commandLine = [string]$process.CommandLine
                if (
                    $commandLine -match $escapedProject -and
                    $commandLine -match $servicePattern
                ) {
                    [void]$selected.Add([int]$process.ProcessId)
                }
            }

            foreach ($port in $ports) {
                $owners = @(
                    Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
                        Select-Object -ExpandProperty OwningProcess -Unique
                )
                foreach ($ownerPid in $owners) {
                    $owner = $all | Where-Object ProcessId -eq $ownerPid |
                        Select-Object -First 1
                    if (
                        $owner -and
                        ([string]$owner.CommandLine) -match $escapedProject
                    ) {
                        [void]$selected.Add([int]$ownerPid)
                    }
                }
            }

            do {
                $added = $false
                foreach ($process in $all) {
                    if (
                        $selected.Contains([int]$process.ParentProcessId) -and
                        -not $selected.Contains([int]$process.ProcessId)
                    ) {
                        [void]$selected.Add([int]$process.ProcessId)
                        $added = $true
                    }
                }
            } while ($added)

            $roots = @(
                $all | Where-Object {
                    $selected.Contains([int]$_.ProcessId) -and
                    -not $selected.Contains([int]$_.ParentProcessId)
                }
            )

            foreach ($root in $roots) {
                & taskkill.exe /PID $root.ProcessId /T /F *> $null
            }

            foreach ($processId in $selected) {
                Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
            }
        ' >/dev/null 2>&1 || true
}

start_background() {
    if command -v setsid >/dev/null 2>&1; then
        setsid "$@" &
    else
        "$@" &
    fi
    PIDS+=("$!")
}

cleanup() {
    local pid

    if [[ "$CLEANED_UP" == "true" ]]; then
        return
    fi
    CLEANED_UP=true

    trap - EXIT INT TERM
    info "Stopping local development processes..."

    for pid in "${PIDS[@]:-}"; do
        stop_process_tree "$pid"
    done

    stop_windows_project_processes

    for pid in "${PIDS[@]:-}"; do
        wait "$pid" >/dev/null 2>&1 || true
    done

    if [[ "${STOP_INFRA_ON_EXIT,,}" == "true" ]]; then
        info "Stopping Redis and Qdrant..."
        "${COMPOSE[@]}" stop redis qdrant || true
    fi
}

on_signal() {
    exit 130
}

trap cleanup EXIT
trap on_signal INT TERM

require_command docker
require_command npm
resolve_uv

docker compose version >/dev/null 2>&1 || error "Docker Compose v2 is not available."

load_env_file

# Show Python print() output from both Uvicorn and Celery immediately in this
# terminal. PYTHONIOENCODING also keeps Persian debug output readable.
export PYTHONUNBUFFERED="${PYTHONUNBUFFERED:-1}"
export PYTHONIOENCODING="${PYTHONIOENCODING:-utf-8}"

# Settings above can also be defined in .env.
API_APP="${API_APP:-api.main:app}"
API_HOST="${API_HOST:-127.0.0.1}"
API_PORT="${API_PORT:-8000}"
CELERY_APP="${CELERY_APP:-api.celery_app.celery_app}"
CELERY_LOGLEVEL="${CELERY_LOGLEVEL:-info}"
CELERY_CONCURRENCY="${CELERY_CONCURRENCY:-1}"
FLOWER_HOST="${FLOWER_HOST:-127.0.0.1}"
FLOWER_PORT="${FLOWER_PORT:-5555}"
FRONTEND_DIR="${FRONTEND_DIR:-frontend}"
FRONTEND_HOST="${FRONTEND_HOST:-127.0.0.1}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
STOP_INFRA_ON_EXIT="${STOP_INFRA_ON_EXIT:-true}"

COMPOSE=(docker compose --env-file "$ENV_FILE")

[[ -f "$PROJECT_DIR/docker-compose.yml" || -f "$PROJECT_DIR/compose.yml" ]] \
    || error "docker-compose.yml or compose.yml was not found in $PROJECT_DIR"

[[ -d "$PROJECT_DIR/$FRONTEND_DIR" ]] \
    || error "Frontend directory was not found: $PROJECT_DIR/$FRONTEND_DIR"

resolve_npm_frontend_dir

POWERSHELL_CMD="$(find_powershell || true)"
if [[ -n "$POWERSHELL_CMD" ]]; then
    WINDOWS_PROJECT_DIR="$(to_windows_path "$PROJECT_DIR")"
fi

if [[ "${QDRANT_URL:-}" == *"://qdrant:"* ]]; then
    error "QDRANT_URL points to the Docker-only hostname 'qdrant'. For local development use http://127.0.0.1:6333 in .env."
fi

if [[ "${REDIS_URL:-}" == *"://redis:"* ]]; then
    error "REDIS_URL points to the Docker-only hostname 'redis'. For local development use redis://127.0.0.1:6379/0 in .env."
fi

if [[ "${OLLAMA_HOST:-}" == *"host.docker.internal"* ]]; then
    error "OLLAMA_HOST points to host.docker.internal. For local development use http://127.0.0.1:11434 in .env."
fi

info "Stopping Docker versions of API, Worker, Flower, and Frontend..."
"${COMPOSE[@]}" stop api worker flower frontend >/dev/null 2>&1 || true

info "Stopping stale local processes from this project..."
stop_windows_project_processes

info "Starting Redis and Qdrant..."
if docker compose up --help 2>/dev/null | grep -q -- '--wait'; then
    "${COMPOSE[@]}" up -d --wait redis qdrant
else
    "${COMPOSE[@]}" up -d redis qdrant
fi

if [[ ! -d "$PROJECT_DIR/$FRONTEND_DIR/node_modules" ]]; then
    info "Installing frontend dependencies (first run only)..."
    npm --prefix "$NPM_FRONTEND_DIR" install
fi

info "Starting API on http://${API_HOST}:${API_PORT}"
start_background "${UV_CMD[@]}" run uvicorn "$API_APP" \
    --host "$API_HOST" \
    --port "$API_PORT" \
    --reload

info "Starting Celery worker"
start_background "${UV_CMD[@]}" run watchfiles \
    --filter python \
    --target-type command \
    --sigint-timeout 60 \
    "celery -A $CELERY_APP worker --loglevel=$CELERY_LOGLEVEL --pool=solo --concurrency=$CELERY_CONCURRENCY --events --hostname=local-worker-${RUN_ID}@%h" \
    api src scripts

info "Starting Flower on http://${FLOWER_HOST}:${FLOWER_PORT}"
start_background "${UV_CMD[@]}" run celery \
    -A "$CELERY_APP" \
    flower \
    --address="$FLOWER_HOST" \
    --port="$FLOWER_PORT"

info "Starting frontend on http://${FRONTEND_HOST}:${FRONTEND_PORT}"
start_background npm --prefix "$NPM_FRONTEND_DIR" run dev -- \
    --host "$FRONTEND_HOST" \
    --port "$FRONTEND_PORT" \
    --strictPort

info "Development stack is running. Press Ctrl+C to stop API, Worker, Flower, and Frontend."
printf 'API:      http://%s:%s\n' "$API_HOST" "$API_PORT"
printf 'Swagger:  http://%s:%s/docs\n' "$API_HOST" "$API_PORT"
printf 'Flower:   http://%s:%s\n' "$FLOWER_HOST" "$FLOWER_PORT"
printf 'Frontend: http://%s:%s\n\n' "$FRONTEND_HOST" "$FRONTEND_PORT"
printf 'Live reload: Python (API + Worker) and frontend changes are watched automatically.\n'
printf 'Python print() output from API and Worker will appear below in this terminal.\n'
printf 'Use print("message", flush=True) for explicit immediate flushing.\n\n'

set +e
wait -n "${PIDS[@]}"
EXIT_CODE=$?
set -e

if [[ "$EXIT_CODE" -ne 0 ]]; then
    printf '\nOne of the development processes exited with code %s.\n' "$EXIT_CODE" >&2
else
    printf '\nOne of the development processes stopped.\n' >&2
fi

exit "$EXIT_CODE"
