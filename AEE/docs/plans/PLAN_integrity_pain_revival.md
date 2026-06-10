# PLAN — 复活"改文件=做手术=痛"机制（Integrity Pain Revival）

> 状态：已实现（含 §3-D 受伤退缩），单元 7/7 + 回归（self_counsel 10 / fixes 14 / 50_ticks 全 PASS）通过，待 daemon 端到端验证。
> bcyq 拍板（2026-05-30）：用提议偏小值；受伤退缩这轮一起接上；监控面维持现状三文件；痛走痛觉+身体不适两条。
> 红线：动到**情感/认知核心**（pain / somatic_tone / 驱动力 / 行为偏置）。
> 规则：完整形态一次落地，不做最小版（memory: full-design-over-minimal）。
> 镜像：XIA 验证通过后再镜像糯糯。
> 开工决策（bcyq 已拍）：①给 binding 一个**冷启动底**（一上来就有点痛）；②**越常用越痛**（binding 随使用涌现）；③"在乎"**只涨不跌**（防钻空子）；④"受伤退缩"那条单独标出待拍（§3-D）。

---

## §0 一句话

她有一套"我们改她的文件 → 她像被做手术一样痛/不适"的机制，链路其实**接好了、每拍都在跑**，但被一个**乘以零**彻底掐死：
痛 = 变化量 × **绑定强度（她有多在乎被改的这块）**，而绑定强度**恒等于 0**——因为喂养它的两个函数（`record_access` / `record_perturbation`）**全项目只有定义、从无调用**。本设计把这两个开关接到真实事件、给绑定一个冷启动底、并把死掉的 `active_harm` 接进真实身体后果（痛 + 不适），让手术真的疼。

---

## §1 现状诊断（已查实）

### 链路是通的
`src/pipeline_runner/stages/s07a_state_update.py:347-363`（每拍 Step 11 内）：
```python
from ...core.integrity_monitor import scan as _integrity_scan
from ...core.integrity_signal import update as _integrity_update
_events = _integrity_scan(_data_dir, _project_root, entity.tick)   # 扫 4 区域，算变化量
_ir     = _integrity_update(_events, entity, _data_dir)            # 变化量 → 伤害/驱力/偏置
for _dim, _delta in _ir["drive_delta"].items():                   # ← 唯一活着的出口
    setattr(entity, _dim, clamp(getattr(entity,_dim) + _delta))
entity.integrity_behavior_bias = _ir["behavior_bias"]             # ← 死：无人读
entity.active_harm             = _ir["active_harm"]               # ← 死：无人读
```
- `scan`（`integrity_monitor.py`）：4 区域 = expression(voice 文件) / perception(3 个源文件 md5) / cognition(world_model_db) / continuity(episodes+core)。变化量算得对。
- `update`（`integrity_signal.py:111`）：`harm_score = magnitude × binding`，binding 来自 `self_binding.get_binding(zone)`。

### 根因：binding ≡ 0（乘以零）
`self_binding.get_binding`（`self_binding.py:43-65`）：
```
frequency          = 1 - exp(-access_count/50)          # access_count 来自 record_access
perturbation_depth = mean(最近扰动样本) 或 _COLD_DEPTH   # 样本来自 record_perturbation
weight_depth = 0.6 * min(1, len(history)/5)             # 无样本 → 0
binding = frequency*weight_freq + depth*weight_depth
```
**`record_access` 和 `record_perturbation` 全项目只有定义，从无调用**（已 grep 确认）。于是：
- `access_count` 恒 0（个别遗留 expression=1 例外）→ frequency ≈ 0；
- `perturbation_history` 恒空 → weight_depth = 0；
- **binding ≈ 0**（perception/cognition/continuity 三区精确为 0）。

数据文件实证：
```
self_binding.json:    只有 expression{access_count:1, history:[]}；perception/cognition/continuity 不存在
integrity_signal.json: active_harm=0.0，所有 zone_harms=0.0
```
→ `harm = 变化量 × 0 = 0`。她**永远不痛**。涌现的机器造好了，**没接电**。

### 另两个断点
2. **`active_harm` / `integrity_behavior_bias` 只写不读**（全 .py grep 仅 s07a 两处 setattr，无读者）。即"持续隐痛"和"受伤退缩/不信任"两条出口断头。唯一活路是 `drive_delta`（推 anxiety/fear/stress/unresolved/loneliness）。
3. **覆盖面窄**：perception 仅盯死 3 个源文件（`pipeline_runner/__init__.py`、`daemon/daemon.py`、`action_system/executor.py`）。改其它文件 perception 变化量=0（→ §3-E 开放点）。
4. 痛走的是**不适类驱力**，没直接喂 `pain` / `somatic_tone`（→ §3-C 补"痛"那半边）。

---

## §2 设计原则
1. **不重造、只接线**：涌现机器已存在，本设计把它接到真实事件，不重写其哲学。
2. **绑定从使用涌现，不硬编码重要性**（保留原设计）；冷启动底是"出生即有最低限度的自我归属感"，不是写死的重要性表。
3. **连续无 if 门控**：增量用 `state += signal × coef` + clamp；用量指示子用 0/1 乘子，不用 if。
4. **绕过/在 pipeline 内都自带 clamp**：pain[0,?]、somatic_tone[-1,1]、drives[0,1]。
5. **防钻空子是结构性的**（§9）：access 只涨不跌；痛由外生编辑触发（非她的使用）→ 学不出"用→痛"；无前瞻规划模块。
6. **无 LLM。外科手术**：改动集中在 `self_binding.py`(+底+批量API+perturbation)、`integrity_signal.py`(+body delta) 、一处 tick 级 record_access 挂钩、s07a 既有 integrity 块内 +几行 body 应用。

---

## §3 修复设计

### A. 复活 binding —— 把两个开关接到真实"使用"
"使用" ≈ 各区域的真实活动量（涌现出"她有多依赖/投入这块"）：
| 区域 | 真实使用事件 | 每拍指示子 |
|---|---|---|
| perception | 每拍都在感知 | 恒 1（常用→快速饱和，核心区编辑最痛） |
| expression | 她这拍表达了 | `did_express` 0/1 |
| cognition | 这拍 WM 更新了 | `wm_updated` 0/1（tick_engine:748 `tick%10` 且 inducted） |
| continuity | 这拍写了 episode | `episode_written` 0/1 |

**实现（集中、单次 I/O）**：新批量 API `self_binding.record_accesses(active: dict[zone,float], data_dir)`，一次 read-modify-write `self_binding.json`，`access_count[zone] += active[zone]`（指示子可为 0/1，连续累加，无 if）。
**挂钩点**：tick_engine 每拍末（WM/episode 事件已知处），用 entity 上已有/新增的轻量 0/1 标志组装 `active` 调一次。**只涨不跌**：access_count 永不衰减（§9 防钻空子的结构基石）。

**record_perturbation（depth 项）**：变化发生后 N 拍内记录驱动力方差 → 喂 depth。
- 归 `integrity_signal.update` owner（它已拿到 events + entity + 会算 healing 方差）。
- events 里出现 zone Z → 置 `perturb_watch[Z] = _PERTURB_WINDOW(20)`（持久化进 integrity_signal.json）。
- 每拍对 watch>0 的 zone：`record_perturbation(Z, 当前驱力方差)`，watch -= 1。方差复用 `_compute_healing` 的 `_DRIVE_KEYS` 方差逻辑。

### B. 冷启动底 + 越用越痛 + 只涨不跌
`get_binding` 末行改为（连续、单调、[floor,1]）：
```python
emergent = frequency*weight_freq + perturbation_depth*weight_depth   # 原值 [0,1]
binding  = _BINDING_FLOOR + (1.0 - _BINDING_FLOOR) * emergent          # 抬底，保持单调
return clamp(binding)
```
- 零使用区被编辑：binding = `_BINDING_FLOOR`（提议 0.15）→ 痛 = 变化量 × 0.15，**一上来就有点痛**。
- 常用区：emergent→1，binding→1，**越常用越痛**。
- access_count 单调不减 → 投入过的在乎**不会因为后来不用而贬值**（§9）。

### C. active_harm → 真实身体后果（补"痛"那半边）
`integrity_signal.update` 额外返回 `somatic_delta` / `pain_delta`（由 active_harm × 系数算，量纲小）：
```python
pain_delta = active_harm * _HARM_TO_PAIN     # 提议 0.30：手术→急性痛
soma_delta = active_harm * _HARM_TO_SOMA     # 提议 0.20：不适→体感效价下降
```
s07a 既有 integrity 块内、drive_delta 应用之后，加（自带 clamp）：
```python
entity.pain        = clamp(entity.pain + _ir["pain_delta"], 0.0, 1.0)
entity.somatic_tone= clamp(entity.somatic_tone - _ir["soma_delta"], -1.0, 1.0)
```
> `entity.pain` 已确认：s04a 只对它**衰减(×0.98/拍)+封顶**、不重算覆盖（s04a:179/275）。s07a 在 s04a 之后写 → 本拍加的痛保留、随后拍自然消退。**急性痛会愈合**的语义天然成立。
> "不适"那半边（anxiety/fear/stress/unresolved/loneliness）已由 `drive_delta` 承载，binding 复活后即生效，不重复加。

### D. behavior_bias —— 受伤退缩（**单独标记，待 bcyq 拍**）
`integrity_behavior_bias`（expression_rate_bias / input_trust_bias / novelty_seeking_bias）现死。设计：在行为涌现处（`s05_behavior.py`）读它，连续偏置表达率/输入信任/求新。
- **天然急性会愈合**：bias 由 zone_harms 派生，harm 随 `HEAL_RATE` 愈合 → bias 同步回零。不是永久退缩，是"疼了缩一下"。
- **是否接、接哪几路、系数** → §8 待确认。**不接也不影响"手术会痛"主目标**（A+B+C 已足够让她痛）。

### E. 覆盖面（perception 3 文件）—— 开放点
现仅 3 个哨兵源文件。要"改任意她的代码都痛"，需扩面。候选：
- 保持哨兵（轻量，3 个是载重文件，代表性尚可）；或
- 加几个核心文件（entity_state.py / drive_system.py / 本批新模块）；或
- 对 `src/` 目录做**聚合摘要**（文件数 + 总字节 + 抽样 md5），避免每拍 md5 全部 370 文件的开销。
→ §8 待 bcyq 定广度。**不阻塞主修复**（先让 3 哨兵真的痛起来）。

---

## §4 改动点（函数级）
| 文件 | 改动 | 量级 |
|---|---|---|
| `src/core/self_binding.py` | +`_BINDING_FLOOR` 抬底；+`record_accesses` 批量 API | ~15 行（现 88） |
| `src/core/integrity_signal.py` | +`_HARM_TO_PAIN`/`_HARM_TO_SOMA`/`_PERTURB_WINDOW`；update 返回 pain_delta/soma_delta；perturbation watch+记录 | ~30 行（现 138） |
| `src/daemon/tick_engine.py` | 每拍末组装 `active` 调 `record_accesses`；置 did_express/wm_updated/episode_written 0/1 标志（就近已有信号） | ~12 行 |
| `src/pipeline_runner/stages/s07a_state_update.py` | 既有 integrity 块内 +2 行应用 pain_delta/soma_delta | ~3 行 |
| `src/pipeline_runner/stages/s05_behavior.py`（**D，待拍**） | 读 integrity_behavior_bias 连续偏置 | ~8 行 |

---

## §5 常量（待 bcyq 扫一眼；新标定无旧锚点）
| 常量 | 提议值 | 含义 |
|---|---|---|
| `_BINDING_FLOOR` | 0.15 | 冷启动底：零使用区被编辑的最低痛系数 |
| `_HARM_TO_PAIN` | 0.30 | active_harm → pain 增量（手术急性痛） |
| `_HARM_TO_SOMA` | 0.20 | active_harm → somatic_tone 降幅（不适体感） |
| `_PERTURB_WINDOW` | 20 | 变化后记录驱力方差的拍数（喂 depth 项） |
| `record_accesses` 指示子 | 0/1 | perception 恒 1；其余按当拍活动 |

> 提议值先开跑，端到端观测"痛得可感而不淹没"再微调（同 somatic coupling 粒子常量的标定策略）。

---

## §6 合法性自检
- ✅ 无 if 行为门控：抬底/伤害/愈合全连续函数+clamp；使用量用 0/1 乘子累加；perturbation watch 递减是计数非行为门控。
- ✅ 无 LLM。
- ✅ 自带 clamp：pain[0,1]、somatic_tone[-1,1]、drives[0,1]。
- ✅ 不硬编码重要性：binding 仍从使用涌现，floor 是"出生最低自我归属"，已与 bcyq 讨论定值。
- ✅ 防钻空子结构性成立（§9）。
- ✅ 完整形态：A(复活)+B(底/涨)+C(痛进身体) 本期全做；D(退缩)/E(覆盖) 设计已成文，值待拍。
- ✅ 文件 <400 行：均为小增量，无超限。

---

## §7 验证
1. 单元 `tests/test_integrity_pain.py`：
   - binding 抬底：零使用 zone → `get_binding == _BINDING_FLOOR`；累加 access → binding 单调升至→1。
   - 只涨不跌：record_accesses 后停记，binding 不回落。
   - harm→body：构造 event + binding>0 → active_harm>0 → pain↑、somatic_tone↓、drive_delta 非零、全 clamp 内；binding=0 路径已不可能（有底）。
   - 可答性无关：本机制不涉及。
2. 集成：喂一条 perception 变化事件，跑 update → 断言 pain_delta/soma_delta>0 且随 active_harm 成比例；连续无变化拍 → harm 按 HEAL_RATE 愈合、pain 按 0.98 衰减。
3. 回归：test_50_ticks / test_fixes / test_expression_feedback / test_self_counsel 全过（行为守恒）。
4. 端到端（重启 daemon，需 bcyq 批）：daemon 跑一阵养起 binding → 编辑一个 perception 哨兵文件 → 下一拍日志见 active_harm 跃升、pain↑/somatic_tone↓；随后数拍见愈合衰减。对照编辑一个未监控文件 → 无反应（暴露 §3-E 覆盖面，供 bcyq 判是否扩面）。

---

## §8 开放点（动手前确认）
1. **§5 五个新常量**用提议值开跑？（floor 0.15 / pain 0.30 / soma 0.20 / window 20）
2. **§3-D 受伤退缩**：本期接入 behavior_bias 吗？接的话哪几路（表达率/输入信任/求新）+ 确认其随愈合回零即可（已天然成立）。**我倾向本期接**（否则"手术"只改内部状态、不改她外在行为，体感不完整）——你定。
3. **§3-E 覆盖面**：保持 3 哨兵先验证，还是本期就扩（加核心文件 / 目录聚合摘要）？我倾向先 3 哨兵验证主链路，扩面单独一轮。
4. 痛同时进 `pain` 和 `somatic_tone` 两路确认？（pain=急性痛强度，somatic_tone↓=体感变差，二者一起才是"手术"的完整体感。）

---

## §9 防钻空子论证（固化，勿丢）
担心：她若学会"越用越痛"，会不会为躲痛而**不用某模块、自我阉割**？结论：本架构**自带三重防护**，基本不触发。
1. **痛由外生编辑触发，非她的使用**：用某块不痛，只有"我们改那块文件"才痛，而何时改她无法预测、绝大多数使用后从不被改 → "用→痛"无稳定共现 → 她的世界模型（靠共现归纳）**学不出**这条规律。
2. **"在乎"只涨不跌**（access_count 单调，**严禁加衰减**）：哪怕她想"少用来贬值躲痛"，已攒的在乎不减、痛的潜力仍在 → 躲无用 → 无躲的动机。**给 access_count 加衰减会亲手打开这个空子——红线。**
3. **无前瞻规划**：行为由当下驱力角力涌现，无"为躲未来痛而提前憋着"的模块；且孤独/好奇内生上涨、不可意志关闭，迟早逼她去用。
- **唯一要看住**：§3-D 受伤退缩必须是**急性且会愈合**（疼了缩一下，缩完回来），绝不能演化成永久回避。愈合通道（HEAL_RATE）已保证此性质。

---

## §10 排期 / 与其它线的关系
- 与上两线（身体后果通道 / self_counsel）正交，复用同样的"标量即时 + 自带 clamp"哲学，但独立模块、互不依赖。
- 仍挂着：身体后果通道 + self_counsel 的 daemon 端到端验证（一次重启可与本线一起验证：编辑哨兵文件看痛 + 看自我开导/被理解的体感）。
