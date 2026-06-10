"""Entity state IO helpers: paths, JSON loading, and atomic persistence writes."""

import json
import os
import shutil
import threading
from pathlib import Path
from typing import Any, Dict

# ============================================================================

DATA_DIR = Path(__file__).parent.parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
ENTITY_CORE_PATH = DATA_DIR / "entity_core.json"


def _json_backup_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".bak")


def _json_corrupt_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".corrupt")


def _load_json_file(path: Path) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path} did not contain a JSON object")
    return data


def _json_default(o: Any) -> Any:
    """
    json.dump 兜底序列化钩子。

    numpy 标量（np.int64/np.float64 等）有 .item()，numpy 数组有 .tolist()，
    都不被 json 原生支持。这里用鸭子类型把它们还原成 python 原生值，
    避免单个 numpy 标量混入 state 就让整次持久化失败。
    """
    item = getattr(o, "item", None)
    if callable(item):
        return o.item()
    tolist = getattr(o, "tolist", None)
    if callable(tolist):
        return o.tolist()
    raise TypeError(f"Object of type {type(o).__name__} is not JSON serializable")


def _atomic_json_dump(data: Dict[str, Any], path: Path) -> None:
    """Write JSON via validate-then-replace so crashes never leave half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(
        f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
    )

    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=_json_default)
        f.flush()
        os.fsync(f.fileno())

    _load_json_file(tmp_path)

    if path.exists():
        try:
            _load_json_file(path)
            shutil.copy2(path, _json_backup_path(path))
        except Exception:
            corrupt_path = _json_corrupt_path(path)
            if not corrupt_path.exists():
                shutil.copy2(path, corrupt_path)

    os.replace(tmp_path, path)

