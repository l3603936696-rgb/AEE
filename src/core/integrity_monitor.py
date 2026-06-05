"""
integrity_monitor.py — 完整性监控器

每 tick 扫描四个区域，对比上次快照，生成变化事件列表。
输出中不含技术细节（无文件名/路径），只有 zone 和 change_magnitude。
"""

import hashlib
import json
import sqlite3
from pathlib import Path

_PERCEPTION_FILES = [
    "src/pipeline_runner/__init__.py",
    "src/daemon/daemon.py",
    "src/action_system/executor.py",
]


def _clamp(val: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, val))


def _md5_file(path: Path) -> str:
    try:
        h = hashlib.md5()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def _scan_expression(data_dir: Path, prev: dict) -> tuple[dict, float]:
    voice_dir = data_dir / "xia_voice"
    try:
        files: dict[str, int] = {
            f.name: f.stat().st_size
            for f in voice_dir.iterdir()
            if f.suffix == ".txt"
        }
    except Exception:
        files = {}

    prev_files = prev.get("expression", {})
    prev_count = len(prev_files)
    curr_count = len(files)

    deleted_ratio = max(0.0, prev_count - curr_count) / max(1, prev_count)
    added_ratio   = max(0.0, curr_count - prev_count) / max(1, prev_count)
    magnitude = _clamp(deleted_ratio * 1.0 + added_ratio * 0.3)
    return files, magnitude


def _scan_perception(src_root: Path, prev: dict) -> tuple[dict, float]:
    hashes: dict[str, str] = {}
    for rel in _PERCEPTION_FILES:
        hashes[rel] = _md5_file(src_root / rel)

    prev_hashes = prev.get("perception", {})
    total = len(_PERCEPTION_FILES)
    changed = sum(
        1 for rel in _PERCEPTION_FILES
        if hashes.get(rel) != prev_hashes.get(rel, "")
    )
    magnitude = changed / max(1, total)
    return hashes, magnitude


def _scan_cognition(data_dir: Path, prev: dict) -> tuple[dict, float]:
    wm_path = data_dir / "world_model_db.json"
    try:
        size = wm_path.stat().st_size
        md5  = _md5_file(wm_path)
    except Exception:
        size = 0
        md5  = ""

    snapshot = {"size": size, "md5": md5}
    prev_snap = prev.get("cognition", {})
    prev_size = prev_snap.get("size", 0)

    magnitude = _clamp(abs(size - prev_size) / max(1, prev_size))
    return snapshot, magnitude


def _scan_continuity(data_dir: Path, prev: dict) -> tuple[dict, float]:
    episodes_db = data_dir / "episodes.db"
    core_path   = data_dir / "entity_core.json"

    try:
        with sqlite3.connect(str(episodes_db)) as conn:
            row = conn.execute("SELECT COUNT(*) FROM episodes").fetchone()
            episode_count = int(row[0]) if row else 0
    except Exception:
        episode_count = 0

    try:
        core_size = core_path.stat().st_size
    except Exception:
        core_size = 0

    snapshot = {"episode_count": episode_count, "core_size": core_size}
    prev_snap    = prev.get("continuity", {})
    prev_count   = prev_snap.get("episode_count", 0)
    prev_core    = prev_snap.get("core_size", 0)

    episode_loss = _clamp((prev_count - episode_count) / max(1, prev_count))
    core_change  = _clamp(abs(core_size - prev_core) / max(1, prev_core))
    magnitude    = _clamp(episode_loss * 0.8 + core_change * 0.2)
    return snapshot, magnitude


def _load_snapshot(data_dir: Path) -> dict:
    """加载上次快照，不存在时返回空字典。"""
    snap_path = data_dir / "integrity_snapshot.json"
    try:
        with open(snap_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_snapshot(data_dir: Path, snapshot: dict) -> None:
    """保存当前快照。写失败时静默忽略。"""
    snap_path = data_dir / "integrity_snapshot.json"
    try:
        with open(snap_path, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def scan(data_dir: Path, src_root: Path, current_tick: int) -> list[dict]:
    """扫描所有区域，返回变化事件列表。无变化时返回空列表。

    第一次运行（无快照）时不生成任何事件——正常初始化行为。
    """
    prev     = _load_snapshot(data_dir)
    has_prev = float(bool(prev))  # 0.0 首次运行（无快照），不生成任何事件

    expr_snap, expr_mag = _scan_expression(data_dir, prev)
    perc_snap, perc_mag = _scan_perception(src_root, prev)
    cogn_snap, cogn_mag = _scan_cognition(data_dir, prev)
    cont_snap, cont_mag = _scan_continuity(data_dir, prev)

    expr_mag *= has_prev
    perc_mag *= has_prev
    cogn_mag *= has_prev
    cont_mag *= has_prev

    _save_snapshot(data_dir, {
        "expression": expr_snap,
        "perception": perc_snap,
        "cognition":  cogn_snap,
        "continuity": cont_snap,
    })

    events = []
    for zone, magnitude in (
        ("expression", expr_mag),
        ("perception", perc_mag),
        ("cognition",  cogn_mag),
        ("continuity", cont_mag),
    ):
        if magnitude > 0.0:
            events.append({
                "zone":             zone,
                "change_magnitude": float(magnitude),
                "tick":             current_tick,
            })

    return events
