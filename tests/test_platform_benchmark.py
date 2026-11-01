from scripts.platform_benchmark import fixture, main, measure


def test_benchmark_fixture_is_deterministic_and_budgeted(tmp_path):
    assert fixture(2).count("Section") == 2
    result = measure(100, 3)
    assert result["fixture_sections"] == 100 and result["p95_ms"] >= result["median_ms"]
    output = tmp_path / "benchmark.json"
    assert main(["--sections", "10", "--repeats", "2", "--p95-budget-ms", "2000", "--output", str(output)]) == 0
    assert "p95_ms" in output.read_text()
