from pyairtable import Api
from core.logger import logger

class AirtableClient:
    def __init__(self, api_key, base_id, table_name):
        self.api_key = api_key
        self.base_id = base_id
        self.table_name = table_name
        try:
            self.api = Api(self.api_key)  # создаем API-клиент
            self.table = self.api.table(self.base_id, self.table_name)  # объект таблицы
            logger.info("[Airtable] Клиент и таблица успешно инициализированы")
        except Exception as e:
            logger.error(f"[Airtable INIT] Ошибка инициализации: {e}")
            self.table = None

    async def get_records(self, filter_by_formula=None):
        try:
            return self.table.all(formula=filter_by_formula)
        except Exception as e:
            logger.error(f"[Airtable GET] Ошибка получения записей: {e}")
            return []

    async def create_record(self, fields: dict):
        try:
            return self.table.create(fields)
        except Exception as e:
            logger.error(f"[Airtable CREATE] Ошибка создания записи: {e}")
            return None

    async def update_record(self, record_id: str, fields: dict):
        try:
            return self.table.update(record_id, fields)
        except Exception as e:
            logger.error(f"[Airtable UPDATE] Ошибка обновления записи {record_id}: {e}")
            return None

    async def delete_record(self, record_id: str):
        try:
            return self.table.delete(record_id)
        except Exception as e:
            logger.error(f"[Airtable DELETE] Ошибка удаления записи {record_id}: {e}")
            return None
