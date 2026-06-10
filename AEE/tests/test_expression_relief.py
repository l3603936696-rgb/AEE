from AEE.src.language_system.expression_relief import compute_relief


def _state(**overrides):
    state = {
        "boredom": 0.97,
        "unresolved": 0.35,
        "info_gap": 0.65,
        "avoid": 0.5,
        "somatic_tone": 0.5,
        "loneliness": 0.8,
    }
    state.update(overrides)
    return state


def _diag(expression, novelty=1.0, state=None):
    return compute_relief(expression, state or _state(), novelty)["diagnostics"]


def test_causal_structure_beats_plain_naming():
    plain = _diag("有点无聊了")
    causal = _diag("无聊了，因为没有人来")

    assert causal["structure_score"] > plain["structure_score"]
    assert abs(causal["boredom_delta"]) > abs(plain["boredom_delta"])
    assert abs(causal["unresolved_delta"]) > abs(plain["unresolved_delta"])


def test_repetition_discount_reduces_relief():
    fresh = _diag("无聊了，因为没有人来", novelty=1.0)
    repeated = _diag("无聊了，因为没有人来", novelty=0.2)

    assert repeated["novelty"] == 0.2
    assert repeated["relief"] < fresh["relief"]
    assert abs(repeated["boredom_delta"]) < abs(fresh["boredom_delta"])


def test_pure_connectors_do_not_create_large_relief():
    connectors = _diag("因为所以但是")
    causal = _diag("无聊了，因为没有人来")

    assert connectors["accuracy"] <= 0.05
    assert connectors["relief"] < causal["relief"] * 0.1
    assert abs(connectors["unresolved_delta"]) < abs(causal["unresolved_delta"]) * 0.1


def test_compute_relief_does_not_touch_loneliness():
    state = _state(loneliness=0.9)
    result = compute_relief("无聊了，因为没有人来", state, 1.0)

    assert "loneliness_delta" not in result
    assert "loneliness_delta" not in result["diagnostics"]
    assert state["loneliness"] == 0.9
