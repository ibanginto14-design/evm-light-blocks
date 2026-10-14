"""Host-side cost per 1000-block segment: zstd decompression of full vs projected blocks (single core).

Timings on a shared machine are noisy, so each variant is timed in ROUNDS rounds (default 5),
interleaved across variants; the reported figure is the median of the per-round medians.
"""
import json
import os
import statistics
import sys
import time

import zstandard

OUT = sys.argv[1]
ROUNDS = int(os.environ.get("ROUNDS", "5"))
RUNS = 40
VARIANTS = ("full", "no_traces", "logs_view")

res = {}
for chain in ("ethereum", "bnb", "polygon"):
    comp = {}
    for variant in VARIANTS:
        raw = open(os.path.join(OUT, f"{chain}_{variant}.binpb"), "rb").read()
        comp[variant] = zstandard.ZstdCompressor(level=3).compress(raw)
    d = zstandard.ZstdDecompressor()
    round_medians = {v: [] for v in VARIANTS}
    for _ in range(ROUNDS):
        for variant in VARIANTS:
            times = []
            for _ in range(RUNS):
                t0 = time.perf_counter()
                d.decompress(comp[variant])
                times.append(time.perf_counter() - t0)
            round_medians[variant].append(statistics.median(times) * 1000)
    res[chain] = {}
    for variant in VARIANTS:
        per_block_ms = statistics.median(round_medians[variant])
        size = len(comp[variant])
        res[chain][variant] = {
            "compressed_bytes": size,
            "decompress_ms_per_block": per_block_ms,
            "decompress_ms_per_block_rounds": round_medians[variant],
            "segment_compressed_MB": size * 1000 / 1e6,
            "segment_decompress_s": per_block_ms,  # ms per block * 1000 blocks / 1000 = s
        }
        print(f"{chain:<9} {variant:<10} compressed {size/1024:7.1f} KB/block  "
              f"-> {size*1000/1e6:6.1f} MB per 1000-block segment, decompress {per_block_ms:6.3f} ms/block "
              f"= {per_block_ms:5.2f} s per segment")
json.dump(res, open(os.path.join(OUT, "zstd.json"), "w"), indent=2)
