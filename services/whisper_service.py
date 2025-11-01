import os

import whisper
from core.logger import logger
from core.utils import safe_execute
from services.audio_service import extract_audio, diarize_audio
from services.drive_service import download_file_to_path
import time
import shutil


def transcribe_audio(audio_path: str, model_size: str = "base") -> str:
    """
    Транскрипция аудио с помощью Whisper на CPU.

    Параметры:
        audio_path (str): путь к аудио файлу
        model_size (str): размер модели ('tiny', 'base', 'small', 'medium', 'large')

    Возвращает:
        str: текст транскрипции
    """

    # Ждём появления файла
    waited = 0
    wait_timeout = 120
    check_interval = 5
    audio_path = os.path.abspath(audio_path)
    while not os.path.exists(audio_path):
        if waited >= wait_timeout:
            logger.error(f"[Whisper] Файл не появился за {wait_timeout} секунд: {audio_path}")
            return ""
        time.sleep(check_interval)
        waited += check_interval

    try:

        logger.info(f"[Whisper] Загружаем модель '{model_size}' на CPU...")
        model = whisper.load_model(model_size, device="cpu")  # Принудительно CPU
        logger.info(f"[Whisper] Начало транскрипции: {audio_path}")
        result = model.transcribe(audio_path, fp16=False, word_timestamps=True)  # fp16=False для стабильности на CPU
        text = result.get("text", "")
        logger.info(f"[Whisper] Транскрипция завершена: {len(text)} символов")
        return text
    except Exception as e:
        logger.error(f"[Whisper] Ошибка транскрипции: {e}")
        return ""


def assign_speakers_to_text(diarization_segments, transcription_segments):
    """
    Привязывает текст к спикерам по временным меткам.

    Возвращает список:
    [
        {"speaker":"SPEAKER_0", "text":"Привет, как дела?"},
        {"speaker":"SPEAKER_1", "text":"А ты?"}
    ]
    """
    result = []
    for t_seg in transcription_segments:
        t_start, t_end, t_text = t_seg["start"], t_seg["end"], t_seg["text"]
        # ищем спикеров, чьи сегменты перекрываются с этим отрезком
        overlapping_speakers = [s['speaker'] for s in diarization_segments
                                if not (s['end'] <= t_start or s['start'] >= t_end)]
        speaker = overlapping_speakers[0] if overlapping_speakers else "UNKNOWN"
        result.append({"speaker": speaker, "text": t_text})
    return result


async def process_file(file, service,DATA_DIR):
    try:
        # Абсолютный путь к рабочей директории
        DATA_DIR = os.path.abspath(DATA_DIR)
        video_name = file['name']
        video_path = os.path.join(DATA_DIR, video_name)

        # Скачиваем видео
        logger.info(f"[Worker] Скачиваем {video_name}...")
        if not safe_execute(download_file_to_path, file['id'], video_path):
            logger.error(f"[Worker] Ошибка скачивания {video_name}")
            return


        # Извлекаем аудио в память (или временный файл, но без сохранения на диск)
        # Для простоты используем временный файл, удалим после обработки

        audio_temp_path =  extract_audio(video_path, video_name)


        # Диаризация
        segments = diarize_audio(audio_temp_path)

        # Транскрипция
        transcript_text = transcribe_audio(audio_temp_path, "base")

        speaker_text = assign_speakers_to_text(
            segments,
            transcript_text.get("segments", [])
        )
        for seg in speaker_text:
            print(f"{seg['speaker']}: {seg['text']}")

        # Удаляем временный аудио файл
        try:
            os.remove(audio_temp_path)
            os.remove( video_path)
        except Exception as e:
            logger.error(f"[Worker] Ошибка удаления временых файлов: {e}")

        # TODO: сохраняем segments и transcript_text в Google Drive и Airtable
        logger.info(f"[Worker] Обработка {video_name} завершена")

    except Exception as e:
        logger.error(f"[Worker] Ошибка при обработке {file['name']}: {e}")