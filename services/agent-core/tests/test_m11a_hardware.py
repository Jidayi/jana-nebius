"""M11.a: the hardware probe, the benchmark and the hardware class (MDL-16, PLT-08, PLT-29). Probe fixtures are
synthetic records of the machines EVL-14 describes; the device lab's own probe records replace them as each reference
laptop arrives."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from agent_core.config import Settings
from agent_core.router.probe import (
    GB,
    Benchmark,
    Probe,
    choose_class,
    cpu_year,
    minimum_shortfalls,
    probe_machine,
    run_benchmark,
)

FIXTURES = Path(__file__).parent / "fixtures" / "probe"
SETTINGS = Settings()


def _fixture(name: str) -> tuple[Probe, Benchmark | None, str]:
    data = json.loads((FIXTURES / f"{name}.json").read_text())
    assert data["synthetic"] is True
    bench = Benchmark(**data["benchmark"]) if data["benchmark"] else None
    return Probe.from_json(data["probe"]), bench, data["expected"]


def mdl16_reference_classes() -> None:
    for name in ("low", "mid", "high", "below_minimum"):
        probe, bench, expected = _fixture(name)
        chosen = choose_class(probe, bench, SETTINGS)
        assert chosen.hardware_class == expected, (name, chosen)
        # The same machine before any model is installed: predicted from the hardware, marked provisional.
        predicted = choose_class(probe, None, SETTINGS)
        assert predicted.provisional and predicted.hardware_class == expected, (name, predicted)
    # Below the minimum laptop: the figure that is short is named, for the notice (PLT-29).
    probe, _, _ = _fixture("below_minimum")
    [short] = choose_class(probe, None, SETTINGS).shortfalls
    assert (short.check, short.have, short.need, short.unit) == ("ram", 4, 8.0, "GB")


def test_class_rules_follow_plt08a() -> None:
    low, _, _ = _fixture("low")
    high, _, _ = _fixture("high")

    def speed(tokens_s: float) -> Benchmark:
        return Benchmark("m", 50.0, tokens_s, 5.0)

    # Too slow for the low model is content-only, with the speed named as the shortfall.
    slow = choose_class(low, speed(4.0), SETTINGS)
    assert slow.hardware_class == "content_only" and slow.shortfalls[0].check == "speed"
    # Fast enough for high, but no memory for the high model: mid needs 14 GB, so an 8 GB laptop stays low.
    assert choose_class(low, speed(40.0), SETTINGS).hardware_class == "low"
    # Apple silicon with the speed for high is high; with mid speed it is mid.
    assert choose_class(high, speed(12.0), SETTINGS).hardware_class == "mid"
    # A 32-bit system, a CPU without SSE4.2, an old CPU and a full disk each fail the minimum laptop.
    data = json.loads((FIXTURES / "low.json").read_text())["probe"]
    for change, check in (({"arch": "x86"}, "cpu"), ({"cpu_features": ["popcnt"]}, "cpu"),
                          ({"cpu_model": "Intel(R) Core(TM) i5-6200U CPU"}, "cpu"),
                          ({"free_disk_bytes": 4 * GB}, "disk")):  # fmt: skip
        assert [s.check for s in minimum_shortfalls(Probe.from_json({**data, **change}), SETTINGS)] == [check]


def test_cpu_year_from_model_names() -> None:
    assert cpu_year("Intel(R) Core(TM) i5-8250U CPU @ 1.60GHz") == 2018
    assert cpu_year("12th Gen Intel(R) Core(TM) i7-1255U") == 2022
    assert cpu_year("AMD Ryzen 5 3500U with Radeon Vega Mobile Gfx") == 2019
    assert cpu_year("Apple M1") == 2020
    assert cpu_year("Intel(R) Celeron(R) N4020 CPU @ 1.10GHz") is None  # unknown: the benchmark decides


def test_probe_reads_this_machine(tmp_path: Path) -> None:
    probe = probe_machine(tmp_path)
    assert probe.ram_bytes > GB and probe.cpu_cores >= 1 and probe.free_disk_bytes > 0
    assert probe.arch in ("x86_64", "arm64")
    assert Probe.from_json(json.loads(json.dumps(probe.to_json()))) == probe


def test_benchmark_reads_runtime_timings() -> None:
    class Runtime:
        async def benchmark(self, model: str, prompt: str, generate: int, timeout_s: float) -> dict[str, float]:
            assert generate > 0 and timeout_s == SETTINGS.benchmark_max_s and len(prompt) > 200
            return {"prompt_tokens_s": 80.0, "generation_tokens_s": 11.0, "seconds": 6.5}

    bench = asyncio.run(run_benchmark(Runtime(), "qwen3-vl-8b", SETTINGS))
    assert bench == Benchmark("qwen3-vl-8b", 80.0, 11.0, 6.5)
