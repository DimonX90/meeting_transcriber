import os

from core.logger import logger
from openai import AsyncOpenAI




def build_meeting_summary_prompt(transcription_segments, meeting_title=None, max_chars=12000):
    """
    Формирует текст запроса (prompt_text) для OpenAI на основе расшифровки встречи.

    Аргументы:
        transcription_segments: List[Dict] — расшифровка с реальными именами спикеров.
        meeting_title: str | None — необязательное название встречи.
        max_chars: int — ограничение длины текста для защиты от переполнения токенов.

    Возвращает:
        str — готовый prompt_text на украинском языке.
    """
    try:
        # Собираем читаемую транскрипцию
        dialogue_lines = []
        for seg in transcription_segments:
            start = seg.get("start", "")
            speaker = seg.get("speaker", "Невідомий спікер")
            text = seg.get("text", "").strip()
            if text:
                dialogue_lines.append(f"[{speaker}]: {text}")

        # Если слишком длинная транскрипция — обрежем по символам
        full_text = "\n".join(dialogue_lines)
        if len(full_text) > max_chars:
            full_text = full_text[:max_chars] + "\n..."

        # Собираем заголовок (если есть)
        title_line = f"Назва зустрічі: {meeting_title}\n\n" if meeting_title else ""

        # Финальный промпт
        prompt = (
            f"{title_line}"
            "На основі наведеної нижче розшифровки зустрічі, зроби короткий підсумок українською мовою.\n"
            "Опиши:\n"
            "1️⃣ Основні теми, які обговорювалися.\n"
            "2️⃣ Які висновки зробили учасники.\n"
            "3️⃣ Чи були прийняті якісь рішення або домовленості.\n"
            "4️⃣ Якщо були завдання або наступні кроки — переліч їх.\n\n"
            "Розшифровка:\n"
            f"{full_text}\n\n"
            "Формат відповіді: короткий структурований підсумок з підзаголовками."
        )

        return prompt

    except Exception as e:
       logger.error(f"[build_meeting_summary_prompt] Помилка при створенні промпта: {e}")
       logger.info(f"[build_meeting_summary_prompt] Помилка при створенні промпта: {e}")
       return None


async  def openai_request(transcription_segments, base_filename):
    prompt_text= build_meeting_summary_prompt(transcription_segments, base_filename)

    client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    try:
        response = await client.chat.completions.create(
            model="gpt-4-0125-preview",
            messages=[{"role": "user", "content": prompt_text}],
            temperature=0.7,
            max_tokens=4096
        )
    except Exception as e:
       logger.error(f"[openai_request] Ошибка при запросе OpenAi: {e}")
       logger.info(f"[openai_request] Ошибка при запросе OpenAi: {e}")
       return None
    summary = response.choices[0].message.content

    return summary