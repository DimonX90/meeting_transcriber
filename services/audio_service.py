import os
import subprocess
import logging
from pyannote.audio import Pipeline
from core.logger import logger
import uuid
import sys

def extract_audio(video_path: str, file_name) -> bool:
    """Извлекаем аудио из видео с помощью ffmpeg"""
    if sys.platform.startswith("win"):
        FFMPEG_BIN = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "bin", "ffmpeg.exe"))
    else:
        # Для Linux/macOS используем системный ffmpeg
        FFMPEG_BIN = "/usr/bin/ffmpeg"  # Обычно установлен через apt/yum/brew


    file_name = os.path.splitext(file_name)[0]

    # Папка для временных файлов внутри проекта
    temp_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "temp"))
    os.makedirs(temp_dir, exist_ok=True)  # создаём папку, если её нет

    # Уникальное имя временного аудиофайла
    temp_filename = f"audio_{file_name}.wav"
    audio_path = os.path.join(temp_dir, temp_filename)

    try:
        command = [
            FFMPEG_BIN,
            "-y",
            "-i", video_path,
            "-vn",
            "-acodec", "pcm_s16le",
            "-ar", "16000",
            "-ac", "1",
            audio_path
        ]
        subprocess.run(command, check=True)
        logger.info(f"Аудио успешно извлечено: {audio_path}")
        return audio_path
    except subprocess.CalledProcessError as e:
        logger.error(f"[Audio] Ошибка извлечения аудио: {e}")
        return False



def diarize_audio(audio_path: str):
    prepared_path = os.path.join(os.path.dirname(audio_path), "_prepared_audio.wav")
    # путь к ffmpeg.exe в проекте
    if sys.platform.startswith("win"):
        FFMPEG_BIN = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "bin", "ffmpeg.exe"))
    else:
        # Для Linux/macOS используем системный ffmpeg
        FFMPEG_BIN = "/usr/bin/ffmpeg"  # Обычно установлен через apt/yum/brew

    command = [
        FFMPEG_BIN,
        "-y",
        "-i", audio_path,
        "-af", "aresample=16000,volume=1.0,afftdn",  # ресемплинг, нормализация, шумоподавление
        "-ac", "1",  # моно
        "-c:a", "pcm_s16le",
        prepared_path
    ]
    subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    """
    Разбиваем аудио на спикеров через pyannote.audio.
    Адаптировано для Windows без симлинков.
    """
    try:
        # Отключаем предупреждения о симлинках
        os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

        # Загружаем пайплайн диаризации (можно использовать локальный кэш)
        pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization",
            use_auth_token=os.getenv("HF_TOKEN")  # Если нужен токен Hugging Face
        )

        diarization = pipeline(prepared_path)

        segments = []
        for turn, _, speaker in diarization.itertracks(yield_label=True):
            segments.append({
                "start": turn.start,
                "end": turn.end,
                "speaker": speaker
            })

        num_speakers = len(set([s['speaker'] for s in segments]))
        logger.info(f"[Diarization] Аудио разбито на {num_speakers} спикеров")
        return segments

        # Удаляем временные файлы
        os.remove(prepared_path)

    except Exception as e:
        logger.error(f"[Diarization] Ошибка разметки спикеров: {e}")
        return []


