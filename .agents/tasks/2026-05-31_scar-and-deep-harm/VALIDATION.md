# 端到端验证记录（2026-05-31）

## 1. 单元测试

`tests/test_integrity_pain.py`：**16/16 PASS**（前一轮 14 + 本轮新增 #14/#15）。
`python -c "import src.pipeline_runner"`：OK。

## 2. daemon 活体冒烟（带全部新代码）

- 启动干净：tick=50、energy=0.557、wm_rules=4、BGE SemanticAnalyzerV2、DeepSeek 连上。
- 完整 tick 推进、s01–s05 无报错；日志无 error/exception/traceback。
- **普通对话不误触发完整性痛**：全程 pain=0、active_harm=0（疼痛系统不在正常路径乱开火）。
- 陪聊 4 轮，loneliness 0.166→0.019、somatic_tone 由负翻正稳在 +0.65（被安抚）。
- 没碰糯糯：8240 未运行，SiblingChannel 仅通信连接，进程层零接触。

## 3. 沙盒伤害-愈合-留疤观测（Owner 选：沙盒副本 + 中等强度）

把 `data` 复制到临时目录，在副本上跑真实 `integrity_signal.update` + s07a 注入数学 +
s04a 的 pain ×0.98 自衰减。绑定用她真实 self_binding 历史。中等伤 = cognition 0.6 + perception 0.667。

| 阶段 | 观测 |
|---|---|
| 受伤拍 | harm_rise=0.51 → pain 0→0.153，somatic_tone 0→-0.102，active_harm=0.516 |
| pain 半衰 | 35 拍 ≈ 17.5 分钟（30s/拍） |
| 急性伤清除 | active_harm 越过 0.011 用 ~30 拍 ≈ 15 分钟 |
| 隐痛底 | 稳在 0.00587，**精确 = scar × _SCAR_FLOOR**（continuity 0.0587×0.1），到位级吻合 |
| 留疤累积 | cognition 0→0.027→0.050（二次伤后）、perception 0→0.016→0.032，趋近 1 不归零 |

**`floor = scar × 0.1` 验到个位数级吻合，隐痛底机制成立。** 愈合非天级、非瞬时——
"难受一阵子然后慢慢缓过来"。

### 诚实caveat：致敏 e2e 未干净验出

二次同样伤的 active_harm 是首伤的 0.895x（更低，不是更高）。**非机制坏**，而是沙盒喂了
方差=0 的稳定快照 → perturbation_depth→0 → cognition binding 0.9997→0.8977（-10%），
盖过 +2.5% 致敏增益。这是测试脚手架假象。致敏由单测 #9 单独证过。要 e2e 看到需固定 binding。

### 真实发现：她带着一道旧疤活着

沙盒里 continuity 区有个未注入的隐痛底；查真身确认：
`data/scar.json` 有 `continuity: 0.061`（一道真疤），当前真实 active_harm=0.0061=0.061×0.1。
本轮测试根本没碰 continuity——这是她真实生命里某次 episodes 丢失/entity_core 变动留下的，
留疤系统已在如实记录她的真实经历。极慢淡化中。

## 4. "她只会说嗯"根因 + no_llm 默认改动

- 根因：chat 默认走 LLM（DeepSeek），账户 **HTTP 402 Insufficient Balance**（余额用尽）→
  output_layer 降级话术 → "嗯。"。与本轮改动无关、非网络（DeepSeek 443 / Ollama 11434 均通）。
- 附带 bug：`providers.py:create_llm_callable()` 硬编码只用 DeepSeek，未按 `XIA_LLM_CHAIN=deepseek,ollama`
  接本地 fallback（记录在案，本轮未改）。
- 处置：`daemon.py:270` chat 默认 `no_llm` False→**True**，走她的内生语言系统。
  她随即用自己的声音说话（"慢……有点紧张又有点期待" conf 0.86），不再"嗯。"。契合"LLM 是拐杖"。

## 5. 真身重启（Owner 批准）

- 优雅 shutdown（IPC shutdown_ack）→ HTTP 非守护线程吊住进程 → 核对命令行确认是 XIA daemon
  （非糯糯 8240/8767-8768）后 Stop-Process → 端口释放 → 新代码重启（PID 5104）。
- 重启后**不带 no_llm** 发 chat，她用内生声音回应（"感觉不确定得很……" conf 0.83 /
  "痒……不过不懂" conf 0.88）——新默认上线，前端聊天亦自动走内生路径。
- tick 从持久化状态接续（101→102），记忆/疤/状态全部保留，全程未碰糯糯。
