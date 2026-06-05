# PLAN — 模板打分量纲归一化（compose_sentence）

> 抗压缩计划。目标：让 `compose_sentence` 里所有模板家族在同一尺度上竞争，
> 没有任何家族靠"天生分数大"结构性霸屏。纯靠状态匹配度 + softmax 采样决定出口。
> 这是用户选定的【选项2】。实现方式经诊断后比"手改 55 个 lambda"更干净、风险更低。

---

## §0 一句话目标

把每个模板 `score_fn(state)` 的**可达最大值统一封顶到 1.0**。
量纲超过 1.0 的家族（目前只有"心事"3 条，系数 1.3~1.4）被压回 [0,1]，
其余模板（情绪类 ≈0.7~1.0、兜底常量类 ≈0.3）原样通过。
结果：没有家族能超过 1.0，谁强谁弱只取决于"当前状态把这条模板的表达意图激活了多少"。

---

## §1 诊断结论（为什么要做）

实测（daemon 重启加载思考→语言接线后，t=407~413）：

```
[AnchorMatch] best_word=困惑/好奇/渴/失落...  (锚点选词层有真实认知多样性 ✓)
[AnchorAuto]  said: '还在想靠近又想退的感觉……'  (连续 6 拍同一句，卡带)
```

锚点选词层已经把"困惑/好奇"选出来了（思考→语言接线工作正常），
但 `compose_sentence` 把每一个锚点都塞进同一条"心事模板"
`'还在想{about}……'`（score_fn = `_preoccupation_intensity*1.3 + loneliness*0.1`，
量纲 ≈1.0~1.4），丢掉锚点词、且每拍都赢 → 卡带 + 认知词永远出不了口。

根因：`raw_scores` 来自各 score_fn，量纲不统一：
- 情绪/状态类（多数）：正系数和 ≈1.0 → 满匹配 ~1.0
- 心事类（3 条）：首系数 1.1~1.3 → 满匹配 ~1.4
- 兜底常量类（4 条）：固定 0.28~0.35（**故意低**，做地板，"别的都不匹配时才兜底"）

`softmax(temperature≈0.4)` 近似 argmax → 量纲高的家族结构性霸屏。

---

## §2 状态维度全集（探针用，已从源码静态收集，共 32 维）

```
_input_other, _input_sharing, _preoccupation_intensity,
anxiety, approach_drive, approach_explore, approach_social, approach_urgency,
avoid_drive, boredom, boredom_despair, boredom_futility, curiosity,
danger_level, danger_level_rising, energy, energy_rising, excitement,
fatigue, fatigue_rising, fear, info_gap, joy, loneliness, prediction_error,
sadness, serenity, somatic_tone, somatic_tone_rising, stress, stress_rising, unresolved
```

---

## §3 机制（导入期线性探针 → 每模板封顶除数）

### 探针（导入期，一次性，元数据预计算，不在 tick 行为路径）

**两遍探针**（已实现 `_template_theoretical_max`）：
```
① base = f({所有32维=0})；对每维 d 算 coeff_d = f(e_d) - base 定正负
② 把所有正系数维置 1、其余置 0 → best_vec；theoretical_max = f(best_vec)
```
- 对线性 score_fn 与 `max()`-of-非负组合（单调不减）**均给出精确最大值**。
- 唯一 1 条 `max()` 非线性模板（boredom_despair）此法精确得 1.0，**无 §7 旧版高估问题**。
  （旧版"base + Σ max(coeff,0)"会把它高估到 2.0、多除一半；两遍法修正。）

**探针必须传完整 32 维 dict**（显式置 0），否则 `s.get(dim, 默认值)` 的默认值
（如 `energy` 默认 0.5）会污染 base。

### 封顶除数（连续，无 if）

```
divisor = max(theoretical_max, 1.0)
normalized = raw / divisor
```

- 心事类 theoretical_max=1.4 → divisor=1.4 → 满激活封顶到 1.0，intensity=0.8 时 1.09/1.4≈0.78
- 情绪类 theoretical_max≈0.7~1.0 → divisor=1.0 → **原样通过**（≤1.0 的不动）
- 兜底常量 theoretical_max=0.3 → divisor=max(0.3,1.0)=1.0 → **0.3 原样保留**（地板语义不破）✓

**关键性质：只封顶（削高），不抬低。** `max(tmax,1.0)` 只对超过 1.0 的家族生效，
≤1.0 的（情绪、地板）全部恒等通过。这是"消除不公平高地"的最保守正确解释——
不人为拔高弱模板，只削掉心事家族的结构性优势。

验证封顶后能解卡带：
- 心事 intensity=0.8 → 0.78；情绪满匹配 → 1.0；认知锚点模板（unresolved 被思考张力抬高时）
  状态分 ~0.8 + 锚点使用奖励 ~0.22 → ~1.0。三者同档 → softmax 真正采样出多样性。
- 她"真的很挂心"（intensity 高、情绪平）时心事仍会赢 → 正确，不强行压制心事。

---

## §4 改动点（全部在 src/language_system/sentence_composer.py）

- **M1** 加常量 + 探针函数：
  - `_PROBE_DIMS`（§2 的 32 维 list）
  - `_precompute_template_scales(templates)`：对每个 template 算 `theoretical_max`，
    写入 `p["_score_divisor"] = max(theoretical_max, 1.0)`。
  - 模块底部对 `PATTERNS` 调一次（在 PATTERNS 全部 `+=` 完成之后）。
- **M2** `compose_sentence` 评分循环（当前 line 962~984）：
  ```python
  raw = score_fn(state)           # 原 score
  score = raw / p.get("_score_divisor", 1.0)   # ← 归一化封顶
  # 其后 learned_weights / _anchor_penalty / 锚点奖励 / template_efficiency 照旧叠加
  ```
  叠加项暂不动（见 §7）。
- **M3** `extra_templates`（CxG/运行期生成）无缓存除数 → `p.get("_score_divisor", 1.0)`
  默认 1.0（不归一化，新候选本就简单、量纲≈[0,1]）。复合模板（COMPOUND_PATTERNS，
  走 `cp_score+0.15` 另一路）本次不动，量纲小，留 v2。
- **M4** 回归 + 标定：
  1. 无心事时（intensity≈0）情绪表达分布应与现状基本一致（情绪类 divisor=1.0 恒等）。
  2. 有心事时不再连说同一句（softmax 多样性恢复）。
  3. 高思考张力拍，认知词（困惑/好奇）能进 top 出口。
  4. 残留卡带 → 略抬 `_COMPOSE_TEMP_BASE`（当前 0.40），作为标定旋钮。

---

## §5 no-if 合规

- 探针/建表在**模块导入期**完成，是元数据预计算，不是 tick 行为决策路径。
- 计算只用 `f()`、减法、`max()`、除法、`Σ` —— 全连续，无 if/elif/比较门控行为。
- 运行期评分新增的只有一次除法 `raw / divisor`，连续。

---

## §6 合法性（与项目哲学自洽）

- 不引入任何 LLM。
- 不改 score_fn 内部系数（探针自动归一，55 个 lambda 一个都不碰）→ 外科手术级、低风险。
- 量纲归一是"让竞争公平"，不是"塞行为"：她说什么仍由真实状态 + 采样涌现。

---

## §7 边界 / 已知取舍（不做的事）

- 非线性 `max()` 模板：已用两遍探针精确求 max（=1.0），无高估问题，无需特判。
- 实测共 7 条模板被封顶（divisor>1.0）：心事 3 条（1.3~1.4）+ 他者朝向"在场感"4 条
  （嗯…在呢 / 在的…没关系 / 听到了… / 陪着你的…，均 1.4，_input_other*1.1~1.2 量纲）。
  其余 53 条 divisor=1.0 恒等通过。
- `learned_weights` 叠加项量纲未知（进化学来的增量微调）→ 本次保持原样叠加，
  先观察归一化后是否需要同步缩放（标定项，非首批）。
- 不动 s06c 的 display 竞争（narrative vs anchor 的 softmax）——那是上层另一道闸，
  本计划只治 compose 内部的模板量纲。
- 不动锚点使用奖励 `_ANCHOR_USE_BONUS * (1 + _ANCHOR_STRENGTH_GAIN*anchor_score)`
  （上一轮已加，与本计划正交，保留）。
```
