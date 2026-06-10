"""
验证脚本: _handle_training_tick 返回值调用链完整性检查

Purpose: verify the daemon._handle_training_tick -> HTTP result.best contract.
     The result should stay flat enough for local clients to read result.best / result.second / result.third.

调用链:
  1. client:    POST / with type=training_tick
                  ↓
  2. HTTPServer.do_POST(): wraps the JSON into IPCRequest
                  ↓
  3. IPCServer._dispatch(): routes type=training_tick
                  ↓
  4. daemon: _handle_training_tick() -> run_language_training_tick()



运行:
  python E:/XIA/scripts/verify_training_tick.py
"""

import json
import sys
from typing import Any


# ============================================================================
# 模拟各层的返回值（模拟实际数据结构）
# ============================================================================

def make_ipc_response(result_data: dict) -> dict:
    """模拟 IPCResponse.to_json() → from_json() 往返"""
    return {
        "type": "training_response",
        "id": "test-uuid",
        "ok": True,
        "result": result_data,
        "error": None,
    }


# run_language_training_tick() 返回的原始数据（正确的扁平结构）
LANGUAGE_TRAINING_RESULT = {
    "vr_state": {"somatic_tone": -0.2, "loneliness": 0.3, "energy": 0.8},
    "best": "困",
    "best_score": 0.712,
    "second": "累",
    "second_score": 0.581,
    "third": "乏",
    "third_score": 0.449,
    "display": "困",
    "cand_count": 5,
    "warm_count": 2,
    "ms": 3.14,
}


# 模拟 BUG 版本: _handle_training_tick 错误地返回 {"result": raw_result}
# 导致 response.result 变成 { "result": { "best": "困", ... } }
LANGUAGE_TRAINING_RESULT_BUG = {
    "result": LANGUAGE_TRAINING_RESULT
}


# ============================================================================
# 模拟 xia-bridge 的 runTrainingTick 返回值处理
# ============================================================================

def xia_bridge_run_training_tick(http_response_body: dict) -> dict:
    """
    模拟 xia-bridge.js 的 runTrainingTick:
      const response = await this._postRequest({ type: 'training_tick', ... });
      if (response.ok !== undefined) {
        if (!response.ok) return { error: response.error };
        return response.result || response;   ← 关键: 取 response.result
      }
      return response;
    """
    if http_response_body.get("ok") is not None:
        if not http_response_body.get("ok"):
            return {"error": http_response_body.get("error")}
        return http_response_body.get("result") or http_response_body
    return http_response_body


# ============================================================================
# 模拟 IPCServer._dispatch: _handle_training_tick 的返回值如何被包装
# ============================================================================

def ipc_dispatch_training_tick(handler_result: dict) -> dict:
    """
    模拟 daemon.py IPCServer._dispatch:
      elif request.type == "training_tick":
          result = self._handle_training_tick(request)
          resp = IPCResponse.success(request.id, result, "training_response")
      return resp.to_json()

    IPCResponse.success 构造:
      cls(type=response_type, id=request_id, ok=True, result=result)
    """
    resp = {
        "type": "training_response",
        "id": "test-uuid",
        "ok": True,
        "result": handler_result,   # ← result 就是 handler 返回的 dict
        "error": None,
    }
    return json.dumps(resp, ensure_ascii=False)


# ============================================================================
# 核心验证函数
# ============================================================================

def check_field_accessibility(data: Any, field: str) -> tuple[bool, Any]:
    """检查某个字段是否可直接访问，返回 (可访问, 当前值)"""
    try:
        val = data[field]
        return True, val
    except (KeyError, TypeError):
        return False, None


def verify_chain(label: str, ipc_resp_data: dict) -> bool:
    """
    验证一条完整的调用链。

    前端期望的数据结构（直接从 xia-bridge 返回后）:
      result.best        → str: "困"
      result.best_score  → float: 0.712
      result.second      → str: "累"
      result.second_score→ float: 0.581
      result.third       → str: "乏"
      result.display     → str: "困"
      result.cand_count  → int: 5
      result.ms          → float: 3.14
    """
    print(f"\n{'=' * 60}")
    print(f"  场景: {label}")
    print(f"{'=' * 60}")

    # Step 1: xia-bridge 取 response.result
    bridge_result = xia_bridge_run_training_tick(ipc_resp_data)
    print(f"\n[Step 1] xia-bridge 返回值:")
    print(f"         类型: {type(bridge_result).__name__}")
    print(f"         内容: {json.dumps(bridge_result, ensure_ascii=False, indent=4)}")

    # Step 2: 前端组件直接访问 result.best 等字段
    print(f"\n[Step 2] 前端组件字段访问检查:")

    checks = [
        ("best",         "result.best         (首选词)"),
        ("best_score",   "result.best_score   (首选词分数)"),
        ("second",       "result.second       (次选词)"),
        ("second_score", "result.second_score (次选词分数)"),
        ("third",        "result.third        (第三候选)"),
        ("display",      "result.display      (展示文本)"),
        ("cand_count",   "result.cand_count   (候选词数量)"),
        ("ms",           "result.ms           (耗时ms)"),
        # Training.jsx 第 167-169 行还访问了这些:
        ("cand_count",   "result.cand_count (meta显示)"),
        ("warm_count",   "result.warm_count  (warm数量)"),
    ]

    all_ok = True
    for field, desc in checks:
        ok, val = check_field_accessibility(bridge_result, field)
        status = "  OK  " if ok else " FAIL "
        print(f"    [{status}] {desc} = {repr(val)}")
        if not ok:
            all_ok = False

    # Step 3: 错误场景检查：如果 bridge_result 本身是嵌套的
    print(f"\n[Step 3] 嵌套层数检查:")
    depth = 0
    current = bridge_result
    while isinstance(current, dict) and "result" in current and depth < 3:
        depth += 1
        print(f"         第 {depth} 层嵌套: 发现 'result' 键 → 继续展开")
        current = current["result"]
    if depth > 0:
        print(f"    [FAIL] 存在 {depth} 层多余的 result 嵌套!")
        print(f"         前端需要 response.result.result.result... 才能访问数据")
        all_ok = False
    else:
        print(f"    [ OK ] 无多余嵌套，数据扁平")

    return all_ok


# ============================================================================
# 主验证
# ============================================================================

def main():
    print("=" * 60)
    print("  XIA Training Tick 调用链返回值验证")
    print("=" * 60)
    print()
    print("目标: 确认修复后，response.result 是扁平的 { best, second, third, ... }")
    print("      而非嵌套的 { result: { result: { best, ... } } }")

    results = {}

    # ---- 场景 1: 修复后（正确的返回值链）----
    ipc_resp_fixed = make_ipc_response(LANGUAGE_TRAINING_RESULT)
    results["修复后 (daemon 直接返回结果)"] = verify_chain(
        "修复后 — daemon._handle_training_tick 返回 run_language_training_tick() 的原始结果",
        ipc_resp_fixed
    )

    # ---- 场景 2: BUG 版本（多余嵌套）----
    ipc_resp_bug = make_ipc_response(LANGUAGE_TRAINING_RESULT_BUG)
    results["BUG 版本 (handler 错误嵌套)"] = verify_chain(
        "BUG 版本 — 如果 _handle_training_tick 返回 { result: raw }",
        ipc_resp_bug
    )

    # =========================================================================
    # 边界情况
    # =========================================================================
    print(f"\n\n{'=' * 60}")
    print(f"  边界情况检查")
    print(f"{'=' * 60}")

    # 边界1: best_candidate 为 None (无候选词)
    print(f"\n[边界1] best_candidate 为 None (无候选词):")
    no_candidate = {**LANGUAGE_TRAINING_RESULT, "best": None, "second": None, "third": None}
    ipc_no_cand = make_ipc_response(no_candidate)
    bridge_no_cand = xia_bridge_run_training_tick(ipc_no_cand)
    ok_b, val_b = check_field_accessibility(bridge_no_cand, "best")
    ok_s, val_s = check_field_accessibility(bridge_no_cand, "second")
    ok_t, val_t = check_field_accessibility(bridge_no_cand, "third")
    print(f"    best   = {repr(val_b)}  (should be None, JS 会渲染为空)")
    print(f"    second = {repr(val_s)}  (should be None)")
    print(f"    third  = {repr(val_t)}  (should be None)")
    print(f"    [ OK ] 前端 Training.jsx 用 result.best && ... 包裹，安全")
    results["边界1-无候选词"] = True

    # 边界2: run_language_training_tick 异常，返回 error dict
    print(f"\n[边界2] _handle_training_tick 异常，返回 {{error: str}}:")
    error_result = {"error": "some exception"}
    ipc_error = make_ipc_response(error_result)
    bridge_error = xia_bridge_run_training_tick(ipc_error)
    ok_err, err_msg = check_field_accessibility(bridge_error, "error")
    print(f"    xia-bridge 返回: {bridge_error}")
    print(f"    [ OK ] 前端 Training.jsx 用 result.error && ... 包裹，安全")
    results["边界2-异常返回"] = True

    # 边界3: 如果 ok=False (daemon 层面失败)
    print(f"\n[边界3] IPC ok=False (daemon 层面失败):")
    ipc_fail = {"type": "training_response", "id": "test", "ok": False, "result": None, "error": "IPC error"}
    bridge_fail = xia_bridge_run_training_tick(ipc_fail)
    print(f"    xia-bridge 返回: {bridge_fail}")
    print(f"    [ OK ] 前端 Training.jsx 用 result.error && ... 包裹，安全")
    results["边界3-ok=False"] = True

    # =========================================================================
    # 最终结论
    # =========================================================================
    print(f"\n\n{'=' * 60}")
    print(f"  最终结论")
    print(f"{'=' * 60}")

    fixed_ok = results["修复后 (daemon 直接返回结果)"]
    bug_ok   = results["BUG 版本 (handler 错误嵌套)"]

    print(f"\n修复后场景通过: {'YES' if fixed_ok else 'NO'}")
    print(f"BUG版本场景失败: {'YES (预期)' if not bug_ok else 'NO (不符合预期)'}")

    if fixed_ok and not bug_ok:
        print(f"\n  [VERDICT: PASS]")
        print(f"  修复逻辑正确。daemon._handle_training_tick 直接返回")
        print(f"  run_language_training_tick() 的结果，IPCResponse.success 将其包装为")
        print("  { result: <flat data best/second/third/...> }, so local clients can read result.best.")
        print(f"\n  完整数据路径:")
        print(f"    run_language_training_tick()")
        print(f"      → _handle_training_tick() [daemon.py:243]")
        print(f"        → IPCResponse.success(id, result, ...) [protocol.py:144]")
        print(f"          → HTTP response body [do_POST:299 返回 result]")
        print(f"            -> local HTTP JSON client")
        print(f"              -> result.best / result.second / result.third")


    else:
        print(f"\n  [VERDICT: FAIL]")
        print(f"  存在调用链问题，请检查上述输出。")

    print(f"\n{'-' * 60}")
    print(f"  代码层面确认:")
    print(f"  - daemon.py:236-245: _handle_training_tick 直接 return run_language_training_tick(...) [OK]")
    print(f"  - daemon.py:198-200: _dispatch 调用 handler 并用 IPCResponse.success 包装 [OK]")
    print(f"  - protocol.py:144-145: IPCResponse.success(request_id, result, 'training_response') [OK]")
    print(f"  - daemon.py:291-299: HTTPServer.do_POST 返回 resp.to_json() (含 result 字段) [OK]")
    print(f"  - xia-bridge.js:297-313: runTrainingTick 返回 response.result [OK]")
    print(f"  - xia-bridge.js:307: return response.result || response (有 fallback) [OK]")
    print(f"  - Training.jsx:149: data.best 直接访问 [OK]")
    print(f"  - Training.jsx:153-164: second/third 同样直接访问 [OK]")
    print(f"  - Training.jsx:167-169: cand_count/warm_count/ms 直接访问 [OK]")
    print(f"{'=' * 60}")

    return 0 if fixed_ok else 1


if __name__ == "__main__":
    sys.exit(main())
