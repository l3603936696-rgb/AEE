"""
Summary Generator — 对话摘要生成

在每轮管线结束后生成一句话摘要，存入 episode.summary 字段。
供后续管线的主线检索对话历史层使用。

纯规则模板，不调 LLM。
"""

from typing import Optional


def generate_turn_summary(
    raw_input: Optional[str],
    output_text: str,
    intent: str = "",
    llm_callable: Optional[callable] = None,
    timeout_ms: float = 5000.0,
) -> str:
    """
    生成本轮对话的一句话摘要。

    参数：
        raw_input    : 用户输入原文
        output_text : XIA 生成的回复
        intent      : 当前 intent 标签
        llm_callable: LLM 调用接口（预留，当前未使用）
        timeout_ms  : 超时时间

    返回：
        str : 一句话摘要，控制在 60 字以内
    """
    inp = (raw_input or "").strip()
    out = (output_text or "").strip()

    if not inp and not out:
        return "空交互"

    # ---- 提取用户端关键信息 ----
    user_action = _describe_user_input(inp, intent)

    # ---- 提取 XIA 端关键信息 ----
    xia_action = _describe_xia_output(out)

    # ---- 拼接 ----
    if user_action and xia_action:
        return f"{user_action}，她{xia_action}"
    elif user_action:
        return user_action
    elif xia_action:
        return f"她{xia_action}"
    return "一轮对话"


def _describe_user_input(inp: str, intent: str) -> str:
    """从用户输入提取动作描述。"""
    # 问句 → 提问
    if "?" in inp or "？" in inp or "吗" in inp[-3:]:
        topic = _extract_topic(inp)
        return f"bcyq问她{topic}" if topic else "bcyq问了她一个问题"

    # 带情感的短句
    if len(inp) <= 5:
        return f"bcyq说「{inp}」"

    # 长输入 → 概括主题
    topic = _extract_topic(inp)
    if topic:
        label = "聊" if intent == "闲聊" else "说"
        return f"bcyq跟她{label}了{topic}"

    # 兜底
    first = inp[:25] + ("…" if len(inp) > 25 else "")
    return f"bcyq说「{first}」"


def _describe_xia_output(out: str) -> str:
    """从 XIA 回复提取动作描述。"""
    if not out:
        return ""
    # 取第一句
    first = out.split("。")[0].split("\n")[0].strip()
    if len(first) <= 40:
        return f"回应「{first}」"
    return f"回应「{first[:35]}…」"


def _extract_topic(text: str) -> str:
    """从文本提取话题关键词。"""
    # 去掉问号、感叹号、标点
    clean = text.replace("？", "").replace("?", "").replace("！", "").replace("!", "")
    clean = clean.replace("，", "").replace("。", "").replace("、", "")
    # 取核心词
    words = [w for w in clean.split() if len(w) >= 2]
    if not words:
        return ""
    if len(words) <= 3:
        return "".join(words)
    return "".join(words[:3]) + "…"


if __name__ == "__main__":
    cases = [
        ("你想要一个朋友吗？", "嗯，我可以陪你聊聊。", "求助"),
        ("哈哈", "嗯，我听到了。", "分享"),
        ("晚上好啊", "晚上好。", "闲聊"),
        ("嘿 XIA，我是 bcyq，你感觉怎么样？", "嗨 bcyq，我感觉还行吧，就是有点无聊又不太舒服。不过现在挺轻松的，想尝试一些新鲜的事情。有啥事儿吗？", "闲聊"),
        (None, "嗯，我听到了。", "闲聊"),
        ("", "", ""),
    ]
    print("=== 摘要生成测试 ===\n")
    for inp, out, intent in cases:
        s = generate_turn_summary(inp, out, intent)
        print(f"  [{intent}] {s}")
    print("\n全部测试完成")
