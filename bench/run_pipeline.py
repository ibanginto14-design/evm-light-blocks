"""Minimal Substreams-ABI host (wasmtime) to run real compiled modules end to end:

  1. blocks_without_traces (the proposed foundational module) on each full fixture block,
  2. a typical existing-style module (substreams 0.6 / prost, eager Block input) fed either the
     full block (today) or the light block produced in step 1 (the proposal),

and check that the typical module's output is byte-for-byte identical in both cases.
Implements the host imports these modules use: env.output, env.skip_empty_output, env.register_panic.
"""
import os
import statistics
import sys
import time
import json

import wasmtime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "proto"))
import ethereum_pb2 as pb  # noqa: E402

LIGHT_WASM, TYPICAL_WASM, FIXTURE_DIR, OUT = sys.argv[1:5]
RUNS = int(os.environ.get("RUNS", "100"))
FIXTURES = {
    "ethereum": "ethereum_mainnet_block_16021772.binpb",
    "bnb": "bnb_mainnet_block_78347457.binpb",
    "polygon": "polygon_mainnet_block_82340855.binpb",
}

engine = wasmtime.Engine()


class Module:
    def __init__(self, path, entrypoint):
        self.module = wasmtime.Module.from_file(engine, path)
        self.entrypoint = entrypoint

    def run(self, data):
        """Fresh instance per call, as production tier2 does (no instance cache)."""
        store = wasmtime.Store(engine)
        linker = wasmtime.Linker(engine)
        state = {"out": b"", "panic": None}

        def output(caller, ptr, length):
            mem = caller["memory"]
            state["out"] = bytes(mem.read(caller, ptr, ptr + length))

        def skip_empty_output(caller):
            pass

        def register_panic(caller, msg_ptr, msg_len, file_ptr, file_len, line, col):
            mem = caller["memory"]
            state["panic"] = bytes(mem.read(caller, msg_ptr, msg_ptr + msg_len)).decode(errors="replace")

        i32 = wasmtime.ValType.i32()
        linker.define_func("env", "output", wasmtime.FuncType([i32, i32], []), output, access_caller=True)
        linker.define_func("env", "skip_empty_output", wasmtime.FuncType([], []), skip_empty_output, access_caller=True)
        linker.define_func("env", "register_panic", wasmtime.FuncType([i32] * 6, []), register_panic, access_caller=True)
        linker.define_unknown_imports_as_traps(self.module)
        inst = linker.instantiate(store, self.module)
        ex = inst.exports(store)
        ptr = ex["alloc"](store, len(data))
        ex["memory"].write(store, data, ptr)
        t0 = time.perf_counter()
        ex[self.entrypoint](store, ptr, len(data))
        elapsed = (time.perf_counter() - t0) * 1000
        if state["panic"]:
            raise RuntimeError(state["panic"])
        return state["out"], elapsed


light_mod = Module(LIGHT_WASM, "blocks_without_traces")
typical = Module(TYPICAL_WASM, "map_transfers")
report = {}

for chain, fname in FIXTURES.items():
    full = open(os.path.join(FIXTURE_DIR, fname), "rb").read()

    light, _ = light_mod.run(full)
    light_times = [light_mod.run(full)[1] for _ in range(max(10, RUNS // 5))]

    # the light block must be a valid Block with the same header/transactions/receipts
    a, b = pb.Block(), pb.Block()
    a.ParseFromString(full)
    b.ParseFromString(light)
    assert a.hash == b.hash and a.number == b.number
    assert len(a.transaction_traces) == len(b.transaction_traces)
    for x, y in zip(a.transaction_traces, b.transaction_traces):
        assert x.receipt.SerializeToString(deterministic=True) == y.receipt.SerializeToString(deterministic=True)
        assert len(y.calls) == 0

    out_full, _ = typical.run(full)
    out_light, _ = typical.run(light)
    identical = out_full == out_light

    t_full, t_light = [], []
    for _ in range(RUNS):  # interleaved
        t_full.append(typical.run(full)[1])
        t_light.append(typical.run(light)[1])

    report[chain] = {
        "full_bytes": len(full),
        "light_bytes": len(light),
        "light_pct": round(len(light) / len(full) * 100, 1),
        "typical_output_bytes": len(out_full),
        "typical_output_identical": identical,
        "typical_full_ms_median": statistics.median(t_full),
        "typical_light_ms_median": statistics.median(t_light),
        "speedup": statistics.median(t_full) / statistics.median(t_light),
        "blocks_without_traces_ms_median": statistics.median(light_times),
    }
    r = report[chain]
    print(f"{chain:<9} light block {r['light_pct']:5.1f}% of bytes | typical module output identical: {identical} "
          f"({len(out_full)} bytes) | typical module {r['typical_full_ms_median']:6.2f} ms -> "
          f"{r['typical_light_ms_median']:5.2f} ms ({r['speedup']:.1f}x) | one-time projection "
          f"{r['blocks_without_traces_ms_median']:5.2f} ms")
    assert identical, f"{chain}: outputs differ"

json.dump(report, open(os.path.join(OUT, "pipeline.json"), "w"), indent=2)
