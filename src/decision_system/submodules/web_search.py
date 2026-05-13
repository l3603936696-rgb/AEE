"""
9. WebSearch (联网搜索)

v3 改造：

职责：
    - 判断当前情境是否需要联网搜索
    - perceive() 时：搜索结果本身不影响驱动力（搜索是工具，不是感受）

注意：WebSearch 在 v3 管线中实际上不参与九模块并行感知，
      它的搜索结果通过 thought_packet["web_search_results"] 传递。
      perceive() 方法存在但为空实现（搜索结果不在此处理）。
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, List, Dict, Optional

from .base import DriveSignal, _clamp, _get_somatic_weight

logger = logging.getLogger(__name__)

# ============================================================================
# 搜索词生成器
# ============================================================================

def _build_search_query(
    semantic_packet_biased: dict,
    concept_tags: List[dict],
    wm_context: dict,
    state_snapshot: dict,
) -> Optional[str]:
    """
    根据当前上下文生成搜索词。

    优先级：
        1. 用户输入中的实体/关键词
        2. concept_tags 中的标签
        3. world_model 中未命中的标签（missed_tags）
        4. 状态描述（energy 低时的"如何恢复能量"等）
    """
    parts: list[str] = []

    # 从用户输入中提取（最优先）
    raw_input = semantic_packet_biased.get("raw_input") or semantic_packet_biased.get("intent", "")
    if raw_input and isinstance(raw_input, str) and len(raw_input.strip()) >= 2:
        intent = semantic_packet_biased.get("intent", "")
        intensity = float(semantic_packet_biased.get("intensity", 0.0))
        # 问句 / 求助意图 → 直接用原始输入作为搜索词
        if intent in ("求助", "指令") and intensity > 0.5:
            cleaned = raw_input.strip()
            if len(cleaned) <= 60:
                return cleaned
            # 截取前 60 字
            return cleaned[:60]

    # 从 concept_tags 提取
    tag_keywords: list[str] = []
    for tag in (concept_tags or []):
        if isinstance(tag, dict):
            t = tag.get("tag", "")
            if t and len(t) <= 20:
                tag_keywords.append(t)
    if tag_keywords:
        parts.extend(tag_keywords[:3])

    # 从 wm_context missed_tags 提取
    missed = wm_context.get("coverage", {}).get("missed_tags", []) if isinstance(wm_context, dict) else []
    for m in (missed or [])[:3]:
        if m and m not in parts:
            parts.append(str(m))

    # 从 state_snapshot 推断
    state = state_snapshot or {}
    if state.get("energy", 0.8) < 0.3:
        parts.append("恢复精力方法")
    if state.get("loneliness", 0.3) > 0.7:
        parts.append("缓解孤独感")

    if not parts:
        return None

    return " ".join(parts[:5])


# ============================================================================
# 异步搜索包装（避免阻塞裁决）
# ============================================================================

class _AsyncSearchRunner:
    """
    在独立线程中执行搜索，避免阻塞裁决主流程。
    结果通过 shared container 传递。
    """

    def __init__(self, query: str, num_results: int, timeout: float, backend: Optional[str]):
        self.query = query
        self.num_results = num_results
        self.timeout = timeout
        self.backend = backend
        self.results: List[Dict[str, Any]] = []
        self._done = False
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """启动搜索线程（立即返回）"""
        def _run():
            try:
                # 延迟导入，避免顶层循环导入
                from net.search_engine import search_web as _sw
                raw_results = _sw(
                    query=self.query,
                    num_results=self.num_results,
                    timeout_seconds=self.timeout,
                    preferred_backend=self.backend,
                )
                self.results = [r.to_dict() for r in raw_results]
            except Exception as e:
                logger.warning(f"[WebSearch] 搜索异常: {e}")
                self.results = []
            finally:
                self._done = True

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()

    def is_done(self) -> bool:
        return self._done

    def get_results(self) -> List[Dict[str, Any]]:
        return self.results


# ============================================================================
# WebSearch 模块
# ============================================================================

class WebSearch:

    # =========================================================================
    # v3 新接口：perceive() — 直接修改 EntityCore
    # =========================================================================

    def perceive(self, inputs: dict, entity_core: Any) -> None:
        """
        WebSearch 不直接修改驱动力——联网是工具性行为，不是感受。
        """
        pass

    # =========================================================================
    # 旧接口：evaluate() — 向后兼容
    # =========================================================================

    def evaluate(
        self,
        semantic_packet_biased: dict,
        concept_tags: List[dict],
        wm_context: dict,
        drive_vector: dict,
        thought_packet: dict,
        state_snapshot: dict,
        params: dict,
    ) -> List[DriveSignal]:
        """
        评估是否需要触发联网搜索。

        返回：
            - 触发搜索：返回一个 signal_type="seek" 的 DriveSignal，
              payload_draft["web_search_results"] 初始为空 [],
              实际结果由 entity_zero_iteration.py 在裁决后异步填充
            - 不触发：返回空列表
        """
        signals: List[DriveSignal] = []

        try:
            params = params or {}
            enabled = bool(params.get("web_search.enabled", True))
            if not enabled:
                return []

            info_hunger_thresh = float(params.get("web_search.info_hunger_threshold", 0.6))
            wm_hit_thresh = float(params.get("web_search.wm_hit_threshold", 0.3))
            intent_thresh = float(params.get("web_search.intent_intensity_threshold", 0.6))
            max_results = int(params.get("web_search.max_results", 5))
            timeout = float(params.get("web_search.timeout_seconds", 8.0))
            backend = params.get("web_search.backend")  # None = 自动选择

            dv = drive_vector or {}
            sc = state_snapshot or {}
            sp = semantic_packet_biased or {}

            info_hunger = float(dv.get("info_hunger", 0.0))
            wm_hit_rate = 0.0
            if isinstance(wm_context, dict):
                cov = wm_context.get("coverage", {})
                if isinstance(cov, dict):
                    wm_hit_rate = float(cov.get("hit_rate", 0.0))

            intent = str(sp.get("intent", "闲聊"))
            intensity = float(sp.get("intensity", 0.0))

            # ---- 触发条件判断 ----
            trigger_reason = ""
            trigger_strength = 0.0

            if info_hunger > info_hunger_thresh:
                trigger_reason = f"信息饥饿驱动（info_hunger={info_hunger:.2f} > {info_hunger_thresh}）"
                trigger_strength = min(1.0, info_hunger)

            elif wm_hit_rate < wm_hit_thresh and wm_hit_rate >= 0.0:
                trigger_reason = f"世界模型命中率低（hit_rate={wm_hit_rate:.2f} < {wm_hit_thresh}）"
                trigger_strength = min(1.0, 1.0 - wm_hit_rate + 0.3)

            elif intent == "求助" and intensity > intent_thresh:
                trigger_reason = f"求知意图（intent={intent}, intensity={intensity:.2f}）"
                trigger_strength = min(1.0, intensity)

            if not trigger_reason:
                return []

            # ---- 生成搜索词 ----
            query = _build_search_query(sp, concept_tags, wm_context, sc)
            if not query:
                return []

            # ---- 启动异步搜索（不阻塞裁决） ----
            runner = _AsyncSearchRunner(query, max_results, timeout, backend)
            runner.start()

            # ---- 注册到全局搜索池（entity_zero_iteration.py 会读取） ----
            _pending_search_register(runner)

            # ---- 发出 seek 信号 ----
            signals.append(DriveSignal(
                signal_type="seek",
                strength=trigger_strength,
                source="WebSearch",
                payload_draft={
                    "reason": trigger_reason,
                    "context_id": "web_search",
                    "search_query": query,
                    "search_results": [],  # 初始为空，裁决后由外层填充
                }
            ))

        except Exception as e:
            logger.warning(f"[WebSearch] WebSearch.evaluate 异常: {e}")

        return signals


# ============================================================================
# 全局搜索池（供 entity_zero_iteration.py 读取未决搜索）
# ============================================================================

_pending_searches: List[_AsyncSearchRunner] = []


def _pending_search_register(runner: _AsyncSearchRunner) -> None:
    _pending_searches.append(runner)


def drain_pending_searches() -> List[Dict[str, Any]]:
    """
    收集所有已完成搜索的结果。

    由 entity_zero_iteration.py 在裁决后调用。
    返回格式：List[{"query": str, "results": List[dict]}]
    """
    global _pending_searches
    done: List[Dict[str, Any]] = []
    remaining: List[_AsyncSearchRunner] = []

    for runner in _pending_searches:
        if runner.is_done():
            done.append({
                "query": runner.query,
                "results": runner.get_results(),
            })
        else:
            remaining.append(runner)

    _pending_searches = remaining
    return done


def clear_pending_searches() -> None:
    """清空所有未决搜索（裁决完成时调用）"""
    global _pending_searches
    _pending_searches.clear()
