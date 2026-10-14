"""Time in-WASM block decoding (wasmtime, the production runtime) for full vs projected blocks.

Each measurement = one call into the module: decode the block bytes already in linear memory and
iterate every log (substreams-ethereum Block::logs()). The host-side copy into memory is timed
separately. Results are medians over many runs after warm-up.
"""
import json
import os
import statistics
import sys
import time

import wasmtime

OUT = sys.argv[1]
WASMS = {
    "prost (substreams 0.6/0.7)": (sys.argv[2], ["decode_logs"]),
    "buffa (substreams 0.8)": (sys.argv[3], ["decode_logs", "decode_logs_lazy"]),
}
CHAINS = ["ethereum", "bnb", "polygon"]
VARIANTS = ["full", "no_traces", "logs_view"]
RUNS = int(os.environ.get("RUNS", "60"))

engine = wasmtime.Engine()
results = {}
for label, (path, funcs) in WASMS.items():
    module = wasmtime.Module.from_file(engine, path)
    store = wasmtime.Store(engine)
    linker = wasmtime.Linker(engine)
    linker.define_unknown_imports_as_traps(module)
    inst = linker.instantiate(store, module)
    ex = inst.exports(store)
    mem, alloc, free = ex["memory"], ex["bench_alloc"], ex["bench_free"]
    for fn_name in funcs:
        fn = ex[fn_name]
        key = f"{label} :: {'lazy view' if 'lazy' in fn_name else 'eager decode'}"
        results[key] = {}
        for chain in CHAINS:
            results[key][chain] = {}
            # load every variant, then time them interleaved (round-robin) so CPU drift hits all equally
            loaded = {}
            for variant in VARIANTS:
                data = open(os.path.join(OUT, f"{chain}_{variant}.binpb"), "rb").read()
                ptr = alloc(store, len(data))
                t0 = time.perf_counter()
                mem.write(store, data, ptr)
                copy_ms = (time.perf_counter() - t0) * 1000
                n_logs = fn(store, ptr, len(data))
                for _ in range(5):
                    fn(store, ptr, len(data))
                loaded[variant] = (ptr, len(data), n_logs, copy_ms)
            times = {v: [] for v in VARIANTS}
            for _ in range(RUNS):
                for variant in VARIANTS:
                    ptr, size, _, _ = loaded[variant]
                    t0 = time.perf_counter()
                    fn(store, ptr, size)
                    times[variant].append((time.perf_counter() - t0) * 1000)
            for variant in VARIANTS:
                ptr, size, n_logs, copy_ms = loaded[variant]
                free(store, ptr, size)
                ts = sorted(times[variant])
                results[key][chain][variant] = {
                    "median_ms": statistics.median(ts),
                    "p10_ms": ts[len(ts) // 10],
                    "p90_ms": ts[len(ts) * 9 // 10],
                    "logs": n_logs,
                    "bytes": size,
                    "host_copy_ms": copy_ms,
                }

json.dump(results, open(os.path.join(OUT, "decode_times.json"), "w"), indent=2)
for key, by_chain in results.items():
    print(f"\n{key}")
    for chain, by_var in by_chain.items():
        full = by_var["full"]["median_ms"]
        cells = "  ".join(
            f"{v}: {by_var[v]['median_ms']:6.3f} ms ({full / by_var[v]['median_ms']:4.1f}x)" for v in VARIANTS
        )
        logs = {by_var[v]["logs"] for v in VARIANTS}
        print(f"  {chain:<9} {cells}   logs={logs}")
