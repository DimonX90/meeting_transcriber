
from services.airtable_service import AirtableClient
from services.drive_service import list_files_in_folder, get_drive_service, find_matching_transcription, get_file_link
from core.utils import safe_execute
import os
from dotenv import load_dotenv
import asyncio
from core.logger import logger
from services.whisper_service import process_file

load_dotenv()


# Таймаут между проверками (секунды)
POLL_INTERVAL =  int(os.getenv("POLL_INTERVAL"))
POLL_INTERVAL_TRANSCRIPTION = int(os.getenv("POLL_INTERVAL_TRANSCRIPTION"))
# ID папки meetings на Google Drive
MEETINGS_FOLDER_ID = os.getenv("MEETINGS_FOLDER_ID")
MEETINGS_TEAMS_TRANSCRIPTION = os.getenv("MEETINGS_TEAMS_TRANSCRIPTION")


# Очередь новых файлов (просто логируем на этом этапе)
file_queue = []
tasks = set()  # глобальное множество задач
# --- Инициализация объекта Airtable ---
airtable = AirtableClient(
    api_key=os.getenv("AIRTABLE_API_KEY"),
    base_id=os.getenv("AIRTABLE_BASE_ID"),
    table_name=os.getenv("AIRTABLE_TABLE_NAME")
)

async def wait_for_transcription(service, base_filename: str):
    """
    Асинхронно ждёт, пока в папке с транскрипциями появится файл с тем же именем (без расширения).
    """
    logger.info(f"Ожидание транскрипции для файла: {base_filename}")

    while True:
        transcription_file = find_matching_transcription(service, MEETINGS_TEAMS_TRANSCRIPTION, base_filename)
        if transcription_file:
            logger.info(f"Найдена транскрипция для {base_filename}: {transcription_file['name']}")
            return transcription_file
        await asyncio.sleep(POLL_INTERVAL_TRANSCRIPTION)

async def poll_files(service):

    logger.info("Воркер запущен")

    if not service:
        logger.error("Не удалось создать сервис. Выход...")
        return

    seen = set(f['id'] for f in safe_execute(list_files_in_folder, service, MEETINGS_FOLDER_ID))
    logger.info(f"Initial snapshot: {len(seen)} файлов уже в папке — игнорируем их")


    while True:
        files = safe_execute(list_files_in_folder, service, MEETINGS_FOLDER_ID)
        if files:
            for f in files:
                if f['id'] not in seen:
                    seen.add(f['id'])
                    file_queue.append(f)
                    logger.info(f"Новый файл: {f['name']} добавлен в очередь")
                    link_to_video = get_file_link(f['id'])
                    base_filename = os.path.splitext(f['name'])[0]
                    transcription_file = await wait_for_transcription(service, base_filename)
                    link_to_trancription_teams = get_file_link(transcription_file['id'])
                    fields = {
                        "Name": base_filename,
                        "Link to video meeting": link_to_video,
                        "Link to teams transcription": link_to_trancription_teams
                    }
                    logger.info(
                        f"Пара файлов готова: видео = {f['name']}, транскрипт = {transcription_file['name']}"
                    )
                    result = await airtable.create_record(fields)
                    logger.info("Новая запись в Airtable создана")

                    #Добавляем файлы в очередь для обработки
                    while file_queue:
                        f = file_queue.pop(0)
                        task = asyncio.create_task(process_file(f, service, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "temp"))))
                        tasks.add(task)
                        task.add_done_callback(tasks.discard)

        await asyncio.sleep(POLL_INTERVAL)

async def main():
    service = safe_execute(get_drive_service)
    if not service:
        logger.error("Не удалось создать сервис. Выход...")
        return
    await poll_files(service)

if __name__ == "__main__":
    asyncio.run(main())