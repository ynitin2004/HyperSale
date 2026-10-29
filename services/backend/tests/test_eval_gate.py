"""D38: the eval gate fails on unverified quotes, kappa/MAE regressions and IE drift."""
import pytest

from evals import harness

GATE = {"qwk_margin": 0.15, "mae_margin": 0.4, "ie_rate_band": 0.2, "max_errors": 1}
ITEMS = [f"i{n}" for n in range(10)]
CRITS = ["opening", "discovery", "value"]


def _labels(shift: int = 0) -> dict:
    return {i: {c: str(min(5, max(1, 1 + (n + k) % 5 + shift))) for k, c in enumerate(CRITS)}
            for n, i in enumerate(ITEMS)}


def _run(outcomes: dict, **extra) -> dict:
    return {"items": [{"item": i, "source": "sim", "outcomes": o, "fabricated": 0, "misattributed": 0,
                       "latency_ms": 1000, "cost_usd": 0.01, **extra} for i, o in outcomes.items()]}


@pytest.fixture(autouse=True)
def raters(monkeypatch: pytest.MonkeyPatch) -> None:
    docs = [{"rater": "a", "kind": "human", "labels": _labels()},
            {"rater": "b", "kind": "human", "labels": _labels()}]
    monkeypatch.setattr(harness, "load_raters", lambda: (docs, "human"))


def test_a_model_that_matches_the_raters_passes() -> None:
    report = harness.evaluate(_run(_labels()), GATE)
    assert report["passed"], report["failures"]
    assert report["ceiling_kind"] == "human"


def test_a_degraded_model_that_scores_everything_five_fails() -> None:
    all_five = {i: {c: "5" for c in CRITS} for i in ITEMS}
    report = harness.evaluate(_run(all_five), GATE)
    assert not report["passed"]
    assert any("kappa" in f for f in report["failures"])


def test_any_surviving_fabricated_quote_fails() -> None:
    report = harness.evaluate(_run(_labels(), fabricated=1), GATE)
    assert any("unverified quotes" in f for f in report["failures"])


def test_insufficient_evidence_drift_fails() -> None:
    lazy = {i: {c: "insufficient_evidence" for c in CRITS} for i in ITEMS[:6]} | {
        i: o for i, o in _labels().items() if i in ITEMS[6:]}
    report = harness.evaluate(_run(lazy), GATE)
    assert any("insufficient-evidence" in f for f in report["failures"])


def test_a_regression_against_the_baseline_fails_even_above_the_ceiling() -> None:
    """D38: a lenient prompt that stays near the ceiling still fails if it is worse than the
    accepted baseline on the same items (the live 'degraded' run did exactly this)."""
    baseline = _run(_labels())
    nudged = {i: {c: str(min(5, int(v) + 1)) for c, v in o.items()} for i, o in _labels().items()}
    report = harness.evaluate(_run(nudged), {**GATE, "qwk_margin": 1.0, "mae_margin": 2.0,
                                             "baseline_qwk_drop": 0.05, "baseline_mae_rise": 0.1},
                              baseline)
    assert any("regressed" in f for f in report["failures"]), report["failures"]
    same = harness.evaluate(_run(_labels()), {**GATE, "baseline_qwk_drop": 0.05, "baseline_mae_rise": 0.1},
                            baseline)
    assert same["passed"], same["failures"]
