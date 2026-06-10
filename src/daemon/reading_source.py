"""
阅读源 — explore 行为的本地信息输入

当 explore 触发时，根据实体当前状态选择最共鸣的文件，
读取一段文本，送入 reading_acquisition 管线提取候选词汇。

不用 LLM，不联网。信息来源：
    1. data/library/   — 用户放的阅读材料（优先）
    2. data/xia_voice/ — 自己过去写的东西（回顾）

选书逻辑：
    不是随机选——是状态驱动。
    累的时候被"疲惫"描写吸引，好奇的时候被"探索"段落吸引。
    采样每个文件的几个片段，算和当前状态的共鸣分，按共鸣加权选择。

用法：
    chunk = pick_and_read(data_dir, entity_state)
"""

import json
import logging
import random
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# 每次读取的字符数范围
_CHUNK_MIN = 200
_CHUNK_MAX = 600

# 采样参数：每个文件取几个探针来评估共鸣度
_PROBE_COUNT = 3
_PROBE_SIZE = 150

# 顺序游标：记录每本书的阅读位置
_CURSOR_FILENAME = "reading_cursor.json"


def pick_and_read(
    data_dir: Path,
    entity_state: Any = None,
) -> Optional[dict]:
    """
    根据实体状态选书、选段落。

    返回:
        {"text": str, "source": str, "file": str, "offset": int}
        或 None（无可读内容）
    """
    sources = _collect_sources(data_dir)
    if not sources:
        return None

    # 状态驱动选书
    if entity_state is not None and len(sources) > 1:
        source_name, file_path = _state_driven_pick(sources, entity_state)
    else:
        source_name, file_path = random.choice(sources)

    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        logger.debug(f"[ReadSource] Failed to read {file_path}: {e}")
        return None

    if len(content) < 20:
        return None

    # 顺序游标读取（替代随机偏移）
    chunk_size = random.randint(_CHUNK_MIN, _CHUNK_MAX)
    content_len = len(content)
    max_offset = max(0, content_len - chunk_size)

    cursors = _load_cursors(data_dir)
    file_key = file_path.name
    cursor = cursors.get(file_key, 0)
    # 游标超出有效范围时回绕（文件被截短时的安全保障）
    offset = cursor % max(1, max_offset + 1)

    text = content[offset : offset + chunk_size]

    # 前进游标并持久化
    cursors = _advance_cursor(cursors, file_key, offset, chunk_size, content_len)
    _save_cursors(data_dir, cursors)

    progress_pct = offset / max(1, content_len) * 100
    logger.info(
        f"[ReadSource] Read {len(text)} chars from {source_name}/{file_path.name} "
        f"(offset={offset}, {progress_pct:.1f}%)"
    )

    return {
        "text": text,
        "source": source_name,
        "file": file_path.name,
        "offset": offset,
        "progress_pct": round(progress_pct, 1),
    }


# ============================================================================
# 顺序游标：每本书记一个读取位置，不随机跳跃
# ============================================================================

def _load_cursors(data_dir: Path) -> Dict[str, int]:
    """加载所有文件的阅读游标（文件名 → 字符偏移量）。"""
    try:
        return json.loads((data_dir / _CURSOR_FILENAME).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cursors(data_dir: Path, cursors: Dict[str, int]) -> None:
    """持久化游标 dict。写失败时静默忽略（不影响主流程）。"""
    try:
        (data_dir / _CURSOR_FILENAME).write_text(
            json.dumps(cursors, ensure_ascii=False, indent=None),
            encoding="utf-8",
        )
    except Exception:
        pass


def _advance_cursor(cursors: Dict[str, int], file_key: str, offset: int,
                    chunk_size: int, content_len: int) -> Dict[str, int]:
    """
    前进游标：offset + chunk_size，超出文件长度时回绕到 0（顺序循环阅读）。
    纯数学，无 if-else。
    """
    next_pos = (offset + chunk_size) % max(1, content_len)
    cursors[file_key] = next_pos
    return cursors


# ============================================================================
# 状态驱动选书
# ============================================================================

# 锚点字 → 影响的主要维度（简化版，不引入 somatic_concept_map 的依赖）
_ANCHOR_DIMS: Dict[str, str] = {
    "冷": "avoid_drive", "热": "approach_drive", "痛": "stress",
    "软": "serenity", "硬": "stress", "湿": "fatigue",
    "干": "fatigue", "重": "fatigue", "轻": "joy",
    "饿": "energy", "渴": "energy", "累": "fatigue",
    "困": "fatigue", "舒": "serenity", "静": "serenity",
    "快": "excitement", "慢": "serenity", "紧": "anxiety",
    "松": "serenity", "麻": "anxiety", "胀": "stress",
    "晕": "fatigue", "烫": "fear", "凉": "serenity",
    "僵": "fatigue", "闷": "sadness", "慌": "fear",
    "抖": "fear", "沉": "sadness", "飘": "joy",
    "刺": "stress", "堵": "anxiety", "跳": "anxiety",
    "烧": "fear", "压": "stress", "空": "sadness",
    "酥": "serenity", "乏": "fatigue",
    "怒": "anger", "哭": "sadness", "笑": "joy",
    "吼": "anger", "颤": "fear", "喘": "fatigue",
    "汗": "stress", "酸": "fatigue", "胸": "anxiety",
    "血": "fear", "寒": "fear", "暖": "serenity",
    "苦": "sadness", "甜": "joy", "臭": "disgust",
    "香": "approach_drive", "黑": "fear", "亮": "curiosity",
}


def _resonance_score(text: str, state: Dict[str, float]) -> float:
    """
    计算一段文本与实体状态的共鸣分。

    原理：文本里出现的锚点字指向某些维度，
    如果实体当前那些维度值高（偏离中性），共鸣就强。
    """
    score = 0.0
    seen = set()
    for char in text:
        if char in seen:
            continue
        dim = _ANCHOR_DIMS.get(char)
        if dim:
            seen.add(char)
            # 维度值越偏离 0，共鸣越强
            val = abs(state.get(dim, 0.0))
            score += val
    return score


def _get_state_dict(entity_state: Any) -> Dict[str, float]:
    """从 entity 提取状态 dict。"""
    if isinstance(entity_state, dict):
        return entity_state
    result = {}
    for field in [
        "energy", "fatigue", "stress", "anxiety", "sadness", "joy",
        "fear", "anger", "serenity", "excitement", "curiosity",
        "approach_drive", "avoid_drive", "disgust", "loneliness",
    ]:
        val = getattr(entity_state, field, None)
        if val is not None:
            result[field] = float(val)
    return result


def _state_driven_pick(
    sources: List[Tuple[str, Path]],
    entity_state: Any,
) -> Tuple[str, Path]:
    """
    按 (状态共鸣 + 品味匹配) 加权随机选文件。

    两个信号叠加：
        1. 状态共鸣 — 当前状态下哪些文本"应景"
        2. 品味偏好 — 历史上哪种风格对她有效（学到的偏好）

    不是确定性的——加了底分，确保每本书都有机会。
    """
    state = _get_state_dict(entity_state)
    if not state:
        return random.choice(sources)

    # 尝试获取品味评分
    try:
        from .reading_taste import taste_score
        _has_taste = True
    except Exception:
        _has_taste = False

    scores: List[float] = []

    for source_name, file_path in sources:
        try:
            size = file_path.stat().st_size
            if size < 50:
                scores.append(0.1)
                continue

            # 读几个探针
            total_resonance = 0.0
            total_taste = 0.0
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                content_len = f.seek(0, 2)  # seek to end
                for _ in range(_PROBE_COUNT):
                    probe_offset = random.randint(0, max(0, content_len - _PROBE_SIZE))
                    f.seek(probe_offset)
                    probe = f.read(_PROBE_SIZE)
                    total_resonance += _resonance_score(probe, state)
                    if _has_taste:
                        total_taste += taste_score(entity_state, probe)

            avg_resonance = total_resonance / _PROBE_COUNT
            avg_taste = total_taste / _PROBE_COUNT if _has_taste else 0.0

            # 综合分 = 状态共鸣(70%) + 品味偏好(30%) + 底分
            combined = avg_resonance * 0.7 + avg_taste * 0.3 + 0.1
            scores.append(combined)

        except Exception:
            scores.append(0.1)

    # 加权随机选择
    total = sum(scores)
    if total <= 0:
        return random.choice(sources)

    r = random.random() * total
    cumulative = 0.0
    for i, s in enumerate(scores):
        cumulative += s
        if r <= cumulative:
            logger.debug(
                f"[ReadSource] Picked {sources[i][1].name} "
                f"(score={scores[i]:.2f}/{total:.2f})"
            )
            return sources[i]

    return sources[-1]


# ============================================================================
# 文件收集
# ============================================================================

def _collect_sources(data_dir: Path) -> list:
    """收集所有可读的 (source_name, file_path) 对。

    library 优先：70% 概率选 library，30% 选 voice。
    """
    library_files = []
    voice_files = []

    # 1. library — 用户放的材料（新信息来源）
    library_dir = data_dir / "library"
    if library_dir.is_dir():
        for f in library_dir.iterdir():
            if f.is_file() and f.suffix in {".txt", ".md", ".log"}:
                library_files.append(("library", f))

    # 2. xia_voice — 自己的过往写作（回顾）
    voice_dir = data_dir / "xia_voice"
    if voice_dir.is_dir():
        voice_all = [f for f in voice_dir.iterdir() if f.is_file() and f.suffix == ".txt"]
        # 只取最近 20 个（避免扫描数千文件）
        voice_all.sort(key=lambda f: f.stat().st_mtime, reverse=True)
        for f in voice_all[:20]:
            voice_files.append(("voice", f))

    # 分组选择：有 library 时 70% 选 library
    if library_files and voice_files:
        if random.random() < 0.7:
            return library_files
        else:
            return voice_files
    elif library_files:
        return library_files
    else:
        return voice_files
