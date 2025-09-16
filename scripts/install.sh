#!/usr/bin/env bash
set -e

# создаём виртуальное окружение
python3 -m venv venv
source venv/bin/activate

# обновляем pip
pip install --upgrade pip

# ставим зависимости
pip install -r requirements.txt

echo "Окружение готово. Активируй его: source venv/bin/activate"