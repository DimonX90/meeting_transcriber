import os
import whisper
from core.logger import logger
from core.utils import safe_execute
from services.audio_service import extract_audio, diarize_audio
from services.drive_service import download_file_to_path, save_transcription_to_drive
import time
from typing import List, Dict
import shutil
import subprocess
from services.airtable_service import AirtableClient
from services.openai_promt_generation_service import openai_request
from services.synchronizw_teams_service import map_whisper_speakers_by_iter, parse_vtt_text
from langcodes import Language
import re
from datetime import datetime
import sys
import assemblyai as aai
import glob

# --- Инициализация объекта Airtable ---
airtable = AirtableClient(
    api_key=os.getenv("AIRTABLE_API_KEY"),
    base_id=os.getenv("AIRTABLE_BASE_ID"),
    table_name=os.getenv("AIRTABLE_TABLE_NAME")
)

# путь к ffmpeg.exe в проекте
if sys.platform.startswith("win"):
    FFMPEG_BIN = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "bin", "ffmpeg.exe"))
else:
    # Для Linux/macOS используем системный ffmpeg
    FFMPEG_BIN = "/usr/bin/ffmpeg"  # Обычно установлен через apt/yum/brew



def prepare_audio_for_transcription(input_path: str, output_path: str):
    """
    Подготавливает аудио для транскрипции:
    - Конвертирует в PCM16
    - Моно
    - 16kHz
    - Нормализует громкость
    - Подавляет шум (basic noise reduction)
    """
    command = [
        FFMPEG_BIN,
        "-y",
        "-i", input_path,
        "-af", "aresample=16000,volume=1.0,afftdn",  # ресемплинг, нормализация, шумоподавление
        "-ac", "1",  # моно
        "-c:a", "pcm_s16le",
        output_path
    ]
    subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

def get_audio_duration(input_path: str) -> float:
    """
    Получаем длительность аудио в секундах через ffmpeg
    """
    command = [
        FFMPEG_BIN,
        "-i", input_path,
        "-f", "null",
        "-"  # вывод не нужен
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    for line in result.stderr.splitlines():
        if "Duration" in line:
            time_str = line.strip().split("Duration:")[1].split(",")[0].strip()
            h, m, s = time_str.split(":")
            return int(h) * 3600 + int(m) * 60 + float(s)
    return 0.0

def export_audio_segment_ffmpeg(input_path: str, start: float, end: float, output_path: str):
    """
    Нарезка сегмента аудио через ffmpeg.
    start, end в секундах
    """
    command = [
        FFMPEG_BIN,
        "-y",
        "-i", input_path,
        "-ss", str(start),
        "-to", str(end),
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        output_path
    ]
    subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def transcribe_audio(
        audio_path: str,
        api_key: str,
        language: str = "uk"
):
    """
    Транскрипция аудио через AssemblyAI.
    Возвращает:
      - full_text: весь текст
      - all_segments: список слов с таймкодами {start, end, text, confidence}
    """
    audio_path = os.path.abspath(audio_path)
    waited = 0
    wait_timeout = 120
    check_interval = 5

    while not os.path.exists(audio_path):
        if waited >= wait_timeout:
            logger.error(f"[AssemblyAI] Файл не появился за {wait_timeout} секунд: {audio_path}")
            return "", []
        time.sleep(check_interval)
        waited += check_interval

    try:
        logger.info("[AssemblyAI] Подготовка аудио для транскрипции...")
        prepared_path = os.path.join(os.path.dirname(audio_path), "_prepared_audio.wav")
        prepare_audio_for_transcription(audio_path, prepared_path)

        aai.settings.api_key = api_key
        transcriber = aai.Transcriber()

        logger.info(f"[AssemblyAI] Загружаем файл {prepared_path} на транскрипцию...")
        transcript = transcriber.transcribe(
            prepared_path,
            config=aai.TranscriptionConfig(language_code=language)
        )

        if transcript.status == aai.TranscriptStatus.error:
            logger.error(f"[AssemblyAI] Ошибка транскрипции: {transcript.error}")
            return "", []

        full_text = transcript.text.strip()
        all_segments = []

        # transcript.words — список слов с таймкодами
        for w in transcript.words:
            start_s = w.start / 1000.0
            end_s = w.end / 1000.0
            all_segments.append({
                "start": start_s,
                "end": end_s,
                "text": w.text,
                "confidence": getattr(w, "confidence", None)
            })

        logger.info(f"[AssemblyAI] Транскрипция завершена. Слов: {len(all_segments)}, символов: {len(full_text)}")

        os.remove(prepared_path)
        return full_text, all_segments

    except Exception as e:
        logger.error(f"[AssemblyAI] Ошибка транскрипции: {e}")
        return "", []


def assign_speakers_to_text(
    diarization_segments: list,
    transcription_segments: list
) -> list:
    """
    Группирует слова в фразы по спикерам.
    """
    assigned_phrases = []
    current_speaker = None
    current_phrase = {"start": None, "end": None, "speaker": None, "text": ""}

    for word in transcription_segments:
        # находим спикера для слова
        speaker = None
        for d in diarization_segments:
            if word['start'] >= d['start'] and word['end'] <= d['end']:
                speaker = d['speaker']
                break
        if speaker is None and diarization_segments:
            closest = min(diarization_segments, key=lambda d: abs(d['start'] - word['start']))
            speaker = closest['speaker']

        # если спикер сменился, сохраняем предыдущую фразу
        if speaker != current_speaker:
            if current_speaker is not None:
                assigned_phrases.append(current_phrase)
            # начинаем новую фразу
            current_phrase = {
                "start": word['start'],
                "end": word['end'],
                "speaker": speaker,
                "text": word['text']
            }
            current_speaker = speaker
        else:
            # продолжаем текущую фразу
            current_phrase['end'] = word['end']
            current_phrase['text'] += " " + word['text']

    # добавляем последнюю фразу
    if current_phrase['text']:
        assigned_phrases.append(current_phrase)

    return assigned_phrases


def get_langoage(name):
    # Выделяем кусок после последнего "_"
    if "_" not in name:
        return "uk"

    lang = name.rsplit("_", 1)[1]

    # Проверяем, является ли это валидным языковым кодом
    try:
        if Language.get(lang).is_valid():
            return lang
    except:
        pass

    return "uk"


def extract_meeting_date(filename: str) -> str:
    """
    Извлекает дату из имени файла и возвращает её
    в формате YYYY-MM-DD для Airtable
    """

    match = re.search(r'(\d{8})', filename)

    if not match:
        raise ValueError(f"Дата не найдена в имени файла: {filename}")

    date_str = match.group(1)

    dt = datetime.strptime(date_str, "%Y%m%d")

    return dt.date().isoformat()


def clear_temp_folder(substring: str):
    """
    Удаляет все файлы из папки 'temp' в корне проекта, в названии которых есть переданная подстрока.

    Параметры:
        substring (str): Подстрока для поиска в имени файла.
    """
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    temp_folder = os.path.join(project_root, "temp")

    if not os.path.exists(temp_folder):
        logger.warning(f"Папка {temp_folder} не существует")
        return

    # Находим все файлы (не папки) в temp
    files = [f for f in glob.glob(os.path.join(temp_folder, "*")) if os.path.isfile(f)]

    # Фильтруем только те файлы, в имени которых есть substring
    matched_files = [f for f in files if substring in os.path.basename(f)]

    if not matched_files:
        logger.info(f"В папке {temp_folder} нет файлов с подстрокой '{substring}'")
        return

    for f in matched_files:
        try:
            os.remove(f)
            logger.info(f"Удалён файл: {f}")
        except Exception as e:
            logger.error(f"Не удалось удалить файл {f}: {e}")

async def process_file(file, service,DATA_DIR,base_filename,record_id,transcription_file):
    try:
        # Абсолютный путь к рабочей директории
        DATA_DIR = os.path.abspath(DATA_DIR)
        video_name = file['name']
        video_path = os.path.join(DATA_DIR, video_name)

        teams_name = transcription_file['name']
        teams_path = os.path.join(DATA_DIR, teams_name)

        # Скачиваем видео
        logger.info(f"[Worker] Скачиваем {video_name}...")
        if not safe_execute(download_file_to_path, file['id'], video_path):
            logger.error(f"[Worker] Ошибка скачивания {video_name}")
            return

        logger.info(f"[Worker] Скачиваем {teams_path }...")
        if not safe_execute(download_file_to_path, transcription_file['id'], teams_path ):
            logger.error(f"[Worker] Ошибка скачивания {teams_path }")
            return


        # Извлекаем аудио в память (или временный файл, но без сохранения на диск)
        # Для простоты используем временный файл, удалим после обработки

        audio_temp_path =  extract_audio(video_path, video_name)


        # Диаризация
        segments = diarize_audio(audio_temp_path)

        #Получение языка
        lang = get_langoage(base_filename)

        # Транскрипция
        asembl_api_key = os.getenv("ASSEMBLY_AI_KEY")
        full_text, transcription_segments = transcribe_audio(audio_temp_path, asembl_api_key , lang)

        speaker_text = assign_speakers_to_text(segments,transcription_segments)

        file_link = save_transcription_to_drive(
            speaker_text,
            folder_id=os.getenv("WHISPER_AI_TRANSCRIPTION"),
            base_filename=base_filename
        )


        await airtable.update_record(record_id, {'Link to whisper ai transcription': file_link.get("webViewLink")})

        with open(teams_path, "r", encoding="utf-8") as f:
            vtt_text = f.read()

        vtt_segments = parse_vtt_text(vtt_text)

        teams_trans_doc_link = save_transcription_to_drive(
            vtt_segments,
            folder_id = os.getenv("TEAMS_TRANS_DOC"),
            base_filename=base_filename
        )
        logger.info(teams_trans_doc_link)
        await airtable.update_record(record_id, {'Link to teams transcription doc': teams_trans_doc_link.get("webViewLink")})

        whisper_segments = speaker_text
        new_segments, stats = map_whisper_speakers_by_iter(whisper_segments, vtt_segments, tolerance=0.7)


        synchro_link = save_transcription_to_drive(
            new_segments,
            folder_id=os.getenv("SYNCRO_TRANSCRIPTION"),
            base_filename=base_filename
        )
        logger.info(synchro_link)
        await airtable.update_record(record_id, {'Link to synchronized transcription': synchro_link.get("webViewLink")})

        openai_answer = await openai_request(new_segments, base_filename)

        speakers = stats.get("speaker_names")

        meeting_date = extract_meeting_date(base_filename)

        await airtable.update_record(record_id, {'Summury':  openai_answer})

        await airtable.update_record(record_id, {'Speakers': speakers})

        await airtable.update_record(record_id, {'Meeting Date': meeting_date})

        # Удаляем временный аудио файл
        try:
            os.remove(audio_temp_path)
            os.remove( video_path)
            os.remove(teams_path)
        except Exception as e:
            logger.error(f"[Worker] Ошибка удаления временых файлов: {e}")

        # TODO: сохраняем segments и transcript_text в Google Drive и Airtable
        logger.info(f"[Worker] Обработка {video_name} завершена")
        clear_temp_folder(base_filename)
    except Exception as e:
        logger.error(f"[Worker] Ошибка при обработке {file['name']}: {e}")
        clear_temp_folder(base_filename)
