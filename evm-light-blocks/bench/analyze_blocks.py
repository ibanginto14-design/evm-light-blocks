"""Measure how much of a Firehose Ethereum block a log-based module actually needs.

For each EVM fixture block shipped in streamingfast/substreams (wasm/bench/testdata), build:
  - full:       the block as stored today
  - logs_view:  same Block type, keeping only header + per-transaction identity/status + receipt logs
  - tx_view:    logs_view plus transaction-level fields (value, input, gas, fees), still without calls/state diffs
Then report raw and zstd-compressed sizes, and check that the logs a module would iterate
(successful transactions -> receipt.logs, as substreams-ethereum's Block::logs() does) are identical.
Writes light blocks to out/ so they can be fed to the WASM decode benchmark.
"""
import os
import sys
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "proto"))
import ethereum_pb2 as pb  # noqa: E402
import zstandard  # noqa: E402

FIXTURES = {
    "ethereum": "ethereum_mainnet_block_16021772.binpb",
    "bnb": "bnb_mainnet_block_78347457.binpb",
    "polygon": "polygon_mainnet_block_82340855.binpb",
}
FIXTURE_DIR = sys.argv[1]
OUT_DIR = sys.argv[2]
os.makedirs(OUT_DIR, exist_ok=True)

SUCCEEDED = pb.TransactionTraceStatus.Value("SUCCEEDED")


def logs_of(block):
    """Mirror of substreams-ethereum Block::logs(): successful txs -> receipt.logs."""
    out = []
    for tx in block.transaction_traces:
        if tx.status != SUCCEEDED:
            continue
        for log in tx.receipt.logs:
            out.append(log.SerializeToString(deterministic=True))
    return out


def project(block, keep_tx_fields):
    light = pb.Block()
    light.ver = block.ver
    light.hash = block.hash
    light.number = block.number
    light.size = block.size
    light.detail_level = block.detail_level
    light.header.CopyFrom(block.header)
    for tx in block.transaction_traces:
        t = light.transaction_traces.add()
        t.hash = tx.hash
        setattr(t, "from", getattr(tx, "from"))
        t.to = tx.to
        t.index = tx.index
        t.status = tx.status
        t.begin_ordinal = tx.begin_ordinal
        t.end_ordinal = tx.end_ordinal
        t.receipt.logs.extend(tx.receipt.logs)
        if keep_tx_fields:
            t.nonce = tx.nonce
            t.gas_limit = tx.gas_limit
            t.gas_used = tx.gas_used
            t.type = tx.type
            t.input = tx.input
            if tx.HasField("gas_price"):
                t.gas_price.CopyFrom(tx.gas_price)
            if tx.HasField("value"):
                t.value.CopyFrom(tx.value)
            if tx.HasField("max_fee_per_gas"):
                t.max_fee_per_gas.CopyFrom(tx.max_fee_per_gas)
            if tx.HasField("max_priority_fee_per_gas"):
                t.max_priority_fee_per_gas.CopyFrom(tx.max_priority_fee_per_gas)
            t.receipt.cumulative_gas_used = tx.receipt.cumulative_gas_used
    return light


def zsize(data, level):
    return len(zstandard.ZstdCompressor(level=level).compress(data))


results = {}
for chain, fname in FIXTURES.items():
    raw = open(os.path.join(FIXTURE_DIR, fname), "rb").read()
    block = pb.Block()
    block.ParseFromString(raw)

    n_tx = len(block.transaction_traces)
    n_calls = sum(len(tx.calls) for tx in block.transaction_traces)
    n_logs = len(logs_of(block))

    # where the bytes go
    parts = {
        "header": block.header.ByteSize(),
        "tx_calls": sum(c.ByteSize() for tx in block.transaction_traces for c in tx.calls),
        "tx_receipt_logs": sum(l.ByteSize() for tx in block.transaction_traces for l in tx.receipt.logs),
        "tx_input": sum(len(tx.input) for tx in block.transaction_traces),
        "balance_changes": sum(x.ByteSize() for x in block.balance_changes),
        "code_changes": sum(x.ByteSize() for x in block.code_changes),
        "system_calls": sum(x.ByteSize() for x in block.system_calls),
    }

    variants = {"full": raw}
    # no_traces: the exact proposal -- drop only the bulky trace/state structures, keep every other field
    nt = pb.Block()
    nt.CopyFrom(block)
    for tx in nt.transaction_traces:
        del tx.calls[:]
    del nt.system_calls[:]
    del nt.balance_changes[:]
    del nt.code_changes[:]
    nt.detail_level = pb.Block.DetailLevel.Value("DETAILLEVEL_BASE")
    nt_data = nt.SerializeToString(deterministic=True)
    assert logs_of(nt) == logs_of(block), f"{chain}/no_traces: logs differ"
    variants["no_traces"] = nt_data
    open(os.path.join(OUT_DIR, f"{chain}_no_traces.binpb"), "wb").write(nt_data)
    for name, keep in (("logs_view", False), ("tx_view", True)):
        light = project(block, keep)
        data = light.SerializeToString(deterministic=True)
        assert logs_of(light) == logs_of(block), f"{chain}/{name}: logs differ"
        variants[name] = data
        open(os.path.join(OUT_DIR, f"{chain}_{name}.binpb"), "wb").write(data)
    open(os.path.join(OUT_DIR, f"{chain}_full.binpb"), "wb").write(raw)

    sizes = {}
    for name, data in variants.items():
        sizes[name] = {
            "raw_bytes": len(data),
            "zstd3_bytes": zsize(data, 3),
            "zstd19_bytes": zsize(data, 19),
        }

    results[chain] = {
        "block_number": block.number,
        "detail_level": pb.Block.DetailLevel.Name(block.detail_level),
        "transactions": n_tx,
        "calls": n_calls,
        "logs_iterated": n_logs,
        "bytes_by_part": parts,
        "sizes": sizes,
    }

json.dump(results, open(os.path.join(OUT_DIR, "sizes.json"), "w"), indent=2)

for chain, r in results.items():
    s = r["sizes"]
    print(f"\n{chain} block {r['block_number']} ({r['detail_level']}): {r['transactions']} txs, "
          f"{r['calls']} calls, {r['logs_iterated']} logs")
    print("  bytes by part:", {k: f"{v/1024:.0f}KB" for k, v in r["bytes_by_part"].items()})
    for name in ("full", "no_traces", "tx_view", "logs_view"):
        v = s[name]
        print(f"  {name:<10} raw {v['raw_bytes']/1024:8.1f} KB  ({v['raw_bytes']/s['full']['raw_bytes']*100:5.1f}%)"
              f"   zstd3 {v['zstd3_bytes']/1024:7.1f} KB ({v['zstd3_bytes']/s['full']['zstd3_bytes']*100:5.1f}%)")
