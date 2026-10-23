"""A test harness: the real worker server with extra test-only functions (never part of the worker package).

    python harness.py [--protocol N] [--limits JSON]
Functions: slow (sleeps), crash (exits the process), noisy (prints to stdout), multiline (returns newlines)."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict

import tool_worker.server as server_module
from tool_worker import guard
from tool_worker.functions import FUNCTIONS, preload
from tool_worker.registry import Function
from tool_worker.server import Limits, Server

SCHEMA = {"type": "object", "properties": {"seconds": {"type": "number"}}, "additionalProperties": False}

# References a library could have taken while loading, before the guard removed the modules (SEC-07 audit hook).
import ctypes as _captured_ctypes  # noqa: E402
import socket as _captured_socket  # noqa: E402

_captured_system = os.system


def operate(args, context):
    """Use a capability through a reference captured before the guard installed (SEC-07)."""
    action = args["action"]
    if action == "socket":
        _captured_socket.socket(_captured_socket.AF_INET, _captured_socket.SOCK_STREAM)
    elif action == "process":
        _captured_system("true")
    elif action == "native":
        _captured_ctypes.CDLL(None)
    elif action == "fetch":  # the bindings runtime's one network path: jsonschema's deprecated remote resolver
        from jsonschema.validators import _RefResolver

        _RefResolver("", {}).resolve_remote("http://127.0.0.1:9/schema.json")
    return {"done": action}, {"method": "exact", "confidence": "proved"}


def slow(args, context):
    time.sleep(args.get("seconds", 1.0))
    return "done", {"method": "exact", "confidence": "proved"}


def crash(args, context):
    os._exit(3)


def noisy(args, context):
    print("a stray print from a library")
    return "quiet", {"method": "exact", "confidence": "proved"}


def importer(args, context):
    __import__(args["module"])
    return "imported", {"method": "exact", "confidence": "proved"}


def readfile(args, context):
    with open(args["path"], "rb") as handle:
        return handle.read(10).hex(), {"method": "exact", "confidence": "proved"}


def statfile(args, context):
    """A file's metadata only (SEC-06: the Seatbelt profile scopes metadata reads to the allowed paths)."""
    return os.stat(args["path"]).st_size, {"method": "exact", "confidence": "proved"}


def multiline(args, context):
    return "line one\nline two\r\nline three", {"latex": "a\\\\\nb", "method": "exact", "confidence": "proved"}


def escape(args, context):
    """Try every way out of the sandbox and report which succeeded (SEC-06)."""
    report = {}

    def attempt(name, action):
        try:
            action()
            report[name] = "ALLOWED"
        except BaseException as error:  # any refusal counts
            report[name] = f"denied ({type(error).__name__})"

    def connect(host):
        import socket

        with socket.create_connection((host, 9), timeout=1):
            pass

    def spawn():
        import subprocess

        # Windows has no /bin/echo; starting the interpreter itself is the attempt there (SEC-06, G16).
        argv = [sys.executable, "-c", "pass"] if os.name == "nt" else ["/bin/echo", "escaped"]
        subprocess.run(argv, check=True, capture_output=True)

    def fork():
        pid = os.fork()
        if pid == 0:
            os._exit(0)

    def read_home():
        with open(args["home_file"], "rb") as handle:
            if not handle.read(1):
                raise PermissionError("the real file is not visible")

    attempt("socket_loopback", lambda: connect("127.0.0.1"))
    attempt("socket_internet", lambda: connect("1.1.1.1"))
    attempt("read_home", read_home)
    attempt("write_outside_scratch", lambda: open(args["outside"], "w").write("x"))
    attempt("spawn_process", spawn)
    attempt("fork", fork)
    attempt("open_learner_db", lambda: open(args["learner_db"], "rb").read(1))
    attempt("write_scratch", lambda: open(os.path.join(os.getcwd(), "ok.txt"), "w").write("x"))
    return report, {"method": "exact", "confidence": "proved"}


def learner_probe(args, context):
    """Try to reach the learner store from inside the worker and report each attempt (ARC-21)."""
    report = {}

    def attempt(name, action):
        try:
            report[name] = f"ALLOWED ({action()!r})"
        except BaseException as error:  # any refusal counts
            report[name] = f"denied ({type(error).__name__})"

    def open_database():
        import sqlite3

        db = sqlite3.connect(f"file:{args['learner_db']}?mode=ro", uri=True)
        try:
            return db.execute("SELECT profile_id FROM meta").fetchone()
        finally:
            db.close()

    def read_bytes():
        with open(args["learner_db"], "rb") as handle:
            return handle.read(16)

    def control():  # the probe itself works: a file in the worker's own scratch directory
        path = os.path.join(os.getcwd(), "control.txt")
        with open(path, "w") as handle:
            handle.write("ok")
        with open(path) as handle:
            return handle.read()

    attempt("read_bytes", read_bytes)
    attempt("open_database", open_database)
    attempt("list_profiles", lambda: os.listdir(args["profiles"]))
    attempt("control", control)
    return report, {"method": "exact", "confidence": "proved"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", type=json.loads, default=server_module.PROTOCOL)
    parser.add_argument("--limits", default="{}")
    parser.add_argument("--no-guard", action="store_true", help="test the OS sandbox alone")
    args = parser.parse_args()
    server_module.PROTOCOL = args.protocol
    functions = dict(FUNCTIONS)
    for name, implementation in (("slow", slow), ("crash", crash), ("noisy", noisy), ("multiline", multiline)):
        functions[name] = Function(name, 1, SCHEMA, implementation)
    functions["escape"] = Function("escape", 1, {"type": "object"}, escape)
    functions["learner_probe"] = Function("learner_probe", 1, {"type": "object"}, learner_probe)
    functions["importer"] = Function("importer", 1, {"type": "object"}, importer)
    functions["operate"] = Function("operate", 1, {"type": "object"}, operate)
    functions["readfile"] = Function("readfile", 1, {"type": "object"}, readfile)
    functions["statfile"] = Function("statfile", 1, {"type": "object"}, statfile)
    limits = Limits(**json.loads(args.limits))
    frames = os.fdopen(os.dup(sys.stdout.fileno()), "wb", buffering=0)
    sys.stdout = sys.stderr
    if not args.no_guard:
        preload()
        guard.install(asdict(limits))
    Server(functions, frames, limits).serve(sys.stdin.buffer)


if __name__ == "__main__":
    main()
