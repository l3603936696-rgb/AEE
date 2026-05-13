"""
probe_logger.py — 探针日志写入器

独立日志文件（JSONL），不进入 episodes 经验池。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ============================================================================
# 默认路径（可通过环境变量覆盖）
# ============================================================================

DEFAULT_LOG_DIR = Path(__file__).parent.parent.parent / "logs"
DEFAULT_LOG_FILE = DEFAULT_LOG_DIR / "counterfactual_probe.jsonl"


# ============================================================================
# ProbeLogger
# ============================================================================

class ProbeLogger:
    """
    反事实探针日志写入器。

    写入格式：JSONL（每行一条 JSON）。
    文件不存在时自动创建，目录不存在时自动创建。
    """

    def __init__(
        self,
        log_path: Optional[Path] = None,
        max_mb: float = 10.0,
    ):
        """
        参数：
            log_path : 日志文件路径（默认 logs/counterfactual_probe.jsonl）
            max_mb   : 文件大小上限（超过则截断旧内容）
        """
        self.log_path = Path(log_path) if log_path else DEFAULT_LOG_FILE
        self.max_bytes = int(max_mb * 1024 * 1024)
        self._ensure_dir()

    def _ensure_dir(self) -> None:
        """确保日志目录存在。"""
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ #
    # 核心写入接口
    # ------------------------------------------------------------------ #

    def log(
        self,
        tick: int,
        counterfactual_report: Dict[str, Any],
        trend_report: Optional[Dict[str, Any]] = None,
        profile_report: Optional[Dict[str, Any]] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        将一条探针记录追加到日志文件。

        参数：
            tick                  : 当前 tick
            counterfactual_report : run_counterfactual_probe 的返回值
            trend_report         : compute_trend 的返回值（可选）
            profile_report       : compute_profile 的返回值（可选）
            extra                : 额外字段（可选，如 connection_trace 等）
        """
        entry: Dict[str, Any] = {
            "timestamp": datetime.now().isoformat(timespec="milliseconds"),
            "tick": tick,
            "counterfactual": counterfactual_report,
        }

        if trend_report is not None:
            entry["trend"] = trend_report

        if profile_report is not None:
            entry["profile"] = profile_report

        if extra is not None:
            entry["extra"] = extra

        self._append_entry(entry)

    def log_batch(
        self,
        records: List[Dict[str, Any]],
    ) -> None:
        """
        批量追加多条探针记录。

        参数：
            records : [{"tick": ..., "counterfactual": ...}, ...]
        """
        for rec in records:
            ts = datetime.now().isoformat(timespec="milliseconds")
            entry = dict(rec)
            if "timestamp" not in entry:
                entry["timestamp"] = ts
            self._append_entry(entry)

    # ------------------------------------------------------------------ #
    # 低层操作
    # ------------------------------------------------------------------ #

    def _append_entry(self, entry: Dict[str, Any]) -> None:
        """将一条 JSON 记录追加到文件末尾。"""
        self._check_size()
        try:
            line = json.dumps(entry, ensure_ascii=False)
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception as e:
            logger.warning(f"[ProbeLogger] Failed to write log entry: {e}")

    def _check_size(self) -> None:
        """文件超过 max_bytes 时截断到一半。"""
        try:
            if self.log_path.exists():
                size = self.log_path.stat().st_size
                if size > self.max_bytes:
                    self._rotate()
        except Exception as e:
            logger.debug(f"[ProbeLogger] Size check skipped: {e}")

    def _rotate(self) -> None:
        """将文件前一半保留，后一半丢弃（简单轮转）。"""
        try:
            with open(self.log_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            keep = lines[len(lines) // 2:]
            with open(self.log_path, "w", encoding="utf-8") as f:
                f.writelines(keep)
            logger.info(f"[ProbeLogger] Rotated log, kept {len(keep)} entries")
        except Exception as e:
            logger.warning(f"[ProbeLogger] Rotation failed: {e}")

    # ------------------------------------------------------------------ #
    # 查询接口（只读）
    # ------------------------------------------------------------------ #

    def read_recent(self, n: int = 10) -> List[Dict[str, Any]]:
        """
        读取最近 n 条探针记录。

        参数：
            n : 返回条数

        返回：
            List[Dict] — 每条含 tick, counterfactual 等字段
        """
        if not self.log_path.exists():
            return []

        try:
            with open(self.log_path, "r", encoding="utf-8") as f:
                all_lines = f.readlines()
            records = []
            for line in all_lines[-n:]:
                try:
                    records.append(json.loads(line.strip()))
                except json.JSONDecodeError:
                    continue
            return records
        except Exception:
            return []

    def read_by_tick(self, tick: int) -> Optional[Dict[str, Any]]:
        """按 tick 查找单条记录（倒序扫描，最近优先）。"""
        if not self.log_path.exists():
            return None
        try:
            with open(self.log_path, "r", encoding="utf-8") as f:
                for line in reversed(f.readlines()):
                    try:
                        rec = json.loads(line.strip())
                        if rec.get("tick") == tick:
                            return rec
                    except json.JSONDecodeError:
                        continue
        except Exception:
            pass
        return None

    def read_analysis_summary(self, last_n: int = 50) -> Dict[str, Any]:
        """
        读取最近 N 条记录，聚合分析。

        返回：
            {
                "dominant_distortions": Dict[str, int],  # 各标签出现次数
                "interpretations": Dict[str, int],        # 各解释出现次数
                "avg_connection_depth": float,
                "risk_flag_count": int,
            }
        """
        records = self.read_recent(last_n)
        if not records:
            return {}

        dom_counts: Dict[str, int] = {}
        interp_counts: Dict[str, int] = {}
        conn_depths: List[float] = []
        risk_count = 0

        for rec in records:
            cf = rec.get("counterfactual", {})
            analysis = cf.get("analysis", {})
            trend = rec.get("trend", {})

            dom = analysis.get("dominant_distortion", "unknown")
            dom_counts[dom] = dom_counts.get(dom, 0) + 1

            for interp in analysis.get("interpretations", []):
                interp_counts[interp] = interp_counts.get(interp, 0) + 1

            conn_depths.append(cf.get("baseline", {}).get("connection_depth", 0.0))

            if trend.get("risk_flags"):
                risk_count += len(trend["risk_flags"])

        return {
            "dominant_distortions": dom_counts,
            "interpretations": interp_counts,
            "avg_connection_depth": round(sum(conn_depths) / len(conn_depths), 4) if conn_depths else 0.0,
            "risk_flag_count": risk_count,
            "records_count": len(records),
        }


# ============================================================================
# 全局单例（懒加载）
# ============================================================================

_probe_logger_instance: Optional[ProbeLogger] = None


def get_probe_logger() -> ProbeLogger:
    """获取全局探针日志写入器单例。"""
    global _probe_logger_instance
    if _probe_logger_instance is None:
        log_path_str = Path(__file__).parent.parent.parent / "logs" / "counterfactual_probe.jsonl"
        _probe_logger_instance = ProbeLogger(log_path=log_path_str)
    return _probe_logger_instance
