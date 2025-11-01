import logging
import traceback
import os
from dotenv import load_dotenv
from core.logger import logger
load_dotenv()

def safe_execute(func, *args, **kwargs):
    """Безопасное выполнение функции с логированием ошибок"""
    try:
        return func(*args, **kwargs)
    except Exception as e:
        logger.error(f"[Utils] Ошибка в {func.__name__}: {e}")
        logger.error(traceback.format_exc())
        return None


import os
from dotenv import load_dotenv

load_dotenv()


def get_env_file_path(env_var_name: str) -> str:
    """
    Получить полный путь к файлу из переменной окружения,
    подставляя относительный путь относительно корня проекта.
    """
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # корень проекта
    filename = os.getenv(env_var_name)

    if not filename:
        raise ValueError(f"Переменная окружения '{env_var_name}' не задана")

    full_path = os.path.join(base_dir, filename)

    if not os.path.exists(full_path):
        raise FileNotFoundError(f"Файл не найден: {full_path}")

    return full_path
