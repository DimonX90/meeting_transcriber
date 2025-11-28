import re
from typing import List, Dict, Tuple
from core.logger import logger

def time_to_seconds(t: str) -> float:
    """Convert 'HH:MM:SS.mmm' (or 'MM:SS.mmm') to seconds (float)."""
    try:
        parts = t.strip().split(":")
        parts = [p for p in parts if p != ""]
        if len(parts) == 3:
            h, m, s = parts
            return int(h) * 3600 + int(m) * 60 + float(s)
        elif len(parts) == 2:
            m, s = parts
            return int(m) * 60 + float(s)
        else:
            return float(parts[0])
    except Exception as e:
        logger.warning(f"[time_to_seconds] cannot parse '{t}': {e}")
        return 0.0


def parse_vtt_text(vtt_text: str) -> List[Dict]:
    """
    Parse VTT text and return list of segments:
    [{ "start": float_seconds, "end": float_seconds, "speaker": str, "text": str }, ...]
    """
    try:
        if not vtt_text or not isinstance(vtt_text, str):
            logger.error("[parse_vtt_text] empty or invalid vtt_text")
            return []

        segments = []
        lines = vtt_text.splitlines()
        curr_start = curr_end = None

        # simple stateful parse: find time lines then next <v ...> line(s)
        for i, raw in enumerate(lines):
            line = raw.strip()
            if "-->" in line:
                # parse times
                try:
                    start_s, end_s = line.split("-->")
                    curr_start = time_to_seconds(start_s.strip())
                    curr_end = time_to_seconds(end_s.strip())
                except Exception as e:
                    logger.warning(f"[parse_vtt_text] bad time line '{line}': {e}")
                    curr_start = curr_end = None
            elif line.startswith("<v "):
                # <v Name>text</v>  (sometimes text may be on next line(s) but many Teams VTTs have single-line)
                try:
                    # extract speaker
                    m = re.match(r"<v\s+([^>]+)>(.*)</v>?$", line, re.DOTALL)
                    if m:
                        speaker = m.group(1).strip()
                        text = m.group(2).strip()
                    else:
                        # fallback: split at first '>' char
                        after = line[3:]
                        sp, rest = after.split(">", 1)
                        speaker = sp.strip()
                        text = rest.replace("</v>", "").strip()
                    if curr_start is not None and curr_end is not None:
                        segments.append({
                            "start": float(curr_start),
                            "end": float(curr_end),
                            "speaker": speaker,
                            "text": text
                        })
                        # reset times to avoid accidental reuse
                        curr_start = curr_end = None
                except Exception as e:
                    logger.warning(f"[parse_vtt_text] can't parse speaker line '{line}': {e}")
                    continue
            else:
                # sometimes Teams puts text on next line after time; try to capture that
                # if previous time exists and next line is a speaker line without <v ...> (rare), skip
                continue

        if not segments:
            logger.warning("[parse_vtt_text] no segments found in VTT")
        return segments

    except Exception as e:
        logger.error(f"[parse_vtt_text] critical error: {e}")
        return []



def _to_float(x):
    """Удобная конвертация на случай np.float64 и т.п."""
    try:
        return float(x)
    except Exception:
        return 0.0

def _overlap(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    """Длительность пересечения двух интервалов (в секундах)."""
    s = max(a_start, b_start)
    e = min(a_end, b_end)
    return max(0.0, e - s)

def map_whisper_speakers_by_iter(
    whisper_segments: List[Dict],
    vtt_segments: List[Dict],
    tolerance: float = 0.7,
    min_overlap_for_match: float = 0.02
) -> Tuple[List[Dict], Dict]:
    """
    Итеративно проходим по каждому уникальному SPEAKER_* из whisper_segments,
    ищем первое подходящее совпадение в vtt_segments (по времени + tolerance),
    и при нахождении — заменяем имя во всех whisper_segments.

    Возвращает (new_whisper_segments, stats)
    stats = {
        "mapping": { "SPEAKER_00": "Real Name", ... },
        "matched": int,
        "total_speakers": int,
        "unmatched_speakers": [...],
    }
    Параметры:
      - tolerance: сколько секунд "подтолкнуть" vtt-интервал при проверке пересечения.
      - min_overlap_for_match: минимальная длительность пересечения, чтобы считать совпадением (в сек).
    """
    try:
        if not isinstance(whisper_segments, list):
            logger.error("[sync_iter] whisper_segments must be list")
            return whisper_segments, {}

        if not isinstance(vtt_segments, list) or not vtt_segments:
            logger.warning("[sync_iter] vtt_segments empty — ничего не будет заменено")
            return whisper_segments, {"mapping": {}, "matched": 0, "total_speakers": 0, "unmatched_speakers": []}

        # Список уникальных SPEAKER_* в порядке первого появления
        speaker_order = []
        speaker_names = []
        for seg in whisper_segments:
            sp = seg.get("speaker")
            if sp not in speaker_order:
                speaker_order.append(sp)

        mapping = {}
        matched_count = 0

        # Преобразуем vtt_segments в нормализованный список (float times)
        vtt = []
        for vs in vtt_segments:
            try:
                vtt.append({
                    "start": float(vs["start"]),
                    "end": float(vs["end"]),
                    "speaker": vs.get("speaker") or "Unknown",
                })
            except Exception:
                continue

        # Для каждого SPEAKER_* последовательно ищем подходящее имя
        for sp in speaker_order:
            # Собираем все сегменты, принадлежащие этому SPEAKER
            sp_segments = [s for s in whisper_segments if s.get("speaker") == sp]
            if not sp_segments:
                continue

            # Для каждого сегмента ищем пересекающиеся VTT отрезки — аккумулируем кандидатов
            candidate_scores = {}  # name -> total_overlap (or count)
            for s in sp_segments:
                w_start = _to_float(s.get("start", 0.0))
                w_end = _to_float(s.get("end", 0.0))
                for vs in vtt:
                    v_start = vs["start"]
                    v_end = vs["end"]
                    # проверяем пересечение с расширением vtt интервала на tolerance
                    if (v_end + tolerance) < w_start or (v_start - tolerance) > w_end:
                        continue
                    overlap = _overlap(w_start, w_end, v_start, v_end)
                    if overlap >= min_overlap_for_match:
                        name = vs["speaker"]
                        candidate_scores.setdefault(name, 0.0)
                        candidate_scores[name] += overlap  # суммируем длительность пересечения

            # Если есть кандидаты — выберем тот с максимальным суммарным overlap
            if candidate_scores:
                best_name = max(candidate_scores.items(), key=lambda x: x[1])[0]
                mapping[sp] = best_name
                matched_count += 1
                speaker_names.append(best_name)

                # Заменяем имя во всех сегментах whisper_segments
                for seg in whisper_segments:
                    if seg.get("speaker") == sp:
                        seg["speaker"] = best_name
            else:
                # не нашли для этого SPEAKER подходящего VTT имени
                mapping[sp] = None

        # Соберём статистику
        total_speakers = len(speaker_order)
        unmatched = [k for k, v in mapping.items() if v is None]
        stats = {
            "mapping": mapping,
            "matched": sum(1 for v in mapping.values() if v),
            "total_speakers": total_speakers,
            "speaker_names": speaker_names,
            "unmatched_speakers": unmatched
        }

        logger.info(f"[sync_iter] mapped {stats['matched']}/{total_speakers} speakers")
        return whisper_segments, stats

    except Exception as e:
        logger.error(f"[sync_iter] unexpected error: {e}")
        return whisper_segments, {}
