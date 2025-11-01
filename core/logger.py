# core/logger.py
import logging
import os
import sys
from datetime import datetime

LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "logs")
os.makedirs(LOG_DIR, exist_ok=True)

LOG_FILE = os.path.join(LOG_DIR, "errors.log")

# === Цвета для консоли ===
RESET = "\033[0m"
COLORS = {
    logging.DEBUG: "\033[37m",   # серый
    logging.INFO: "\033[0m",     # стандартный
    logging.WARNING: "\033[33m", # жёлтый
    logging.ERROR: "\033[31m",   # красный
    logging.CRITICAL: "\033[41m" # красный фон
}

class ColorFormatter(logging.Formatter):
    def format(self, record):
        log_fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        date_fmt = "%Y-%m-%d %H:%M:%S"
        formatter = logging.Formatter(log_fmt, date_fmt)
        formatted = formatter.format(record)
        color = COLORS.get(record.levelno, RESET)
        return f"{color}{formatted}{RESET}"

# === Кастомный FileHandler с разделителями по дням ===
class DailySeparatorFileHandler(logging.FileHandler):
    def __init__(self, filename, mode='a', encoding=None, delay=False):
        super().__init__(filename, mode, encoding, delay)
        self.current_day = None

    def emit(self, record):
        log_day = datetime.now().strftime("%Y-%m-%d")
        if log_day != self.current_day:
            # новый день → вставляем разделитель
            self.stream.write(f"\n===== {log_day} =====\n")
            self.current_day = log_day
        super().emit(record)

# === Инициализация логгера ===
logger = logging.getLogger("transcriber")
logger.setLevel(logging.DEBUG)

# Консоль
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(ColorFormatter())
logger.addHandler(console_handler)

# Файл (только ошибки и выше, с разделителями дней)
file_handler = DailySeparatorFileHandler(LOG_FILE, encoding="utf-8")
file_handler.setLevel(logging.ERROR)
file_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    "%Y-%m-%d %H:%M:%S"
))
logger.addHandler(file_handler)
