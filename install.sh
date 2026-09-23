#!/usr/bin/env bash
# Установка и первый запуск «Граф денег» (Linux, macOS; на Windows — через WSL или вручную, см. INSTALL.md).
#
#   ./install.sh            установить зависимости и пересчитать выгрузки
#   ./install.sh --serve    то же и сразу запустить экран с AI-ассистентом
#   ./install.sh --test     то же и прогнать автотесты
#   ./install.sh --no-run   только установить зависимости
#
# Ключ OpenAI для AI-ассистента (необязательно):  OPENAI_API_KEY=sk-... ./install.sh
set -euo pipefail
cd "$(dirname "$0")"

RUN=1 SERVE=0 TEST=0
for arg in "$@"; do
  case "$arg" in
    --serve) SERVE=1 ;;
    --test) TEST=1 ;;
    --no-run) RUN=0 ;;
    -h | --help) sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Неизвестный параметр: $arg (список: ./install.sh --help)" >&2; exit 2 ;;
  esac
done

step() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

# 1. uv — единственное, что нужно поставить: он сам скачает Python 3.12 и пакеты
if ! command -v uv >/dev/null 2>&1; then
  step "uv не найден, устанавливаю (https://docs.astral.sh/uv/)"
  if command -v curl >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
  elif command -v wget >/dev/null 2>&1; then
    wget -qO- https://astral.sh/uv/install.sh | sh
  else
    echo "Нужен curl или wget. Или установите uv вручную: https://docs.astral.sh/uv/getting-started/installation/" >&2
    exit 1
  fi
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
fi
step "uv $(uv --version | awk '{print $2}')"

# 2. Python 3.12 и зависимости — точные версии из uv.lock
step "Устанавливаю Python 3.12 и зависимости (первый раз — около минуты)"
uv sync --frozen || uv sync

# 3. .env для AI-ассистента (файл не попадает в git)
if [ ! -f .env ]; then
  cp .env.example .env
  if [ -n "${OPENAI_API_KEY:-}" ]; then
    sed -i.bak "s|^OPENAI_API_KEY=.*|OPENAI_API_KEY=${OPENAI_API_KEY}|" .env && rm -f .env.bak
    step "Ключ OpenAI записан в .env"
  else
    step "Создан .env без ключа: без него AI-ассистент отвечает только на вопросы по графу. Ключ можно вписать позже."
  fi
fi

# 4. Полный пересчёт: data/*.parquet → out/ (проверка схемы ТЗ встроена)
if [ "$RUN" = 1 ]; then
  step "Пересчёт выгрузок"
  uv run moneygraph
fi

# 5. Автотесты
if [ "$TEST" = 1 ]; then
  step "Автотесты"
  uv run pytest -q
fi

cat <<'EOF'

Готово. Дальше:
  экран без сервера            откройте out/viewer.html в браузере
  экран и AI-ассистент         uv run moneygraph serve        → http://127.0.0.1:8765
  карточка клиента в терминале uv run moneygraph explain 8165763100
  пересчёт после изменений     uv run moneygraph
  автотесты                    uv run pytest
EOF

if [ "$SERVE" = 1 ]; then
  step "Запускаю экран с AI-ассистентом (Ctrl+C — остановить)"
  exec uv run moneygraph serve
fi
