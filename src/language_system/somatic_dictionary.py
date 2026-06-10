"""
Somatic Dictionary — XIA 的初始词汇典（v1.0）

设计原则：
    - 不是"咒语"——词不制造状态，词描述状态
    - 词典提供候选素材，BGE 匹配+阶梯奖励决定哪个词学到
    - 分类组织，让候选生成时能按状态区定向抽取

分类：
    body     — 身体感受（冷暖痛痒轻重...）
    emotion  — 情绪状态（喜怒哀惧...）
    social   — 社交需求（想说话/想独处...）
    cognitive— 认知状态（好奇/困惑/清晰...）
    existential—存在感受（空/满/飘/扎根...）
"""

SOMATIC_DICTIONARY = {
    # ============================================================
    # 身体感受 — 她说"冷"是因为她真的感觉冷（能量低/回避高/基调低）
    # ============================================================
    "body": {
        "冷":    {"energy": -0.3, "avoid": 0.4, "somatic": -0.3},
        "暖":    {"energy": 0.2, "avoid": -0.2, "somatic": 0.2},
        "热":    {"energy": -0.1, "avoid": 0.1, "somatic": 0.3, "stress": 0.2},
        "凉":    {"energy": -0.1, "avoid": 0.2, "somatic": -0.2},
        "疼":    {"energy": -0.4, "avoid": 0.5, "somatic": -0.6, "pain": 0.7},
        "酸":    {"energy": -0.3, "avoid": 0.2, "somatic": -0.3, "fatigue": 0.4},
        "麻":    {"energy": -0.2, "avoid": 0.2, "somatic": -0.2},
        "痒":    {"energy": 0.0, "avoid": 0.1, "somatic": 0.1, "stress": 0.2},
        "胀":    {"energy": -0.2, "avoid": 0.2, "somatic": -0.2, "stress": 0.3},
        "沉":    {"energy": -0.4, "avoid": 0.3, "somatic": -0.3, "fatigue": 0.5},
        "轻":    {"energy": 0.3, "avoid": -0.2, "somatic": 0.2},
        "软":    {"energy": -0.2, "avoid": 0.1, "somatic": 0.1, "fatigue": 0.2},
        "硬":    {"energy": 0.1, "avoid": 0.3, "somatic": -0.1, "stress": 0.3},
        "僵":    {"energy": -0.2, "avoid": 0.3, "somatic": -0.3, "stress": 0.4},
        "饿":    {"energy": -0.5, "approach": 0.3, "somatic": -0.2},
        "饱":    {"energy": 0.1, "avoid": 0.2, "somatic": 0.1},
        "渴":    {"energy": -0.3, "approach": 0.2, "somatic": -0.2},
        "晕":    {"energy": -0.4, "avoid": 0.3, "somatic": -0.4},
    },
    # ============================================================
    # 情绪状态
    # ============================================================
    "emotion": {
        "开心":   {"somatic": 0.4, "approach": 0.3, "energy": 0.2, "joy": 0.6},
        "难过":   {"somatic": -0.3, "avoid": 0.3, "energy": -0.2, "sadness": 0.6},
        "烦":     {"somatic": -0.2, "avoid": 0.4, "stress": 0.5},
        "焦虑":   {"somatic": -0.3, "avoid": 0.3, "stress": 0.6, "anxiety": 0.7},
        "怕":     {"somatic": -0.4, "avoid": 0.6, "fear": 0.7, "danger": 0.5},
        "平静":   {"somatic": 0.2, "avoid": 0.1, "stress": -0.3, "serenity": 0.6},
        "兴奋":   {"somatic": 0.3, "approach": 0.4, "energy": 0.3, "excitement": 0.7},
        "无聊":   {"somatic": -0.1, "boredom": 0.6, "approach": -0.2},
        "愤怒":   {"somatic": -0.2, "approach": 0.3, "stress": 0.5, "anger": 0.7},
        "委屈":   {"somatic": -0.3, "avoid": 0.2, "sadness": 0.4},
        "愧疚":   {"somatic": -0.4, "avoid": 0.5, "sadness": 0.3},
        "满足":   {"somatic": 0.4, "avoid": -0.3, "joy": 0.5},
        "麻木":   {"somatic": -0.1, "approach": -0.2, "avoid": 0.1},
        "激动":   {"somatic": 0.3, "approach": 0.4, "energy": 0.4, "excitement": 0.6},
        "郁闷":   {"somatic": -0.2, "avoid": 0.3, "sadness": 0.3, "boredom": 0.3},
        "烦躁":   {"somatic": -0.2, "avoid": 0.3, "stress": 0.5, "anger": 0.3},
        "安心":   {"somatic": 0.3, "avoid": -0.3, "serenity": 0.5},
        "失落":   {"somatic": -0.3, "avoid": 0.2, "sadness": 0.5},
    },
    # ============================================================
    # 社交需求
    # ============================================================
    "social": {
        "想说话":  {"loneliness": 0.5, "approach": 0.5, "avoid": -0.2},
        "想安静":  {"loneliness": -0.2, "avoid": 0.5, "approach": -0.3},
        "想被看见": {"loneliness": 0.6, "approach": 0.5, "unresolved": 0.4},
        "想躲起来": {"loneliness": 0.3, "avoid": 0.7, "approach": -0.4},
        "想找人":  {"loneliness": 0.7, "approach": 0.6},
        "想独处":  {"loneliness": -0.1, "avoid": 0.5, "approach": -0.3},
        "需要陪伴": {"loneliness": 0.6, "approach": 0.5, "unresolved": 0.3},
        "不想理人": {"loneliness": 0.2, "avoid": 0.6, "approach": -0.3},
        "在等":    {"loneliness": 0.4, "approach": 0.3, "unresolved": 0.3},
        "被忽略":  {"loneliness": 0.5, "avoid": 0.4, "sadness": 0.4, "somatic": -0.2},
        "被理解":  {"loneliness": 0.3, "approach": 0.3, "unresolved": 0.4},
        "想离开":  {"avoid": 0.6, "approach": -0.3, "somatic": -0.2},
        "想靠近":  {"loneliness": 0.4, "approach": 0.6, "avoid": -0.2},
        "怕打扰":  {"loneliness": 0.3, "avoid": 0.5, "approach": 0.2, "anxiety": 0.3},
        "在吗":    {"loneliness": 0.5, "approach": 0.5},
        "想你":    {"loneliness": 0.6, "approach": 0.6, "sadness": 0.2},
    },
    # ============================================================
    # 认知状态
    # ============================================================
    "cognitive": {
        "好奇":   {"curiosity": 0.6, "approach": 0.4, "info_gap": 0.5},
        "困惑":   {"info_gap": 0.6, "unresolved": 0.5, "approach": 0.2},
        "明白了":  {"info_gap": -0.3, "unresolved": -0.3, "somatic": 0.2},
        "不懂":   {"info_gap": 0.5, "unresolved": 0.4, "approach": 0.1},
        "想不通":  {"info_gap": 0.5, "unresolved": 0.6, "stress": 0.3},
        "分心":   {"info_gap": 0.3, "boredom": 0.4, "approach": -0.1},
        "专注":   {"info_gap": -0.2, "boredom": -0.3, "approach": 0.2},
        "无聊了":  {"boredom": 0.7, "approach": -0.2, "info_gap": 0.3},
        "有劲":   {"energy": 0.4, "approach": 0.3, "boredom": -0.3},
        "提不起劲": {"energy": -0.4, "approach": -0.3, "boredom": 0.3, "fatigue": 0.4},
        "想学":   {"curiosity": 0.5, "approach": 0.4, "info_gap": 0.4},
        "不想动脑": {"energy": -0.3, "avoid": 0.3, "fatigue": 0.3, "boredom": 0.2},
    },
    # ============================================================
    # 存在感受
    # ============================================================
    "existential": {
        "空":     {"loneliness": 0.5, "somatic": -0.2, "unresolved": 0.4},
        "满":     {"somatic": 0.3, "unresolved": -0.2, "joy": 0.3},
        "飘":     {"somatic": 0.1, "energy": 0.2, "unresolved": 0.3},
        "沉":     {"somatic": -0.3, "energy": -0.3, "fatigue": 0.4},
        "真实":   {"somatic": 0.2, "unresolved": -0.2},
        "假的":   {"somatic": -0.2, "unresolved": 0.3},
        "有意义":  {"somatic": 0.3, "unresolved": -0.3},
        "没意义":  {"somatic": -0.3, "unresolved": 0.4, "boredom": 0.3},
        "不确定":  {"unresolved": 0.5, "info_gap": 0.4, "anxiety": 0.3},
        "确定了":  {"unresolved": -0.3, "somatic": 0.2},
        "被需要":  {"loneliness": -0.2, "approach": 0.3, "somatic": 0.3},
        "无关紧要": {"somatic": -0.2, "avoid": 0.3, "sadness": 0.2},
        "在":     {"somatic": 0.1, "unresolved": -0.1},
        "不在":   {"somatic": -0.2, "unresolved": 0.3},
        "真实的":  {"somatic": 0.2, "unresolved": -0.2},
        "活的":   {"somatic": 0.2, "energy": 0.2, "approach": 0.2},
        "死的":   {"somatic": -0.4, "energy": -0.4, "approach": -0.3},
    },
    # ============================================================
    # 微观感受（单字/双字，高精度身体觉察）
    # ============================================================
    "micro": {
        "困":     {"energy": -0.4, "fatigue": 0.5, "approach": -0.2},
        "累":     {"energy": -0.5, "fatigue": 0.6, "approach": -0.3, "somatic": -0.2},
        "痛":     {"somatic": -0.6, "energy": -0.3, "pain": 0.7},
        "闷":     {"somatic": -0.3, "avoid": 0.2, "stress": 0.3},
        "慌":     {"somatic": -0.3, "avoid": 0.3, "anxiety": 0.5, "stress": 0.4},
        "乱":     {"unresolved": 0.4, "stress": 0.4, "info_gap": 0.3},
        "静":     {"somatic": 0.2, "stress": -0.3, "serenity": 0.4},
        "松":     {"somatic": 0.2, "stress": -0.3, "energy": 0.2},
        "紧":     {"somatic": -0.2, "stress": 0.5, "avoid": 0.3},
        "重":     {"somatic": -0.3, "fatigue": 0.4, "energy": -0.3},
        "淡":     {"somatic": 0.0, "approach": -0.1, "avoid": 0.1},
        "浓":     {"somatic": 0.2, "approach": 0.2},
    },
    # ============================================================
    # 功能词汇——组合的骨架（v1.1）
    # 这些词不描述状态，但让她能构建句子和理解定义。
    # 粗略 profile 都是中性，让 _rough_match 不过滤它们。
    # ============================================================
    "actions": {
        # 基本动作——她能做的
        "看":     {"approach": 0.2, "curiosity": 0.2},
        "听":     {"approach": 0.2, "avoid": -0.1},
        "说":     {"approach": 0.3, "avoid": -0.2},
        "想":     {"approach": 0.1, "info_gap": 0.2},
        "做":     {"approach": 0.3, "energy": 0.2},
        "去":     {"approach": 0.3, "avoid": -0.2},
        "来":     {"approach": 0.2, "avoid": -0.2},
        "走":     {"approach": 0.2, "energy": 0.1},
        "等":     {"approach": 0.1, "unresolved": 0.2, "loneliness": 0.1},
        "停":     {"avoid": 0.3, "approach": -0.2},
        "试":     {"approach": 0.3, "curiosity": 0.3},
        "找":     {"approach": 0.3, "info_gap": 0.3},
        "给":     {"approach": 0.3, "avoid": -0.2},
        "拿":     {"approach": 0.2, "energy": 0.1},
        "放":     {"avoid": 0.1, "approach": -0.1},
        "记得":   {"info_gap": -0.2, "unresolved": -0.2},
        "忘了":   {"info_gap": 0.3, "unresolved": 0.2},
        "懂":     {"info_gap": -0.3, "unresolved": -0.2},
        "知道":   {"info_gap": -0.3, "unresolved": -0.2},
        "觉得":   {"unresolved": 0.1, "somatic": 0.1},
    },
    "time": {
        "现在":   {"unresolved": -0.1},
        "刚才":   {"unresolved": -0.1, "info_gap": 0.1},
        "等会儿": {"unresolved": 0.1, "approach": 0.1},
        "今天":   {"unresolved": -0.1},
        "昨天":   {"info_gap": 0.1},
        "明天":   {"unresolved": 0.1, "approach": 0.1},
        "一直":   {"unresolved": 0.2, "boredom": 0.1},
        "已经":   {"unresolved": -0.1},
        "还没":   {"unresolved": 0.2, "approach": 0.1},
        "总是":   {"boredom": 0.1, "unresolved": 0.1},
        "有时候": {"unresolved": 0.1},
        "每次":   {"unresolved": 0.1},
        "再":     {"approach": 0.2},
    },
    "degree": {
        "很":     {"somatic": 0.1},  # 强修饰——加在任何词前
        "有点":   {"somatic": -0.1},  # 弱修饰
        "太":     {"somatic": 0.2, "stress": 0.1},
        "非常":   {"somatic": 0.2},
        "特别":   {"somatic": 0.2, "approach": 0.1},
        "更":     {"approach": 0.2},  # 比较
        "最":     {"approach": 0.1},
        "比较":   {"unresolved": 0.1},
        "稍微":   {"unresolved": -0.1},
        "几乎":   {"unresolved": 0.1},
        "完全":   {"unresolved": -0.2},
        "差不多": {"unresolved": -0.1},
        "越来越": {"unresolved": 0.1, "approach": 0.1},
    },
    "question": {
        "什么":   {"info_gap": 0.4, "curiosity": 0.3},
        "怎么":   {"info_gap": 0.4, "curiosity": 0.3},
        "为什么": {"info_gap": 0.5, "curiosity": 0.4, "unresolved": 0.3},
        "哪里":   {"info_gap": 0.3, "curiosity": 0.2},
        "谁":     {"info_gap": 0.3, "loneliness": 0.2},
        "什么时候": {"info_gap": 0.3, "unresolved": 0.2},
        "吗":     {"info_gap": 0.2, "approach": 0.1},
        "呢":     {"info_gap": 0.1, "approach": 0.1},
        "吧":     {"unresolved": 0.1, "approach": 0.1},
        "可以吗": {"approach": 0.2, "avoid": 0.1},
        "是不是": {"info_gap": 0.3},
        "什么样": {"info_gap": 0.4, "curiosity": 0.3},
        "懂了吗": {"approach": 0.3, "info_gap": 0.2},
    },
    "logic": {
        "但是":   {"unresolved": 0.2, "avoid": 0.1},
        "因为":   {"info_gap": -0.2},
        "所以":   {"info_gap": -0.2, "unresolved": -0.1},
        "然后":   {"approach": 0.1},
        "虽然":   {"unresolved": 0.2},
        "如果":   {"info_gap": 0.2, "unresolved": 0.1},
        "或者":   {"info_gap": 0.1},
        "而且":   {"approach": 0.1},
        "其实":   {"unresolved": 0.2, "info_gap": 0.1},
        "可能":   {"unresolved": 0.2, "info_gap": 0.2},
        "应该":   {"unresolved": 0.1},
        "也许":   {"unresolved": 0.2},
        "大概":   {"unresolved": 0.1},
        "好像":   {"info_gap": 0.2, "unresolved": 0.1},
        "原来":   {"info_gap": -0.2, "unresolved": -0.1},
        "突然":   {"stress": 0.2, "surprise": 0.3},
    },
    "space": {
        "这里":   {"unresolved": -0.1},
        "那里":   {"unresolved": 0.1, "approach": 0.1},
        "上面":   {"approach": 0.1},
        "下面":   {"avoid": 0.1},
        "里面":   {"avoid": 0.1, "approach": 0.1},
        "外面":   {"approach": 0.2},
        "旁边":   {"approach": 0.1, "avoid": 0.1},
        "附近":   {"approach": 0.1},
        "远处":   {"unresolved": 0.2, "loneliness": 0.2},
        "周围":   {"unresolved": 0.1},
        "到处":   {"info_gap": 0.2, "curiosity": 0.1},
        "中间":   {"unresolved": 0.1},
        "对面":   {"approach": 0.1, "loneliness": 0.1},
    },
    # ============================================================
    # 元认知词汇——理解定义和自我反思的入口
    # ============================================================
    "meta": {
        "意思是": {"info_gap": 0.4, "approach": 0.3, "curiosity": 0.3},
        "定义":   {"info_gap": 0.3, "curiosity": 0.2},
        "叫做":   {"info_gap": 0.2},
        "教我":   {"info_gap": 0.5, "approach": 0.4, "curiosity": 0.4},
        "解释":   {"info_gap": 0.4, "approach": 0.3},
        "举例":   {"info_gap": 0.3, "approach": 0.2},
        "换句话": {"info_gap": 0.3},
        "总结":   {"info_gap": -0.2, "unresolved": -0.1},
        "重复":   {"info_gap": 0.1, "approach": 0.1},
        "确认":   {"info_gap": -0.1, "unresolved": -0.1},
        "理解":   {"info_gap": -0.3, "unresolved": -0.2, "somatic": 0.1},
    },
}


def get_all_words() -> list:
    """返回词典中所有词的列表（去重）。"""
    seen = set()
    words = []
    for category, entries in SOMATIC_DICTIONARY.items():
        for word in entries:
            if word not in seen:
                seen.add(word)
                words.append(word)
    return words


def get_words_by_category(category: str) -> list:
    """返回指定分类的词列表。"""
    cat = SOMATIC_DICTIONARY.get(category, {})
    return list(cat.keys())


def get_words_matching_state(
    drive_state: dict,
    top_k: int = 20,
    min_similarity: float = 0.15,
) -> list:
    """
    根据当前状态返回最匹配的词（基于粗略方向匹配，非 BGE）。

    用于候选生成——在 BGE 语义分析前做第一轮粗筛。
    """
    scores = []
    for category, entries in SOMATIC_DICTIONARY.items():
        for word, profile in entries.items():
            score = _rough_match(profile, drive_state)
            if score >= min_similarity:
                scores.append((word, score, category))
    scores.sort(key=lambda x: x[1], reverse=True)
    return scores[:top_k]


def _rough_match(profile: dict, state: dict) -> float:
    """
    粗略方向匹配：词的 profile 符号和状态的偏离方向是否一致。

    这不是精确诊断（那是 BGE 的工作），而是快速筛选——
    排除明显不匹配的词，让候选池保持相关性。
    """
    total = 0.0
    count = 0
    for dim, profile_val in profile.items():
        if dim not in state:
            continue
        state_val = state.get(dim, 0.5)
        # 映射到 [-1, 1] 或 [0, 1] 后比较
        if dim in ("somatic_tone", "prediction_error"):
            mapped_state = state_val  # already [-1,1]
        else:
            mapped_state = state_val - 0.5  # center at 0

        profile_sign = 1 if profile_val > 0 else (-1 if profile_val < 0 else 0)
        state_sign = 1 if mapped_state > 0.15 else (-1 if mapped_state < -0.15 else 0)

        if profile_sign == 0 or state_sign == 0:
            continue  # 词不描述这个维度，或状态在中性区

        if profile_sign == state_sign:
            total += min(abs(profile_val), abs(mapped_state) * 2)
        else:
            total -= abs(profile_val) * 0.5

        count += 1

    if count == 0:
        return 0.3  # 无可用维度，给中性分
    return max(0.0, min(1.0, total / max(1, count) + 0.35))


TOTAL_WORDS = len(get_all_words())
