#!/usr/bin/env bash
set -u

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP_DIR="$ROOT/app"
RESULTS_DIR="$ROOT/results"
FIRST_PORT=8080
LAST_PORT=8099
OS="$(uname -s)"
USE_SUDO=0
PORT=""
BASE=""
RUN_ID=""

say() { printf '%s\n' "$*"; }

step() { printf '\n==> %s\n' "$*"; }

fail() {
    printf '\n[Ошибка] %s\n' "$1" >&2
    if [ $# -gt 1 ] && [ -n "$2" ]; then printf '%s\n' "$2" >&2; fi
    if [ -t 0 ]; then
        printf '\nНажмите Enter, чтобы закрыть окно. '
        read -r _
    fi
    exit 1
}

retry_until() {
    local deadline=$((SECONDS + $1))
    shift
    until "$@"; do
        if [ "$SECONDS" -ge "$deadline" ]; then return 1; fi
        sleep 2
    done
}

install_hint() {
    if [ "$OS" = Darwin ]; then
        say "Установите Docker Desktop: https://www.docker.com/products/docker-desktop/ — и запустите этот файл снова."
    else
        say "Установите Docker Engine с плагином Compose: https://docs.docker.com/engine/install/ — и запустите этот файл снова."
    fi
}

add_known_docker_paths() {
    # A double-clicked script starts with a minimal PATH that misses the usual Docker CLI locations.
    local dir
    for dir in /usr/local/bin /opt/homebrew/bin "$HOME/.docker/bin" /Applications/Docker.app/Contents/Resources/bin; do
        case ":$PATH:" in
            *":$dir:"*) ;;
            *) if [ -d "$dir" ]; then PATH="$PATH:$dir"; fi ;;
        esac
    done
    export PATH
}

docker_cli() {
    if [ "$USE_SUDO" = 1 ]; then sudo docker "$@"; else docker "$@"; fi
}

compose() {
    # sudo resets the environment, so the chosen port is handed over explicitly.
    if [ "$USE_SUDO" = 1 ]; then
        sudo env MG_HTTP_PORT="$PORT" docker compose "$@"
    else
        MG_HTTP_PORT="$PORT" docker compose "$@"
    fi
}

docker_ready() { docker_cli info >/dev/null 2>&1; }

start_docker_daemon() {
    if [ "$OS" = Darwin ] && [ -d /Applications/Docker.app ]; then
        say "Запускаю Docker Desktop…"
        open -ga Docker
    elif [ "$OS" = Linux ] && command -v systemctl >/dev/null 2>&1; then
        say "Запускаю службу Docker (может понадобиться пароль администратора)…"
        sudo systemctl start docker
    else
        return 1
    fi
}

ensure_docker() {
    step "Проверяю Docker"
    add_known_docker_paths
    command -v docker >/dev/null 2>&1 || fail "Docker не найден." "$(install_hint)"
    if ! docker_ready && [ "$OS" = Linux ] && docker info 2>&1 | grep -qi "permission denied"; then
        say "Docker доступен только администратору — команды пойдут через sudo."
        USE_SUDO=1
    fi
    if ! docker_ready; then
        start_docker_daemon || fail "Docker установлен, но не запущен." "Запустите Docker и запустите этот файл снова."
        say "Жду готовности Docker (до 3 минут)…"
        retry_until 180 docker_ready ||
            fail "Docker не ответил за 3 минуты." "Дождитесь запуска Docker и запустите этот файл снова."
    fi
    docker_cli compose version >/dev/null 2>&1 ||
        fail "Не найден Docker Compose v2 (команда «docker compose»)." "Обновите Docker или установите пакет docker-compose-plugin."
}

port_in_use() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }

published_port() {
    local mapping
    mapping="$(compose port frontend 8080 2>/dev/null | head -n 1)"
    if [ -n "$mapping" ]; then printf '%s' "${mapping##*:}"; fi
}

choose_port() {
    PORT="$(published_port)"
    if [ -n "$PORT" ]; then
        say "Приложение уже запущено — использую порт $PORT."
        return
    fi
    local candidate=$FIRST_PORT
    while [ "$candidate" -le "$LAST_PORT" ]; do
        if ! port_in_use "$candidate"; then
            PORT=$candidate
            return
        fi
        candidate=$((candidate + 1))
    done
    fail "Порты $FIRST_PORT–$LAST_PORT заняты другими программами." "Освободите порт $FIRST_PORT и запустите этот файл снова."
}

api_get() { curl -fsS --max-time 30 "$BASE$1"; }

api_ready() { curl -fs -o /dev/null --max-time 5 "$BASE/api/v1/ready"; }

json_string() { LC_ALL=C sed -n "s/.*\"$1\":\"\\([^\"]*\\)\".*/\\1/p"; }

first_run_id() { LC_ALL=C sed -n 's/^{"id":"\([0-9a-f-]*\)".*/\1/p' | head -n 1; }

find_demo_run() {
    local runs status id
    runs="$(api_get "/api/v1/runs?limit=200" |
        LC_ALL=C grep -o '{"id":"[0-9a-f-]\{36\}","name":"[^"]*","source":"demo","status":"[a-z]*"')"
    for status in succeeded running queued; do
        id="$(printf '%s\n' "$runs" | grep "\"status\":\"$status\"" | first_run_id)"
        if [ -n "$id" ]; then
            printf '%s' "$id"
            return 0
        fi
    done
    return 1
}

create_demo_run() { curl -fsS --max-time 30 -X POST "$BASE/api/v1/runs/demo" | first_run_id; }

wait_for_run() {
    local deadline=$((SECONDS + 900)) run status label shown=""
    while [ "$SECONDS" -lt "$deadline" ]; do
        run="$(api_get "/api/v1/runs/$RUN_ID")" || run=""
        status="$(printf '%s' "$run" | json_string status)"
        case "$status" in
            succeeded) return 0 ;;
            failed | cancelled)
                fail "Анализ завершился со статусом «$status»." "$(printf '%s' "$run" | json_string message)" ;;
        esac
        label="$(printf '%s' "$run" | json_string stage_label)"
        if [ -n "$label" ] && [ "$label" != "$shown" ]; then
            say "   $label"
            shown=$label
        fi
        sleep 2
    done
    fail "Анализ не завершился за 15 минут." "Журнал сервиса: docker compose logs backend (в папке app)."
}

prepare_demo_run() {
    step "Анализ данных кейса: 2 248 клиентов, 4 840 переводов за июль 2026"
    RUN_ID="$(find_demo_run)" || RUN_ID="$(create_demo_run)" || RUN_ID=""
    if [ -z "$RUN_ID" ]; then
        fail "Не удалось найти или создать прогон на данных кейса." "Журнал сервиса: docker compose logs backend (в папке app)."
    fi
    wait_for_run
}

save_exports() {
    local name file
    mkdir -p "$RESULTS_DIR" || return 1
    for name in nodes_roles clusters top_nodes features resilience data_requests run_report; do
        case "$name" in
            run_report) file="$name.md" ;;
            *) file="$name.csv" ;;
        esac
        curl -fsS --max-time 120 -o "$RESULTS_DIR/$file" "$BASE/api/v1/runs/$RUN_ID/exports/$name" || return 1
    done
}

open_browser() {
    if [ "$OS" = Darwin ]; then
        open "$1"
        return
    fi
    local opener
    for opener in xdg-open sensible-browser wslview; do
        if command -v "$opener" >/dev/null 2>&1; then
            "$opener" "$1" >/dev/null 2>&1 &
            return 0
        fi
    done
    return 1
}

main() {
    cd "$APP_DIR" 2>/dev/null || fail "Рядом с этим файлом нет папки app."
    ensure_docker
    if [ ! -f .env ]; then cp .env.example .env || fail "Не удалось создать app/.env."; fi
    choose_port
    BASE="http://127.0.0.1:$PORT"

    step "Собираю и запускаю приложение на порту $PORT (первый запуск — несколько минут: скачиваются образы и зависимости)"
    compose up -d --build ||
        fail "Не удалось запустить контейнеры." "Проверьте интернет и свободное место на диске, затем запустите этот файл снова."

    step "Жду готовности сервиса"
    retry_until 300 api_ready || fail "Сервис не ответил за 5 минут." "Журнал сервиса: docker compose logs (в папке app)."

    local url="http://localhost:$PORT/"
    if api_get "/api/v1/meta" | grep -q '"auth_required":false'; then
        prepare_demo_run
        url="http://localhost:$PORT/runs/$RUN_ID"
        if save_exports; then
            say "Выгрузки сохранены в папку: $RESULTS_DIR"
        else
            say "Не удалось сохранить выгрузки — они есть в интерфейсе (кнопка «↓ Экспорт»)."
        fi
    else
        say "В app/.env задан MG_API_TOKEN — войдите в интерфейсе с этим токеном."
    fi

    step "Готово: $url"
    open_browser "$url" || say "Откройте эту ссылку в браузере."
    if [ -t 0 ]; then
        printf '\nПриложение работает. Нажмите Enter, чтобы остановить его (результаты сохранятся до следующего запуска). '
        read -r _
        step "Останавливаю приложение"
        compose down
    else
        say "Приложение продолжает работать. Остановить: cd \"$APP_DIR\" && docker compose down"
    fi
}

main
