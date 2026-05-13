"""支持 python3 -m channel 启动"""

from .chat import chat, chat_turn

if __name__ == "__main__":
    import argparse
    import os
    import sys

    _ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _ROOT not in sys.path:
        sys.path.insert(0, _ROOT)

    from src.entity_zero_iteration import reset_entity_state

    parser = argparse.ArgumentParser(description="XIA — CLI 对话入口")
    parser.add_argument("--debug", action="store_true", help="显示管线执行追踪")
    parser.add_argument("--reset", action="store_true", help="重置实体内核状态")
    parser.add_argument("input", nargs="?", default=None, help="初始输入（单轮模式）")
    args = parser.parse_args()

    if args.reset:
        reset_entity_state()
        print("✓ 实体内核已重置")

    chat(debug=args.debug, initial_input=args.input)
