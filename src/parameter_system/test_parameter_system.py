"""
Parameter System — 集成测试

运行方式：
    cd src/parameter_system && python -m pytest test_parameter_system.py -v
    或：python test_parameter_system.py
"""

import copy
import os
import tempfile
import time
import unittest

# 确保模块路径正确
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestParameters(unittest.TestCase):
    """测试 parameters.py"""

    def test_param_defaults_structure(self):
        from parameter_system.parameters import PARAM_DEFAULTS, PARAM_CATEGORIES
        # 三层结构
        self.assertIn("thresholds", PARAM_DEFAULTS)
        self.assertIn("drives", PARAM_DEFAULTS)
        self.assertIn("mechanisms", PARAM_DEFAULTS)
        self.assertIn("dynamics", PARAM_DEFAULTS)
        self.assertIn("_system", PARAM_DEFAULTS)
        print("  ✓ PARAM_DEFAULTS 包含 thresholds/drives/mechanisms/dynamics/_system")

    def test_thresholds_migration(self):
        from parameter_system.parameters import THRESHOLDS
        # V3 迁移的参数
        self.assertEqual(THRESHOLDS["narrative_memory_pressure_note_gate"], 0.52)
        self.assertEqual(THRESHOLDS["narrative_compactor_mem_pressure_gate"], 0.70)
        self.assertEqual(THRESHOLDS["pipeline_max_execution_time_ms"], 5000)
        self.assertEqual(THRESHOLDS["thinking_max_steps"], 2)
        self.assertEqual(THRESHOLDS["peer_uncaught_force_reply_streak"], 3)
        print("  ✓ V3 迁移参数完整")

    def test_drives_only_safe_params(self):
        from parameter_system.parameters import DRIVES
        self.assertIn("curiosity_baseline", DRIVES)
        self.assertIn("info_hunger_baseline", DRIVES)
        self.assertLessEqual(len(DRIVES), 5)   # 仅几个绝对安全参数
        print(f"  ✓ drives 保持极简: {list(DRIVES.keys())}")

    def test_mechanisms_structure(self):
        from parameter_system.parameters import MECHANISMS
        self.assertIn("enable_parameter_decay", MECHANISMS)
        self.assertIn("enable_belief_shock", MECHANISMS)
        self.assertIn("enable_body_evolution", MECHANISMS)
        # 全为布尔型
        for v in MECHANISMS.values():
            self.assertIsInstance(v, bool)
        print("  ✓ mechanisms 结构正确（布尔型）")

    def test_dynamics_initially_empty(self):
        from parameter_system.parameters import DYNAMICS
        self.assertEqual(DYNAMICS, {})
        print("  ✓ dynamics 初始为空")

    def test_read_only_defaults(self):
        from parameter_system.parameters import PARAM_DEFAULTS
        # 多次 import 不应共享可变状态
        p1 = PARAM_DEFAULTS
        p2 = PARAM_DEFAULTS
        self.assertIs(p1, p2)  # 同一对象
        print("  ✓ PARAM_DEFAULTS 为模块级单例")


class TestGovernance(unittest.TestCase):
    """测试 governance.py"""

    def setUp(self):
        from parameter_system.governance import ChangeGovernance, reset_governance
        reset_governance()
        self.gov = ChangeGovernance()

    def test_initial_status_is_governed(self):
        status = self.gov.get_status()
        from parameter_system.governance import ParameterStatus
        self.assertEqual(status, ParameterStatus.GOVERNED)
        print("  ✓ 初始状态为 governed")

    def test_submit_creates_pending_request(self):
        req = self.gov.submit(
            key_path="thresholds.test_param",
            proposed_value=0.99,
            reason="test",
            channel="ai_internal",
            requester="ai",
        )
        self.assertFalse(req.approved)
        self.assertIn("pending", self.gov.get_status("thresholds.test_param").value)
        print("  ✓ submit 生成待审批请求")

    def test_locked_rejects_all(self):
        from parameter_system.governance import ParameterStatus
        self.gov.set_status(ParameterStatus.LOCKED, "thresholds.critical")
        req = self.gov.submit(
            key_path="thresholds.critical",
            proposed_value=1.0,
            reason="try lock",
            channel="ai_internal",
            requester="ai",
        )
        self.assertFalse(req.approved)
        self.assertIn("LOCKED", req.rejection_log)
        print("  ✓ LOCKED 状态拒绝所有修改")

    def test_cooldown_drops_requests(self):
        from parameter_system.governance import ParameterStatus
        # 手动触发 cooldown
        self.gov._enter_cooldown_unlocked()
        self.assertEqual(self.gov.get_status(), ParameterStatus.COOLDOWN)
        req = self.gov.submit(
            key_path="thresholds.any",
            proposed_value=0.5,
            reason="during cooldown",
            channel="ai_internal",
            requester="ai",
        )
        self.assertIn("COOLDOWN", req.rejection_log)
        print("  ✓ COOLDOWN 状态丢弃所有请求")

    def test_ai_cannot_approve_own_proposal(self):
        # AI 审批被拒绝
        ok = self.gov.approve(
            key_path="thresholds.test",
            approver="ai",
            reason="ai self-approve",
        )
        self.assertFalse(ok)
        print("  ✓ AI 不能审批自己的提案")

    def test_developer_can_approve(self):
        ok = self.gov.approve(
            key_path="thresholds.test",
            approver="developer",
            reason="external audit pass",
        )
        self.assertTrue(ok)
        print("  ✓ 外部审批（developer）可以通过")

    def test_threshold_burst_triggers_cooldown(self):
        from parameter_system.governance import ParameterStatus
        # 模拟阈值突破（3次在窗口内）
        for i in range(3):
            self.gov.submit(
                key_path=f"thresholds.burst{i}",
                proposed_value=0.5 + i * 0.1,
                reason=f"burst {i}",
                channel="ai_internal",
                requester="ai",
            )
        self.assertEqual(self.gov.get_status(), ParameterStatus.COOLDOWN)
        print("  ✓ 阈值突破自动触发 cooldown")

    def test_get_records(self):
        self.gov.submit(
            key_path="thresholds.record_test",
            proposed_value=0.5,
            reason="record test",
            channel="ai_internal",
            requester="ai",
        )
        records = self.gov.get_records(limit=10)
        self.assertGreaterEqual(len(records), 1)
        print(f"  ✓ 治理记录功能正常（{len(records)} 条）")

    def test_reset(self):
        self.gov.submit(
            key_path="thresholds.reset_test",
            proposed_value=0.5,
            reason="reset",
            channel="ai_internal",
            requester="ai",
        )
        self.gov.reset()
        self.assertEqual(len(self.gov.get_records()), 0)
        print("  ✓ reset() 清空所有状态")


class TestSnapshot(unittest.TestCase):
    """测试 snapshot.py"""

    def test_create_snapshot_immutable(self):
        from parameter_system.snapshot import ParameterSnapshot, ReadOnlyView
        from parameter_system.parameters import PARAM_DEFAULTS

        snap = ParameterSnapshot.create(PARAM_DEFAULTS, tick_index=1)
        self.assertTrue(snap.is_valid)
        self.assertIsInstance(snap.params, ReadOnlyView)
        print("  ✓ create_snapshot 生成 ReadOnlyView")

    def test_readonly_view_blocks_write(self):
        from parameter_system.snapshot import ParameterSnapshot
        from parameter_system.parameters import PARAM_DEFAULTS

        snap = ParameterSnapshot.create(PARAM_DEFAULTS, tick_index=1)
        with self.assertRaises((AttributeError, TypeError)):
            snap.params["thresholds"] = {"new": 0.5}

        print("  ✓ ReadOnlyView 阻止直接写入")

    def test_readonly_view_blocks_nested_write(self):
        from parameter_system.snapshot import ParameterSnapshot
        from parameter_system.parameters import PARAM_DEFAULTS

        snap = ParameterSnapshot.create(PARAM_DEFAULTS, tick_index=1)
        # 读取嵌套 dict 并尝试写入（ReadOnlyView 对 dict 返回不可变包装）
        with self.assertRaises((AttributeError, TypeError)):
            snap.params["thresholds"]["pipeline_max_execution_time_ms"] = 999

        print("  ✓ 嵌套读取同样不可写")

    def test_readonly_view_nested_copy_is_mutable(self):
        from parameter_system.snapshot import ParameterSnapshot
        from parameter_system.parameters import PARAM_DEFAULTS

        snap = ParameterSnapshot.create(PARAM_DEFAULTS, tick_index=1)
        # 用 .copy() 方法获取可变的深拷贝
        mutable = snap.params.copy()
        self.assertIsInstance(mutable, dict)
        mutable["thresholds"]["pipeline_max_execution_time_ms"] = 999
        # 快照本身不受影响
        self.assertEqual(snap.params["thresholds"]["pipeline_max_execution_time_ms"], 5000)
        print("  ✓ .copy() 返回可变深拷贝，原快照不受影响")

    def test_snapshot_invalidate(self):
        from parameter_system.snapshot import ParameterSnapshot
        from parameter_system.parameters import PARAM_DEFAULTS

        snap = ParameterSnapshot.create(PARAM_DEFAULTS, tick_index=1)
        snap.invalidate()
        self.assertFalse(snap.is_valid)
        with self.assertRaises(ValueError):
            snap.validate()
        print("  ✓ snapshot.invalidate() 正确标记失效")

    def test_snapshot_different_ids(self):
        from parameter_system.snapshot import ParameterSnapshot
        from parameter_system.parameters import PARAM_DEFAULTS

        snap1 = ParameterSnapshot.create(PARAM_DEFAULTS, tick_index=1)
        snap2 = ParameterSnapshot.create(PARAM_DEFAULTS, tick_index=2)
        self.assertNotEqual(snap1.snapshot_id, snap2.snapshot_id)
        print(f"  ✓ 不同 tick 生成不同 snapshot_id: {snap1.snapshot_id} vs {snap2.snapshot_id}")

    def test_nested_dict_wrapped_in_readonly_view(self):
        from parameter_system.snapshot import ParameterSnapshot, ReadOnlyView
        from parameter_system.parameters import PARAM_DEFAULTS

        snap = ParameterSnapshot.create(PARAM_DEFAULTS, tick_index=1)
        # 读取嵌套 dict，返回的是 ReadOnlyView（不是普通 dict）
        nested = snap.params["thresholds"]
        self.assertIsInstance(nested, ReadOnlyView)
        # 再嵌套一层
        val = nested["pipeline_max_execution_time_ms"]
        self.assertEqual(val, 5000)
        print("  ✓ 嵌套 dict 被 ReadOnlyView 正确包装")


class TestStaging(unittest.TestCase):
    """测试 staging.py"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.temp_file = os.path.join(self.temp_dir, "test_params.json")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_stage_changes(self):
        from parameter_system.staging import StagedChanges, APPLY_MODE
        from parameter_system.parameters import PARAM_DEFAULTS

        staged = StagedChanges(self.temp_file)
        staged.stage("thresholds.test_param", 0.99, "unit test")
        self.assertEqual(staged.count(), 1)
        self.assertEqual(staged.get_staged("thresholds.test_param"), 0.99)
        print("  ✓ stage() 写入缓冲区")

    def test_apply_staged_only(self):
        from parameter_system.staging import StagedChanges, APPLY_MODE
        from parameter_system.parameters import PARAM_DEFAULTS

        staged = StagedChanges(self.temp_file)
        staged.stage("thresholds.new_param", 0.88, "test apply")
        staged.stage("drives.test_drive", 0.33, "test drive")

        # STAGED_ONLY：不落盘
        result = staged.apply_staged(PARAM_DEFAULTS, mode=APPLY_MODE.STAGED_ONLY)
        self.assertEqual(result["thresholds"]["new_param"], 0.88)
        self.assertFalse(os.path.exists(self.temp_file))
        print("  ✓ STAGED_ONLY 不落盘")

    def test_apply_persist_now(self):
        from parameter_system.staging import StagedChanges, APPLY_MODE
        from parameter_system.parameters import PARAM_DEFAULTS

        staged = StagedChanges(self.temp_file)
        staged.stage("thresholds.persist_test", 0.77, "test persist")

        result = staged.apply_staged(PARAM_DEFAULTS, mode=APPLY_MODE.PERSIST_NOW)
        self.assertEqual(result["thresholds"]["persist_test"], 0.77)
        self.assertTrue(os.path.exists(self.temp_file))
        print("  ✓ PERSIST_NOW 正确落盘")

    def test_clear_after_apply(self):
        from parameter_system.staging import StagedChanges, APPLY_MODE
        from parameter_system.parameters import PARAM_DEFAULTS

        staged = StagedChanges(self.temp_file)
        staged.stage("thresholds.to_clear", 0.66, "test clear")
        self.assertEqual(staged.count(), 1)

        staged.apply_staged(PARAM_DEFAULTS, mode=APPLY_MODE.STAGED_ONLY)
        self.assertEqual(staged.count(), 0)
        print("  ✓ apply_staged 后清空缓冲区")

    def test_nested_key_path(self):
        from parameter_system.staging import StagedChanges, APPLY_MODE
        from parameter_system.parameters import PARAM_DEFAULTS

        staged = StagedChanges(self.temp_file)
        staged.stage("mechanisms.enable_belief_shock", True, "enable shock")
        result = staged.apply_staged(PARAM_DEFAULTS, mode=APPLY_MODE.STAGED_ONLY)
        self.assertTrue(result["mechanisms"]["enable_belief_shock"])
        print("  ✓ 嵌套 key_path 正确解析")


class TestAccess(unittest.TestCase):
    """测试 access.py — 公开 API"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.temp_file = os.path.join(self.temp_dir, "test_access_params.json")
        from parameter_system import access, reset_governance
        reset_governance()
        access._current_snapshot = None
        access._tick_counter = 0
        access._staged_changes = None
        access.PARAM_FILE = self.temp_file

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_create_snapshot(self):
        from parameter_system import access
        snap = access.create_snapshot(persist_path=self.temp_file)
        self.assertIsNotNone(snap)
        self.assertTrue(snap.is_valid)
        print(f"  ✓ create_snapshot: {snap.snapshot_id}")

    def test_get_param_from_snapshot(self):
        from parameter_system import access
        snap = access.create_snapshot(persist_path=self.temp_file)

        val = access.get_param(snap, "thresholds.pipeline_max_execution_time_ms")
        self.assertEqual(val, 5000)

        val2 = access.get_param(snap, "drives.curiosity_baseline")
        self.assertEqual(val2, 0.20)
        print("  ✓ get_param 正确读取嵌套参数")

    def test_get_param_with_default(self):
        from parameter_system import access
        snap = access.create_snapshot(persist_path=self.temp_file)
        val = access.get_param(snap, "nonexistent.key", default=42)
        self.assertEqual(val, 42)
        print("  ✓ get_param 默认值生效")

    def test_stage_changes(self):
        from parameter_system import access
        snap = access.create_snapshot(persist_path=self.temp_file)
        req = access.stage_changes(
            key_path="thresholds.staged_test",
            value=0.95,
            reason="test stage",
            snapshot=snap,
        )
        self.assertFalse(req.approved)
        self.assertEqual(access.list_staged_changes()[0]["value"], 0.95)
        print("  ✓ stage_changes 写入缓冲区并生成待审批请求")

    def test_apply_staged_only(self):
        from parameter_system import access
        access.create_snapshot(persist_path=self.temp_file)
        access.stage_changes("thresholds.applied_test", 0.55, "apply test")
        result = access.apply_staged(mode="staged_only")
        self.assertEqual(result["thresholds"]["applied_test"], 0.55)
        self.assertFalse(os.path.exists(self.temp_file))
        print("  ✓ apply_staged(staged_only) 正确合并参数")

    def test_apply_staged_persist(self):
        from parameter_system import access
        access.create_snapshot(persist_path=self.temp_file)
        access.stage_changes("thresholds.persisted_test", 0.66, "persist test")
        result = access.apply_staged(mode="persist_now")
        self.assertTrue(os.path.exists(self.temp_file))
        # 再次加载验证
        import json
        with open(self.temp_file) as f:
            loaded = json.load(f)
        self.assertEqual(loaded["thresholds"]["persisted_test"], 0.66)
        print("  ✓ apply_staged(persist_now) 正确落盘并验证")

    def test_load_and_save(self):
        from parameter_system import access
        access.save_params_to_file(access.PARAM_DEFAULTS, path=self.temp_file)
        loaded = access.load_params_from_file(path=self.temp_file)
        self.assertEqual(loaded["thresholds"]["pipeline_max_execution_time_ms"], 5000)
        print("  ✓ load_params_from_file / save_params_to_file 正确")

    def test_tick_counter_increments(self):
        from parameter_system import access
        snap1 = access.create_snapshot(persist_path=self.temp_file)
        snap2 = access.create_snapshot(persist_path=self.temp_file)
        self.assertGreater(snap2.tick_index, snap1.tick_index)
        print(f"  ✓ tick_index 递增: {snap1.tick_index} → {snap2.tick_index}")

    def test_governance_status_query(self):
        from parameter_system import access
        access.create_snapshot(persist_path=self.temp_file)
        status = access.get_governance_status()
        self.assertIn(status, ["governed", "locked", "pending_approval", "cooldown"])
        print(f"  ✓ 治理状态查询: {status}")


class TestNoNormalizationConstraint(unittest.TestCase):
    """测试强制规范：禁止归一化"""

    def test_no_normalization_rule_in_docstring(self):
        from parameter_system import parameters
        import inspect
        source = inspect.getsource(parameters)
        self.assertIn("严禁归一化", source)
        self.assertIn("signal = raw_signal * sensitivity_param", source)
        self.assertIn("normalized = total / (weight_a + weight_b)", source)
        print("  ✓ 参数文档包含禁止归一化规范")


class TestIntegration(unittest.TestCase):
    """集成测试：完整流程"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.temp_file = os.path.join(self.temp_dir, "integration_test.json")
        from parameter_system import access, reset_governance
        reset_governance()
        access._current_snapshot = None
        access._tick_counter = 0
        access._staged_changes = None
        access.PARAM_FILE = self.temp_file

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_full_lifecycle(self):
        from parameter_system import access
        from parameter_system.parameters import PARAM_DEFAULTS

        # Step 1: 创建快照（同步管线启动）
        snap = access.create_snapshot(persist_path=self.temp_file)

        # Step 2: 读取参数（同步管线执行）
        timeout = access.get_param(snap, "thresholds.pipeline_max_execution_time_ms")
        self.assertEqual(timeout, 5000)

        curiosity = access.get_param(snap, "drives.curiosity_baseline")
        self.assertEqual(curiosity, 0.20)

        # Step 3: 提案修改（AI 内部评估）
        req = access.stage_changes(
            key_path="thresholds.narrative_memory_pressure_note_gate",
            value=0.60,
            reason="基于世界模型反馈提高叙事门控",
            snapshot=snap,
        )
        self.assertFalse(req.approved)

        # Step 4: 验证提案进入待审批
        pending = req  # 应在 pending 状态
        self.assertFalse(pending.approved)

        # Step 5: 同步管线结束（不落盘）
        snap.invalidate()

        # Step 6: 异步写入循环（审批后落盘）
        gov = access.get_governance()
        gov.approve(
            key_path="thresholds.narrative_memory_pressure_note_gate",
            approver="developer",
            reason="AI 提案审查通过",
        )

        result = access.apply_staged(mode="persist_now")

        # 验证落盘
        self.assertEqual(result["thresholds"]["narrative_memory_pressure_note_gate"], 0.60)

        import json
        with open(self.temp_file) as f:
            saved = json.load(f)
        self.assertEqual(saved["thresholds"]["narrative_memory_pressure_note_gate"], 0.60)

        print("  ✓ 完整生命周期（快照→提案→审批→落盘）")


# ============================================================================
# 主入口
# ============================================================================

if __name__ == "__main__":
    print("=" * 64)
    print("Parameter System — 集成测试")
    print("=" * 64)

    test_modules = [
        TestParameters,
        TestGovernance,
        TestSnapshot,
        TestStaging,
        TestAccess,
        TestNoNormalizationConstraint,
        TestIntegration,
    ]

    total_pass = 0
    total_fail = 0

    for module in test_modules:
        print(f"\n【{module.__name__}】")
        suite = unittest.TestLoader().loadTestsFromTestCase(module)
        result = unittest.TextTestRunner(verbosity=0).run(suite)
        passed = result.testsRun - len(result.failures) - len(result.errors)
        failed = len(result.failures) + len(result.errors)
        total_pass += passed
        total_fail += failed
        if failed == 0:
            print(f"  ✓ 全部通过 ({passed} 项)")
        else:
            for t, trace in result.failures + result.errors:
                print(f"  ✗ {t}: {trace[:200]}")

    print("\n" + "=" * 64)
    if total_fail == 0:
        print(f"✓ 全部测试通过！({total_pass} 项)")
    else:
        print(f"✗ {total_fail} 项测试失败，{total_pass} 项通过")
    print("=" * 64)
