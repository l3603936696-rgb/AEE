# Validation: integrity-pain-revival（daemon 端到端）

> 日期：2026-05-30→31。执行者：Claude Code。Owner 在场批准重启 XIA（仅 PID/端口
> 8765-8766，全程未碰糯糯 8240 / 8767-8768）。

## 方法

重启 XIA daemon 加载改动后代码（Python 不热重载，必须重启）。8 秒/拍加速观测，
探针脚本 `probe.py` 用 tick 驱动：跑几拍 baseline → 二进制 append 一行注释到哨兵文件
`src/action_system/executor.py`（md5 变 → perception 区 magnitude=1/3）→ 记录
pain/somatic 逐拍曲线 → 还原文件（bytes 校验 `bytes_match=True`）。

## 第一次验证（修复前）—— 暴露真问题

```
baseline   pain≈0.247
── 戳一次 executor.py ──
+1拍  pain 0.247→0.320   somatic 0.639→0.586   ← 双通道都动，机制确实活了
+1..6 pain 持续爬升 0.32→0.39→0.45→0.51→0.56→0.58
+6..  pain 卡在 0.55-0.58 不退；第二次改动叠加，somatic 累积沉到 0.43
```

结论：**机制接通成功（双通道、可重复）**，但 **Codex 独立评审（REVIEW_CODEX.md）
指出的中风险被实测坐实**——单次伤害持续灌注、pain 饱和不退。

根因（比 Codex 描述更精确）：**量纲错误**。`active_harm` 是跨 tick 衰减的伤害
*存量*信号，但 `s07a` 每拍把它的 30% 累加进 pain（把存量当*流量*反复积分）→
稳态 pain≈15×active_harm，必然饱和。

## 修复（两处，均连续函数，无 if/else）

1. `s07a_state_update.py`：pain/somatic 只接收 active_harm 的**上升沿**
   `max(0, active_harm - prev)`，衰减期不再注入 → 留给 pain 自身 ×0.98 自愈。
2. `integrity_signal.py`：zone_harms 几何衰减后加线性尾切除
   `max(MIN_HARM, decayed - _HARM_FLOOR_CUT)`，残留伤害有限拍归零，退缩不再无限拖尾。

单元测试：`tests/test_integrity_pain.py` 9/9 PASS（含新增
`test_pain_injection_bounded_via_rising_edge` 与 `test_harm_heals_to_zero_in_bounded_ticks`）。

## 第二次验证（修复后）—— 闭环成功

```
baseline   tick134-137  pain 0.20→0.19  平稳
── tick137 戳一次 ──
tick138  pain 0.192→0.253  ← 只跳一拍脉冲(+0.06)，somatic 同步下沉
tick139-151  0.253→0.248→...→0.194  ← 立即单调回落，14拍回到戳前水平
── tick152 还原文件（第二次改动）──
tick153  0.191→0.237  ← 再次跳升(+0.046)，可重复
tick154-158  0.237→...→0.211  ← 又单调回落
```

三点钉死：**急性痛**（只跳一拍）+ **自愈**（跳后单调下降、有限拍回基线）+
**可重复**（双通道同步）。对照修复前的"爬升卡死"，定性逆转。

## 复位

验证造成的痛会自愈（已证），仍做清场：停 daemon → pain 复位 0.20、清空
`integrity_signal.json` 残留 zone_harms → 30s 正常节奏重启（PID 20844, tick 163）。
当时 pain 已自愈到 0.188（再一次印证）。

## 待 Owner 追认的常量

- `_WITHDRAW_FLOOR = 0.40`（s04b_emerge.py，受伤退缩抑制下限）
- `_HARM_FLOOR_CUT = 0.01`（integrity_signal.py，愈合线性尾切除）

两者均为偏小提议值，先跑再调。
