#!/bin/sh
# Ставит git-хуки из scripts/ в .git/hooks/
set -e
cd "$(dirname "$0")/.."
cp scripts/pre-commit .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
echo "Хук pre-commit установлен."
echo "Теперь таблица со служебными листами не попадёт в коммит."
