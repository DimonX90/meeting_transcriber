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
    """
    Диаризация аудио с использованием pyannote.audio 3.x и TorchCodec.
    Возвращает список сегментов [{'start', 'end', 'speaker'}, ...].
    Временный файл подготовленного аудио удаляется после работы.
    """

    # Подготовка аудио через ffmpeg
    prepared_path = os.path.join(os.path.dirname(audio_path), "_prepared_audio.wav")

    if sys.platform.startswith("win"):
        FFMPEG_BIN = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "bin", "ffmpeg.exe"))
    else:
        FFMPEG_BIN = "/usr/bin/ffmpeg"

    command = [
        FFMPEG_BIN,
        "-y",
        "-i", audio_path,
        "-af", "aresample=16000,volume=1.0,afftdn",
        "-ac", "1",
        "-c:a", "pcm_s16le",
        prepared_path
    ]
    try:
        subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        logger.info(f"[Diarization] Аудио успешно подготовлено: {prepared_path}")
    except subprocess.CalledProcessError as e:
        logger.error(f"[Diarization] Ошибка при подготовке аудио: {e}")
        return []

    try:
        # Отключаем предупреждения о симлинках Hugging Face
        os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

        # Загружаем пайплайн диаризации без фиктивного тега версии
        # Можно указать конкретный commit hash, если нужна стабильная версия
        pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization",
            use_auth_token=os.getenv("HF_TOKEN")
        )

        # Диаризация
        diarization = pipeline(prepared_path)

        segments = [
            {"start": float(turn.start), "end": float(turn.end), "speaker": str(speaker)}
            for turn, _, speaker in diarization.itertracks(yield_label=True)
        ]

        num_speakers = len(set(seg['speaker'] for seg in segments))
        logger.info(f"[Diarization] Аудио разбито на {num_speakers} спикеров")

        return segments

    except Exception as e:
        logger.error(f"[Diarization] Ошибка разметки спикеров: {e}")
        return []

    finally:
        # Удаляем временный файл
        if os.path.exists(prepared_path):
            try:
                os.remove(prepared_path)
            except Exception as e:
                logger.warning(f"[Diarization] Не удалось удалить временный файл {prepared_path}: {e}")
