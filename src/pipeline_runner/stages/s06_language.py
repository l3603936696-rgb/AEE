"""Stage 06 — 语言系统薄编排层。

职责：依次调用 s06a_candidates（候选生成 + thermal）、
      s06b_output（Step 9 三路输出 + L3/L4）。
      s06c_anchor_core 由 s06b_output 内部调用。
"""

from .s06a_candidates import run_stage as run_s06a_candidates
from .s06b_output import run_stage as run_s06b_output


def run_stage(ctx, entity):
    """依次执行语言候选生成和输出层。"""
    run_s06a_candidates(ctx, entity)
    run_s06b_output(ctx, entity)
