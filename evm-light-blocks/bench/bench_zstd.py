"""Host-side cost per 1000-block segment: zstd decompression of full vs projected blocks (single core)."""
import os, sys, time, statistics, json, zstandard
OUT = sys.argv[1]
res = {}
for chain in ("ethereum", "bnb", "polygon"):
    res[chain] = {}
    for variant in ("full", "no_traces", "logs_view"):
        raw = open(os.path.join(OUT, f"{chain}_{variant}.binpb"), "rb").read()
        comp = zstandard.ZstdCompressor(level=3).compress(raw)
        d = zstandard.ZstdDecompressor()
        times = []
        for _ in range(40):
            t0 = time.perf_counter(); d.decompress(comp); times.append(time.perf_counter() - t0)
        per_block_ms = statistics.median(times) * 1000
        res[chain][variant] = {"compressed_bytes": len(comp), "decompress_ms_per_block": per_block_ms,
                               "segment_compressed_MB": len(comp) * 1000 / 1e6,
                               "segment_decompress_s": per_block_ms}  # ms per block * 1000 blocks / 1000 = s
        print(f"{chain:<9} {variant:<10} compressed {len(comp)/1024:7.1f} KB/block  "
              f"-> {len(comp)*1000/1e6:6.1f} MB per 1000-block segment, decompress {per_block_ms:6.3f} ms/block "
              f"= {per_block_ms:5.2f} s per segment")
json.dump(res, open(os.path.join(OUT, "zstd.json"), "w"), indent=2)
