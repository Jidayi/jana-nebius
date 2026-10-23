"""Contract fakes for building against before the real components exist (plan M1.a; section 7.1).

- `ScriptedEventSource`: replays a recorded event stream as SSE, every envelope validated against the events
  contract (what the client builds against until the local API exists, M5).
- `FakeToolWorker`: answers worker JSON-RPC from a recorded transcript, requests and responses validated against
  the worker protocol (what the engine's tool registry builds against until the worker exists, M2).
- `ScriptedModelProvider`: returns scripted model replies, structured replies validated against their contract
  (what the engine builds against until the router and runtime exist, M3).
- `FakeLlamaServer`: a loopback stand-in for llama-server that replays recorded replies and streams, errors,
  stalls and dropped connections (the adapter's tests and cassette replay, M3).

All scripts are synthetic and live in evals/contracts/scripts/.
"""

from .events import ScriptedEventSource
from .llama_server import FakeLlamaServer
from .provider import ScriptedModelProvider
from .worker import FakeToolWorker

__all__ = ["FakeLlamaServer", "FakeToolWorker", "ScriptedEventSource", "ScriptedModelProvider"]
