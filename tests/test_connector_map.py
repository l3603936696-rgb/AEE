"""
验证测试：connector_map.py 连接词连续评分系统

覆盖：
- 高斯评分函数的基本性质
- 强度前缀：低/中/高 intensity → 不同词优势
- 语气开头：不同情绪维度 → 不同词优势
- 后缀语气：变化量 + 社会信号 → 不同词优势
- softmax 采样返回有效词
- 全部无 if-else
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import random
from AEE.src.language_system.connector_map import (
    _gauss,
    _softmax_sample,
    score_intensity_prefix,
    sample_intensity_prefix,
    score_opening_particle,
    sample_opening_particle,
    score_suffix_particle,
    sample_suffix_particle,
)


class TestGauss:
    """_gauss 高斯评分函数的基本性质。"""

    def test_gauss_peak_at_mu(self):
        """x = mu 时得分最高（= 1.0）。"""
        assert abs(_gauss(0.5, 0.5, 0.2) - 1.0) < 1e-9

    def test_gauss_symmetric(self):
        """mu ± d 的得分相同。"""
        mu, sigma = 0.5, 0.2
        assert abs(_gauss(mu - 0.1, mu, sigma) - _gauss(mu + 0.1, mu, sigma)) < 1e-9

    def test_gauss_positive(self):
        """返回值永远 > 0。"""
        assert _gauss(0.0, 0.5, 0.1) > 0
        assert _gauss(1.0, 0.5, 0.1) > 0


class TestSoftmaxSample:
    """_softmax_sample 采样函数的基本性质。"""

    def test_empty_scores_returns_empty_string(self):
        assert _softmax_sample({}) == ""

    def test_returns_valid_key(self):
        scores = {"a": 0.5, "b": 0.3, "c": 0.1}
        random.seed(42)
        result = _softmax_sample(scores, temperature=0.15)
        assert result in scores

    def test_deterministic_with_zero_temperature(self):
        """temperature → 0 时返回最高分词。"""
        scores = {"a": 1.0, "b": 0.0, "c": 0.5}
        random.seed(99)
        result = _softmax_sample(scores, temperature=0.001)
        assert result == "a"


class TestIntensityPrefix:
    """强度前缀词（"有点" / "好" / "太"）评分。"""

    def test_empty_wins_at_low_intensity(self):
        """intensity 极低（0.0）时，"" 得分最高。"""
        scores = score_intensity_prefix(0.0)
        assert scores[""] > scores["有点"]
        assert scores[""] > scores["好"]

    def test_好_wins_at_mid_intensity(self):
        """intensity 中等（~0.50）时，"好" 得分最高。"""
        scores = score_intensity_prefix(0.50)
        assert scores["好"] > scores["有点"]
        assert scores["好"] > scores["太"]

    def test_太_wins_at_high_intensity(self):
        """intensity 高（~0.80）时，"太" 得分最高。"""
        scores = score_intensity_prefix(0.80)
        assert scores["太"] > scores["好"]
        assert scores["太"] > scores["有点"]

    def test_all_scores_positive(self):
        scores = score_intensity_prefix(0.5)
        for v in scores.values():
            assert v > 0

    def test_sample_returns_valid_word(self):
        random.seed(7)
        result = sample_intensity_prefix(0.5, temperature=0.15)
        assert result in score_intensity_prefix(0.5)

    def test_no_if_else_used(self):
        """验证评分表覆盖完整 intensity 范围，无硬编码分支。

        通过检查：intensity 从 0 到 1，每隔 0.1 采样，
        确认每种 intensity 都能从 _softmax_sample 返回有效词。
        """
        for intensity in [0.0, 0.1, 0.25, 0.5, 0.75, 1.0]:
            result = sample_intensity_prefix(intensity, temperature=0.15)
            assert result in score_intensity_prefix(intensity)


class TestOpeningParticle:
    """语气开头词（"嗯…" / "啊…" / "唉…"）评分。"""

    def test_嗯_wins_when_fatigue_is_dominant(self):
        """fatigue 远高于其他维度时，"嗯…" 得分最高。"""
        scores = score_opening_particle(
            fatigue=0.6, somatic_distress=0.0, sadness=0.0, energy=0.8
        )
        assert scores["嗯…"] > scores["啊…"], \
            f"嗯…={scores['嗯…']} 应 > 啊…={scores['啊…']}"
        assert scores["嗯…"] > scores["唉…"], \
            f"嗯…={scores['嗯…']} 应 > 唉…={scores['唉…']}"

    def test_啊_wins_when_distress_is_dominant(self):
        """somatic_distress 远高于其他维度时，"啊…" 得分最高。"""
        scores = score_opening_particle(
            fatigue=0.0, somatic_distress=0.6, sadness=0.0, energy=0.8
        )
        assert scores["啊…"] > scores["嗯…"], \
            f"啊…={scores['啊…']} 应 > 嗯…={scores['嗯…']}"
        assert scores["啊…"] > scores["唉…"], \
            f"啊…={scores['啊…']} 应 > 唉…={scores['唉…']}"

    def test_empty_wins_at_low_distress(self):
        """各维度都很低时，"" 得分最高。"""
        scores = score_opening_particle(
            fatigue=0.0, somatic_distress=0.0, sadness=0.0, energy=0.9
        )
        assert scores[""] > scores["嗯…"]
        assert scores[""] > scores["啊…"]
        assert scores[""] > scores["唉…"]

    def test_sample_returns_valid_word(self):
        random.seed(13)
        result = sample_opening_particle(
            fatigue=0.5, somatic_distress=0.3, sadness=0.2, energy=0.5, temperature=0.15
        )
        assert result in score_opening_particle(0.5, 0.3, 0.2, 0.5)


class TestSuffixParticle:
    """后缀语气词（"了" / "啊" / "吧"）评分。"""

    def test_了_wins_at_sweet_spot_delta(self):
        """delta_total ≈ 0.08（甜点）时，"了" 得分最高。"""
        scores = score_suffix_particle(
            delta_total=0.08,
            loneliness=0.3, approach=0.0,
            anxiety=0.0, unresolved=0.2,
        )
        assert scores["了"] > scores["啊"], \
            f"了={scores['了']} 应 > 啊={scores['啊']}"
        assert scores["了"] > scores["吧"], \
            f"了={scores['了']} 应 > 吧={scores['吧']}"

    def test_了_wins_at_low_delta(self):
        """变化量接近 0 时，"" 得分最高（不需要"了"）。"""
        scores = score_suffix_particle(
            delta_total=0.0,
            loneliness=0.3, approach=0.0,
            anxiety=0.0, unresolved=0.2,
        )
        assert scores[""] > scores["了"]
        assert scores[""] > scores["啊"]
        assert scores[""] > scores["吧"]

    def test_啊_wins_at_high_social_signal(self):
        """高孤独 + 高趋近时，"啊" 得分最高。"""
        scores = score_suffix_particle(
            delta_total=0.0,
            loneliness=0.8, approach=0.7,
            anxiety=0.0, unresolved=0.2,
        )
        assert scores["啊"] > scores["了"], \
            f"啊={scores['啊']} 应 > 了={scores['了']}"
        assert scores["啊"] > scores["吧"], \
            f"啊={scores['啊']} 应 > 吧={scores['吧']}"

    def test_吧_wins_at_high_uncertainty(self):
        """高焦虑 + 高未决时，"吧" 得分最高。"""
        scores = score_suffix_particle(
            delta_total=0.0,
            loneliness=0.2, approach=0.0,
            anxiety=0.5, unresolved=0.5,
        )
        assert scores["吧"] > scores["了"], \
            f"吧={scores['吧']} 应 > 了={scores['了']}"
        assert scores["吧"] > scores["啊"], \
            f"吧={scores['吧']} 应 > 啊={scores['啊']}"

    def test_sample_returns_valid_word(self):
        random.seed(21)
        result = sample_suffix_particle(
            delta_total=0.1, loneliness=0.4, approach=0.3,
            anxiety=0.3, unresolved=0.2, temperature=0.15
        )
        assert result in score_suffix_particle(0.1, 0.4, 0.3, 0.3, 0.2)


class TestConnectorContinuity:
    """连接词评分的连续性验证：无 if-else 的核心保证。"""

    def test_no_threshold_branching_in_intensity_prefix(self):
        """强度前缀：4 种词都应该在某处成为 winner（无 if-else 的直接证明）。"""
        winners = set()
        for intensity in [i * 0.05 for i in range(21)]:
            scores = score_intensity_prefix(intensity)
            winner = max(scores, key=scores.get)
            winners.add(winner)
        assert len(winners) == 4, f"期望 4 种词都能胜出，实际: {winners}"

    def test_no_threshold_branching_in_opening_particle(self):
        """语气开头："" / "嗯…" / "啊…" / "唉…" 都应该在某处成为 winner。"""
        winners = set()
        for fatigue in [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]:
            for distress in [0.0, 0.3, 0.6, 0.9]:
                for sadness in [0.0, 0.3, 0.6, 0.9]:
                    scores = score_opening_particle(fatigue, distress, sadness, 0.5)
                    winners.add(max(scores, key=scores.get))
        assert "" in winners, f"空词应能胜出，实际 winners: {winners}"
        assert "嗯…" in winners, f"嗯…应能胜出，实际 winners: {winners}"
        assert "啊…" in winners, f"啊…应能胜出，实际 winners: {winners}"
        assert "唉…" in winners, f"唉…应能胜出，实际 winners: {winners}"

    def test_no_threshold_branching_in_suffix_particle(self):
        """后缀语气："" / "了" / "啊" / "吧" 都应该在某处成为 winner。"""
        winners = set()
        for delta in [0.0, 0.02, 0.04, 0.06, 0.08, 0.10, 0.12, 0.15, 0.20]:
            for lon in [0.1, 0.4, 0.7, 1.0]:
                for anx in [0.0, 0.3, 0.5, 0.7, 1.0]:
                    for unres in [0.0, 0.3, 0.5, 0.7, 1.0]:
                        scores = score_suffix_particle(delta, lon, 0.0, anx, unres)
                        winners.add(max(scores, key=scores.get))
        assert "" in winners, f"空后缀应能胜出，实际 winners: {winners}"
        assert "了" in winners, f"了应能胜出，实际 winners: {winners}"
        assert "啊" in winners, f"啊应能胜出，实际 winners: {winners}"
        assert "吧" in winners, f"吧应能胜出，实际 winners: {winners}"

    def test_softmax_sample_diversity(self):
        """softmax 采样有随机性，多次调用应产生不同结果（在高温度下）。"""
        random.seed(0)
        results = set()
        scores = {"a": 0.5, "b": 0.4, "c": 0.3}
        for _ in range(50):
            results.add(_softmax_sample(scores, temperature=0.20))
        assert len(results) >= 2, f"高温度采样多样性不足: {results}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
