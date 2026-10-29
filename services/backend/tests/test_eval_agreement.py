"""D15/D38: the agreement maths the eval gate trusts."""
from evals.agreement import IE, ceiling, compare, consensus, mae, quadratic_weighted_kappa


def test_qwk_is_one_for_identical_and_low_for_reversed_scores() -> None:
    same = [(1, 1), (2, 2), (3, 3), (4, 4), (5, 5)]
    assert quadratic_weighted_kappa(same) == 1.0
    reversed_ = [(1, 5), (2, 4), (3, 3), (4, 2), (5, 1)]
    assert quadratic_weighted_kappa(reversed_) < 0
    assert quadratic_weighted_kappa([]) is None


def test_qwk_penalises_far_disagreement_more_than_near() -> None:
    base = [(1, 1), (2, 2), (3, 3), (4, 4), (5, 5)] * 2
    near = base + [(3, 4)] * 3
    far = base + [(1, 5)] * 3
    assert quadratic_weighted_kappa(near) > quadratic_weighted_kappa(far)


def test_insufficient_evidence_is_excluded_from_kappa_but_reported() -> None:
    a = {("i1", "opening"): "4", ("i1", "discovery"): IE, ("i2", "opening"): "2"}
    b = {("i1", "opening"): "4", ("i1", "discovery"): "3", ("i2", "opening"): "3"}
    stats = compare(a, b)
    assert stats["n"] == 2 and stats["mae"] == 0.5
    assert abs(stats["ie_agreement"] - 2 / 3) < 1e-9
    assert mae([]) is None


def test_consensus_majority_ie_else_median() -> None:
    k = ("i1", "value")
    assert consensus([{k: IE}, {k: IE}, {k: "4"}])[k] == IE
    assert consensus([{k: "2"}, {k: "4"}, {k: IE}])[k] == "3"
    assert consensus([{k: "2"}, {k: "5"}])[k] == "4"  # ties round up


def test_ceiling_needs_two_raters() -> None:
    k = ("i1", "value")
    assert ceiling([{k: "3"}])["qwk"] is None
    assert ceiling([{k: "3"}, {k: "3"}, {k: "4"}])["pairs"] == 3
