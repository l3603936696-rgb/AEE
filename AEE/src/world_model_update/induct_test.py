"""Test entry point for induct.py v11.2 — prediction error driven."""

if __name__ == "__main__":
    import sys
    sys.path.insert(0, "src")

    import time
    from world_model_update.defaults import DEFAULT_PARAMS, get_raw_value
    from world_model_update.rules import Rule, Snap, Predicts

    print("=" * 64)
    print("归纳模块测试 — v11.2 预测误差驱动")
    print("=" * 64)

    now = time.time()

    def make_snap_with_pred_error(
        idx: int,
        action: str,
        pre_energy: float,
        pre_info_gap: float,
        info_gap_delta: float,
        pred_error_gap: float,
    ) -> Snap:
        snap = Snap(
            snap_index=idx,
            timestamp=now + idx,
            action_type=action,
            target="none",
            priority=0.5,
            pre_state={"energy": pre_energy, "info_gap": pre_info_gap, "loneliness": 0.3},
            post_state={
                "energy": pre_energy - 0.02,
                "info_gap": pre_info_gap + info_gap_delta,
                "loneliness": 0.31,
            },
        )
        snap.prediction_error_map = {
            "info_gap": pred_error_gap,
            "energy": -0.01,
            "loneliness": 0.005,
        }
        return snap

    from world_model_update.induct import induct_rules, predict_action_effects

    # Test 1: cold start, no rules
    print("\n【测试 1】冷启动：预测=0，|actual| > threshold → 创建规则")
    snaps_cold = [
        make_snap_with_pred_error(0, "seek", 0.8, 0.7, -0.08, -0.08),
        make_snap_with_pred_error(1, "seek", 0.8, 0.6, -0.07, -0.07),
    ]
    new_rules = induct_rules([], snaps_cold, DEFAULT_PARAMS)
    ok1 = len(new_rules) > 0
    print(f"  {'PASS' if ok1 else 'FAIL'} 生成规则数: {len(new_rules)}（期望 >=1）")
    for r in new_rules:
        print(f"    [{r.id}] trigger={r.predicts.trigger}")
        print(f"      expect={r.predicts.expect}")
        print(f"      deltas={r.expected_deltas}")
        print(f"      confidence={r.confidence}")

    # Test 2: EMA update
    print("\n【测试 2】已有规则，EMA 更新 expected_deltas")
    if new_rules:
        old_rule = new_rules[0]
        old_info_gap = old_rule.expected_deltas.get("info_gap", 0.0)
        old_conf = old_rule.confidence

        snaps_update = [
            make_snap_with_pred_error(2, "seek", 0.8, 0.7, -0.05, -0.03),
        ]
        induct_rules([old_rule], snaps_update, DEFAULT_PARAMS)
        new_info_gap = old_rule.expected_deltas.get("info_gap", 0.0)
        new_conf = old_rule.confidence

        expected_ema = round(old_info_gap * 0.7 + (-0.05) * 0.3, 5)
        ok2a = abs(new_info_gap - expected_ema) < 0.001
        ok2b = new_conf > old_conf
        print(f"  {'PASS' if ok2a else 'FAIL'} EMA 更新: {old_info_gap} -> {new_info_gap}（期望 ~{expected_ema}）")
        print(f"  {'PASS' if ok2b else 'FAIL'} confidence: {old_conf} -> {new_conf}（期望上升）")

    # Test 3: error below threshold
    print("\n【测试 3】|error| < threshold -> 不创建规则")
    snaps_tiny = [
        make_snap_with_pred_error(3, "seek", 0.8, 0.7, -0.01, -0.005),
    ]
    result_tiny = induct_rules([], snaps_tiny, DEFAULT_PARAMS)
    ok3 = len(result_tiny) == 0
    print(f"  {'PASS' if ok3 else 'FAIL'} 生成规则数: {len(result_tiny)}（期望 0）")

    # Test 4: empty snap list
    print("\n【测试 4】空快照列表")
    result_empty = induct_rules([], [], DEFAULT_PARAMS)
    ok4 = len(result_empty) == 0
    print(f"  {'PASS' if ok4 else 'FAIL'} 生成规则数: {len(result_empty)}（期望 0）")

    # Test 5: predict_action_effects
    print("\n【测试 5】predict_action_effects")
    test_rules = [
        Rule(
            id="test_seek",
            content="高能量时seek降低info_gap",
            confidence=0.7,
            status="active",
            context="energy高_info_gap高",
            predicts=Predicts(
                trigger="action_seek_in_energy高_info_gap高",
                expect="info_gap_decrease",
            ),
            expected_deltas={"info_gap": -0.06, "energy": -0.02},
        ),
    ]
    pred = predict_action_effects(
        "seek",
        {"energy": 0.8, "info_gap": 0.7},
        test_rules,
    )
    ok5a = abs(pred.get("info_gap", 0) + 0.06) < 0.001
    ok5b = abs(pred.get("energy", 0) + 0.02) < 0.001
    print(f"  {'PASS' if ok5a else 'FAIL'} info_gap 预测: {pred.get('info_gap')}（期望 -0.06）")
    print(f"  {'PASS' if ok5b else 'FAIL'} energy 预测: {pred.get('energy')}（期望 -0.02）")

    pred_none = predict_action_effects("avoid", {"energy": 0.5}, test_rules)
    ok5c = len(pred_none) == 0
    print(f"  {'PASS' if ok5c else 'FAIL'} 无匹配规则 -> 空预测: {pred_none}")

    print("\n" + "=" * 64)
    print("induct.py v11.2 测试完成")
    print("=" * 64)
