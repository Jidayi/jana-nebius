"""The hardware-class benchmark repeated on a device-lab laptop (PLT-08 acceptance).

`run` probes the laptop exactly as the app does (`agent_core.router.probe.probe_machine`), starts llama-server on the
smallest installed model, and runs the app's own benchmark (`run_benchmark`, through the shipped provider) the
configured number of times, recording the class each run picks. The record goes in the laptop's device-lab file as
`class_runs`, with the probe; `plt08_hardware_class_choice_reference_laptops` checks that every run picked the
laptop's class. Run it with networking disabled: the record says so only when the operator states it.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Any

from .memfit import serving


async def _runs(url: str, key: str, model: str, runs: int) -> list[dict[str, Any]]:
    from agent_core.config import Settings
    from agent_core.providers.llama import LlamaServerProvider
    from agent_core.router.probe import choose_class, probe_machine, run_benchmark

    settings = Settings()
    probe = probe_machine(Path(tempfile.gettempdir()))
    provider = LlamaServerProvider(url, key)
    out = []
    try:
        for _ in range(runs):
            bench = await run_benchmark(provider, model, settings)
            choice = choose_class(probe, bench, settings)
            out.append({"hardware_class": choice.hardware_class,
                        "generation_tokens_s": round(bench.generation_tokens_s, 2),
                        "prompt_tokens_s": round(bench.prompt_tokens_s, 2),
                        "seconds": round(bench.seconds, 2)})  # fmt: skip
    finally:
        await provider.close()
    return out


def run(server: Path, gguf: Path, runs: int | None = None, network: str = "unknown") -> dict[str, Any]:
    from agent_core.config import Settings
    from agent_core.router.probe import probe_machine

    count = runs or Settings().benchmark_reference_runs
    probe = probe_machine(Path(tempfile.gettempdir()))
    context = Settings().context_cap_low
    with serving(server, gguf, context) as served:
        class_runs = asyncio.run(_runs(served.url, served.key, gguf.stem, count))
    return {"probe": probe.to_json(), "model": gguf.stem, "network": network, "class_runs": class_runs}
