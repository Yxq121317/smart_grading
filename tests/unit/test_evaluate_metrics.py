from scripts.evaluate import compute_metrics


def test_compute_metrics():
    cases = [
        {"expected_score": 4, "expected_error_type": "incomplete_summary"},
        {"expected_score": 6, "expected_error_type": None},
    ]
    predictions = [
        {
            "score": 5,
            "error_type": "incomplete_summary",
            "json_valid": True,
            "confidence": 0.8,
        },
        {
            "score": 6,
            "error_type": None,
            "json_valid": True,
            "confidence": 0.9,
        },
    ]
    metrics = compute_metrics(cases, predictions)
    assert metrics["mae"] == 0.5
    assert metrics["exact_match_rate"] == 0.5
    assert metrics["json_valid_rate"] == 1.0
    assert metrics["error_accuracy"] == 1.0
