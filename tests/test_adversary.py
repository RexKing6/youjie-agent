from delivery_guard.adversary import evaluate_suite


def test_full_adversarial_suite_passes():
    report = evaluate_suite("data/demo_factory.json", "data/adversarial_suite.json")
    assert report["total_cases"] == 15
    assert report["failed_cases"] == 0
    assert report["invariant_violations"] == []
