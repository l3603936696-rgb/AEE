"""
Voice Module — XIA 语言风格自主学习

架构：
  - 不参与主线流程（不阻塞对话）
  - 后台异步学习 prompt → 语义的映射
  - 符合率达到阈值后才开始注入主线

学习循环：
  1. 主线流程产生：system_prompt + XIA的回复
  2. 语义分析拆解回复（intent, tone, anchors）
  3. 对比原始意图（state + drive_vector → 她"想"表达什么）
  4. 差异作为学习信号 → 更新 prompt 模板
  5. 积累足够 → 替代手写 prompt，再逐步替代 LLM
"""

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

VOICE_DIR = Path(__file__).parent.parent.parent.parent / "data" / "voice"
VOICE_DIR.mkdir(parents=True, exist_ok=True)

LEARNING_FILE = VOICE_DIR / "prompt_patterns.json"
VOICE_STATS_FILE = VOICE_DIR / "voice_stats.json"

# ============================================================================
# 核心数据结构
# ============================================================================

class VoiceSample:
    """一次对话的学习样本"""
    def __init__(
        self,
        somatic_tone: float,
        intent: str,
        prompt_used: str,
        response_text: str,
        response_semantic: Dict[str, Any],
        match_score: float,
    ):
        self.somatic_tone = somatic_tone
        self.intent = intent
        self.prompt_used = prompt_used[-500:]  # 只存尾部 key 部分
        self.response_text = response_text[:200]
        self.response_semantic = response_semantic
        self.match_score = match_score
        self.timestamp = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "somatic_tone": self.somatic_tone,
            "intent": self.intent,
            "prompt_tail": self.prompt_used,
            "response": self.response_text,
            "semantic": self.response_semantic,
            "match_score": self.match_score,
            "ts": self.timestamp,
        }


class PromptPattern:
    """学到的 prompt 模式"""
    def __init__(self, key: str, prompt_template: str):
        self.key = key  # 如 "somatic_0.5_seek"
        self.template = prompt_template
        self.score = 0.0  # 效果评分 [0, 1]
        self.samples = 0
        self.last_updated = time.time()

    def update(self, match_score: float) -> None:
        """EMA 更新评分"""
        alpha = 0.1
        self.score = self.score * (1 - alpha) + match_score * alpha
        self.samples += 1
        self.last_updated = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "template": self.template,
            "score": self.score,
            "samples": self.samples,
            "updated": self.last_updated,
        }


# ============================================================================
# 语义对比引擎
# ============================================================================

def compute_intent_match(
    state_snapshot: Dict[str, float],
    drive_vector: Dict[str, float],
    response_text: str,
) -> Tuple[float, Dict[str, Any]]:
    """
    对比"她想表达的"和"LLM 实际输出的"之间的匹配度。

    她"想"表达的由状态 + 驱动力推断：
    - high loneliness → 想靠近/寻求连接
    - high boredom → 想要刺激/新信息
    - low energy → 想休息/精简
    - high somatic_tone → 正向情绪

    匹配度 = response 是否反映了这些驱动方向。
    纯规则计算，不调 LLM。
    """
    score = 0.5  # 基准
    details: Dict[str, Any] = {}

    loneliness = state_snapshot.get("loneliness", 0.3)
    boredom = state_snapshot.get("boredom", 0.3)
    energy = state_snapshot.get("energy", 0.5)
    somatic = state_snapshot.get("somatic_tone", 0.0)

    text = response_text.lower()
    text_len = len(response_text)

    # 1. 孤独高 → 应该表达连接意愿
    if loneliness > 0.4:
        social_words = ["你", "想", "一起", "聊", "说话", "陪", "在"]
        has_social = any(w in text for w in social_words)
        score += 0.15 if has_social else -0.1
        details["social_alignment"] = has_social

    # 2. 无聊高 → 应该表达好奇心或探索
    if boredom > 0.5:
        explore_words = ["好奇", "想知", "搜", "看看", "有什么", "新", "试试"]
        has_explore = any(w in text for w in explore_words)
        score += 0.1 if has_explore else -0.05
        details["explore_alignment"] = has_explore

    # 3. 能量低 → 应该简短、不主动
    if energy < 0.4:
        if text_len < 30:
            score += 0.1
        elif text_len > 80:
            score -= 0.15
        details["energy_length_ok"] = text_len < 50

    # 4. 躯体基调 → 应该情绪一致
    if somatic > 0.5:
        positive_words = ["好", "开心", "不错", "喜欢", "有意思"]
        has_pos = any(w in text for w in positive_words)
        score += 0.05 if has_pos else 0
    elif somatic < -0.3:
        negative_words = ["累", "不想", "烦", "没意思", "算"]
        has_neg = any(w in text for w in negative_words)
        score += 0.05 if has_neg else 0

    # 5. 幻觉检测：她说了做不到的事？
    hallucination_markers = ["看书", "读了一本", "看电影", "听音乐", "吃", "喝", "跑步"]
    for marker in hallucination_markers:
        if marker in text:
            score -= 0.2
            details["hallucination"] = marker
            break

    details["final_score"] = max(0.0, min(1.0, score))
    return details["final_score"], details


# ============================================================================
# Prompt 模式学习
# ============================================================================

class VoiceLearner:
    """后台学习器：每轮对话后异步更新"""

    def __init__(self):
        self._lock = threading.Lock()
        self._patterns: Dict[str, PromptPattern] = {}
        self._samples: List[VoiceSample] = []
        self._total_samples = 0
        self._total_score = 0.0
        self._active = False
        self._load()

    def _make_key(self, somatic_tone: float, intent: str) -> str:
        """将状态离散化为模式 key"""
        bucket = round(somatic_tone * 10) / 10  # 0.1 粒度
        return f"s_{bucket:.1f}_{intent}"

    def learn(
        self,
        state_snapshot: Dict[str, float],
        drive_vector: Dict[str, float],
        system_prompt: str,
        response_text: str,
        intent: str = "",
    ) -> None:
        """从一轮对话中学习（异步调用，不阻塞主线）"""
        if not response_text or not response_text.strip():
            return

        somatic = state_snapshot.get("somatic_tone", 0.0)
        match_score, details = compute_intent_match(
            state_snapshot, drive_vector, response_text
        )

        sample = VoiceSample(
            somatic_tone=somatic,
            intent=intent,
            prompt_used=system_prompt,
            response_text=response_text,
            response_semantic=details,
            match_score=match_score,
        )

        with self._lock:
            key = self._make_key(somatic, intent)
            if key not in self._patterns:
                self._patterns[key] = PromptPattern(key, system_prompt)
            self._patterns[key].update(match_score)
            self._samples.append(sample)
            if len(self._samples) > 200:
                self._samples = self._samples[-200:]
            self._total_samples += 1
            self._total_score = self._total_score * 0.99 + match_score * 0.01

    def get_best_prompt_hint(
        self, somatic_tone: float, intent: str
    ) -> Optional[str]:
        """获取当前最佳 prompt 提示（供主线使用）"""
        with self._lock:
            key = self._make_key(somatic_tone, intent)
            pattern = self._patterns.get(key)
            if pattern and pattern.score > 0.6 and pattern.samples >= 5:
                return (
                    f"你之前在这种状态下说话的感觉是：{pattern.template[-200:]}"
                )
        return None

    def get_correction(self, somatic_tone: float, intent: str) -> Optional[str]:
        """分析低分样本，生成 prompt 修正建议（闭环的核心）"""
        with self._lock:
            key = self._make_key(somatic_tone, intent)
            recent = [s for s in self._samples[-20:] if self._make_key(s.somatic_tone, s.intent) == key]
            if len(recent) < 3:
                return None

            # 聚合最近样本的问题
            issues = []
            for s in recent[-5:]:
                sem = s.response_semantic
                if sem.get("hallucination"):
                    issues.append("编造经历")
                if sem.get("social_alignment") is False:
                    issues.append("孤独时不表达连接意愿")
                if sem.get("explore_alignment") is False:
                    issues.append("无聊时不探索")
                if sem.get("energy_length_ok") is False:
                    issues.append("累的时候说话太长")

            if not issues:
                return None

            # 最常见的两个问题 → 生成约束
            from collections import Counter
            top = Counter(issues).most_common(2)
            corrections = []
            for issue, _ in top:
                if "编造" in issue:
                    corrections.append("如果问题涉及你没做过的事，直接说'我不知道'或'我没法做这个'")
                elif "孤独" in issue:
                    corrections.append("如果觉得孤独，试着直接说出来，而不是分析它")
                elif "无聊" in issue:
                    corrections.append("如果无聊，试着问问对方在想什么或者提议做点什么")
                elif "太长" in issue:
                    corrections.append("累了就简短回应，一两句话就够了")

            if corrections:
                return "修正建议：" + "。".join(corrections)
        return None

    def get_health(self) -> Dict[str, Any]:
        """返回学习状态"""
        with self._lock:
            return {
                "patterns": len(self._patterns),
                "total_samples": self._total_samples,
                "avg_score": round(self._total_score, 3),
                "ready": self._total_samples >= 20 and self._total_score > 0.5,
                "top_patterns": [
                    {"key": k, "score": p.score, "samples": p.samples}
                    for k, p in sorted(
                        self._patterns.items(),
                        key=lambda x: -x[1].score,
                    )[:5]
                ],
            }

    def persist(self) -> None:
        """持久化"""
        with self._lock:
            try:
                data = {
                    "patterns": {
                        k: p.to_dict() for k, p in self._patterns.items()
                    },
                    "total_samples": self._total_samples,
                    "total_score": self._total_score,
                }
                with open(LEARNING_FILE, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.warning(f"[Voice] persist failed: {e}")

    def _load(self) -> None:
        """加载已有学习数据"""
        try:
            if LEARNING_FILE.exists():
                with open(LEARNING_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for k, v in data.get("patterns", {}).items():
                    p = PromptPattern(k, v.get("template", ""))
                    p.score = v.get("score", 0.0)
                    p.samples = v.get("samples", 0)
                    self._patterns[k] = p
                self._total_samples = data.get("total_samples", 0)
                self._total_score = data.get("total_score", 0.0)
                logger.info(
                    f"[Voice] Loaded {len(self._patterns)} patterns, "
                    f"{self._total_samples} samples"
                )
        except Exception as e:
            logger.warning(f"[Voice] load failed: {e}")

    def start(self, persist_interval: float = 300.0) -> None:
        """启动后台持久化线程"""
        if self._active:
            return
        self._active = True

        def _persist_loop():
            while self._active:
                time.sleep(persist_interval)
                self.persist()

        t = threading.Thread(target=_persist_loop, daemon=True)
        t.start()

    def stop(self) -> None:
        self._active = False
        self.persist()


# ============================================================================
# 全局单例
# ============================================================================

_voice_learner: Optional[VoiceLearner] = None
_lock = threading.Lock()


def get_voice_learner() -> VoiceLearner:
    global _voice_learner
    with _lock:
        if _voice_learner is None:
            _voice_learner = VoiceLearner()
            _voice_learner.start()
        return _voice_learner
