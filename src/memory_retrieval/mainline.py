"""
Mainline Retrieval — 主线检索（直接通道）

基于当前输入语义，从 episodes_db 检索相关历史经验 + 对话历史摘要，
合并后返回完整检索结果，供 output_layer 注入 user_prompt。

职责：
    1. 语义相似度检索（调用 episodes_db.retrieve_episodes_by_text）
    2. 对话历史摘要层（取最近 K 轮 summary）
    3. 格式化检索结果为 prompt 可用格式
"""

from typing import Any, Dict, List, Optional

# 参数默认值
DEFAULT_MAINLINE_LIMIT: int = 5
DEFAULT_MAINLINE_MIN_SIMILARITY: float = 0.40
DEFAULT_RECENT_CONTEXT_K: int = 5


def get_recent_summaries(k: int = DEFAULT_RECENT_CONTEXT_K) -> List[str]:
    """
    从 episodes_db 取最近 K 轮对话的 summary 字段。

    按时间戳升序排列（最早一轮在前，最近一轮在后），
    保证 user_prompt 注入顺序与真实对话顺序一致。
    每条带 [第N轮] 前缀。

    参数：
        k : 返回条数上限

    返回：
        List[str] : 非空 summary 列表（升序，[第N轮] 前缀）
    """
    try:
        from ..memory_hub.episodes_db import get_recent_episodes
        episodes = get_recent_episodes(limit=k)
        if not episodes:
            return []
        # 升序排列（最早在前）
        episodes.sort(key=lambda ep: ep.timestamp)
        return [
            f"[第{ep.iteration_id}轮] {ep.summary.strip()}"
            for ep in episodes
            if ep.summary and ep.summary.strip()
        ]
    except Exception:
        return []


def _format_recent_context(episodes: List[Any]) -> str:
    """
    将对话历史 episode 列表（升序）格式化为带轮次标记的文本。

    轮次号从 episode.iteration_id 读取，保证 LLM 能区分"刚才"和"之前"。
    """
    if not episodes:
        return ""
    lines = []
    for ep in episodes:
        tick_label = f"[第{getattr(ep, 'iteration_id', '?')}轮]"
        summary = getattr(ep, "summary", "") or ""
        if summary.strip():
            lines.append(f"- {tick_label} {summary.strip()}")
    if not lines:
        return ""
    return "【对话历史】\n" + "\n".join(lines)


def _format_related_memories(episodes: List[Any]) -> str:
    """将检索到的历史 episode 格式化为提示文本。"""
    if not episodes:
        return ""
    lines = []
    for ep in episodes:
        inp = (ep.raw_input or "").strip()
        out = (ep.output_text or "").strip()
        if inp:
            snippet = inp[:80] + ("…" if len(inp) > 80 else "")
            lines.append(f"- 你说过「{snippet}」")
        elif out:
            snippet = out[:80] + ("…" if len(out) > 80 else "")
            lines.append(f"- 之前回应过「{snippet}」")
    if not lines:
        return ""
    return "【相关记忆】\n" + "\n".join(lines)


def mainline_retrieval(
    semantic_packet_biased: Dict[str, Any],
    *,
    limit: int = DEFAULT_MAINLINE_LIMIT,
    min_similarity: float = DEFAULT_MAINLINE_MIN_SIMILARITY,
    recent_k: int = DEFAULT_RECENT_CONTEXT_K,
    current_iteration_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    主线检索入口。

    参数：
        semantic_packet_biased : 当前轮次的语义包（来自 semantic 层 + memory_bias）
        limit                 : 语义检索最多返回条数
        min_similarity        : 语义检索最低相似度
        recent_k              : 对话历史摘要覆盖轮数
        current_iteration_id  : 当前轮次 ID（用于排除当前轮次自身）

    返回：
        {
            "recent_context": List[Any],    # 最近 K 轮 Episode 对象（升序排列）
            "related_memories": List[Any], # 语义相似的历史 episode（Episode 对象）
            "recent_context_text": str,    # 格式化后的对话历史文本（供注入 prompt）
            "related_memories_text": str,  # 格式化后的相关记忆文本（供注入 prompt）
            "query": str,                 # 本次检索使用的查询文本
        }
    """
    try:
        from ..memory_hub.episodes_db import retrieve_episodes_by_text, get_recent_episodes

        query = (semantic_packet_biased.get("raw_input") or "").strip()

        # 1. 对话历史摘要层：取最近 K 轮，timestamp 升序排列
        recent_episodes = get_recent_episodes(limit=recent_k)
        recent_episodes.sort(key=lambda ep: ep.timestamp)  # 升序：最早在前

        # 2. 语义相似检索
        recalled = []
        if query:
            try:
                recalled = retrieve_episodes_by_text(
                    query=query,
                    limit=limit,
                    min_similarity=min_similarity,
                    exclude_iteration_id=current_iteration_id,
                )
            except Exception:
                recalled = []

        return {
            "recent_context": recent_episodes,
            "related_memories": recalled,
            "recent_context_text": _format_recent_context(recent_episodes),
            "related_memories_text": _format_related_memories(recalled),
            "query": query,
        }

    except Exception:
        return {
            "recent_context": [],
            "related_memories": [],
            "recent_context_text": "",
            "related_memories_text": "",
            "query": "",
        }


if __name__ == "__main__":
    print("=== 主线检索测试 ===\n")

    test_packet = {
        "raw_input": "你想要一个朋友吗？",
        "intent": "求助",
        "emotion": 0.1,
        "intensity": 0.5,
    }

    result = mainline_retrieval(test_packet, recent_k=5, limit=3)
    print(f"查询: {result['query']}")
    print(f"对话历史条数: {len(result['recent_context'])}")
    print(f"相关记忆条数: {len(result['related_memories'])}")
    if result["recent_context_text"]:
        print(f"\n对话历史:\n{result['recent_context_text']}")
    if result["related_memories_text"]:
        print(f"\n相关记忆:\n{result['related_memories_text']}")

    print("\n全部测试完成")
