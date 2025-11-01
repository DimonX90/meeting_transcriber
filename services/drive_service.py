import logging
from core.logger import logger
from googleapiclient.http import MediaIoBaseDownload
from googleapiclient.discovery import build
from google.oauth2 import service_account
from core.utils import get_env_file_path, safe_execute
import os
from dotenv import load_dotenv

load_dotenv()

SERVICE_ACCOUNT_JSON = get_env_file_path("SERVICE_ACCOUNT_FILE")



def get_drive_service():
    """Создаём клиент Google Drive API"""
    try:
        creds = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_JSON,
        scopes=["https://www.googleapis.com/auth/drive"]
        )
        service = build("drive", "v3", credentials=creds)
        return service
    except Exception as e:
        logger.error(f"[Drive] Ошибка создания сервиса: {e}")
        return None


def list_files_in_folder(service, folder_id: str):
    """Получить список файлов в папке Google Drive, используя существующий сервис"""
    try:
        if not service:
            logging.error("[Drive] Сервис не инициализирован")
            return []
        query = f"'{folder_id}' in parents and trashed = false"
        results = service.files().list(q=query, fields="files(id, name)").execute()
        return results.get("files", [])
    except Exception as e:
        logger.error(f"[Drive] Ошибка при получении файлов: {e}")
        return []


def find_matching_transcription(service, transcription_folder_id: str, base_filename: str):
    """
    Ищет файл в папке транскрипций, у которого совпадает имя без расширения.
    """
    files = safe_execute(list_files_in_folder, service, transcription_folder_id)
    if not files:
        return None

    for f in files:
        name_without_ext = os.path.splitext(f["name"])[0]
        if name_without_ext == base_filename:
            return f
    return None

def get_file_link(file_id: str) -> str:
    """
    Возвращает прямую ссылку на файл Google Drive по его ID
    """
    return f"https://drive.google.com/file/d/{file_id}/view?usp=sharing"


def download_file_to_path(file_id: str, destination_path: str):
    """Скачивает файл с Google Drive по ID в указанный путь"""
    try:
        # Создаём директорию, если её нет
        os.makedirs(os.path.dirname(destination_path), exist_ok=True)
        service = get_drive_service()
        request = service.files().get_media(fileId=file_id)
        with open(destination_path, "wb") as f:
            downloader = MediaIoBaseDownload(f, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
        return True
    except Exception as e:
        logger.error(f"[Drive] Ошибка скачивания файла {file_id}: {e}")
        return False


