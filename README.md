# Light EVM blocks for Substreams

`blocks_without_traces` is the EVM counterpart of Solana's `blocks_without_votes`: a Substreams map
module that outputs the same `sf.ethereum.type.v2.Block` it receives, minus call traces and
block-level state changes. Modules that only read headers, transactions, receipts and logs can
consume it by changing one manifest line, with no code change.

```diff
 modules:
   - name: map_transfers
     inputs:
-      - source: sf.ethereum.type.v2.Block
+      - map: eth:blocks_without_traces
```

## Results

Measured on the three EVM fixture blocks shipped in `streamingfast/substreams` (`wasm/bench/testdata`).

| Chain (block) | Light block, raw / compressed | Data per 1,000-block segment | Decompression per segment | Typical module per block | Output |
| --- | --- | --- | --- | --- | --- |
| Ethereum (16,021,772) | 14.4% / 19.1% | 163 → 31 MB (5.2x) | 0.50 → 0.06 s (8.7x) | 4.32 → 0.96 ms (4.5x) | identical |
| BNB Chain (78,347,457) | 16.2% / 18.6% | 162 → 30 MB (5.4x) | 0.56 → 0.08 s (6.6x) | 4.46 → 1.02 ms (4.4x) | identical |
| Polygon (82,340,855) | 14.7% / 16.8% | 516 → 87 MB (5.9x) | 2.04 → 0.22 s (9.3x) | 13.69 → 2.46 ms (5.6x) | identical |

Raw JSON for every figure is in `bench/results/`. Absolute times come from a 2-vCPU sandbox; the
ratios are the meaningful part. Sizes and module outputs are deterministic and reproduce exactly.
Decompression timings are the noisiest figure: a light block decompresses in well under 0.1 ms, and
across repeated runs the ratio ranged from 5x to 12x. The table shows the medians committed in
`bench/results/zstd.json` (five rounds).

## Layout

- `module/` — the `blocks_without_traces` module (Rust, `substreams` 0.8 / buffa), its tests and
  manifest, and a packed `.spkg`.
- `bench/` — the scripts behind every number:
  - `analyze_blocks.py` — byte breakdown and the light views of each fixture block.
  - `bench_zstd.py` — compressed size and decompression time per 1,000-block segment.
  - `bench_decode.py` — in-WASM decode time, full vs light, for prost, buffa and buffa lazy views.
  - `run_pipeline.py` — runs the compiled `blocks_without_traces` module, then a typical
    existing-style module on full and on light blocks, and checks the outputs are byte-identical.
  - `wasm/` — the Rust sources of the benchmark modules (`decode_prost`, `decode_buffa`,
    `typical_module`).

## Reproduce

Module tests (native, no WASM needed):

```bash
cd module
cargo test --release -- --nocapture
```

Build and pack the module:

```bash
rustup target add wasm32-unknown-unknown
cargo build --release --target wasm32-unknown-unknown
substreams pack substreams.yaml
```

Benchmarks:

```bash
pip install protobuf grpcio-tools zstandard wasmtime
cd bench
python -m grpc_tools.protoc -I proto \
  -I "$(python -c 'import grpc_tools, os; print(os.path.join(os.path.dirname(grpc_tools.__file__), "_proto"))')" \
  --python_out=proto proto/ethereum.proto
python analyze_blocks.py ../module/testdata out
python bench_zstd.py out
for m in decode_prost decode_buffa typical_module; do
  (cd wasm/$m && cargo build --release --target wasm32-unknown-unknown)
done
python bench_decode.py out \
  wasm/decode_prost/target/wasm32-unknown-unknown/release/decode_prost.wasm \
  wasm/decode_buffa/target/wasm32-unknown-unknown/release/decode_buffa.wasm
(cd ../module && cargo build --release --target wasm32-unknown-unknown)
python run_pipeline.py \
  ../module/target/wasm32-unknown-unknown/release/evm_blocks_without_traces.wasm \
  wasm/typical_module/target/wasm32-unknown-unknown/release/typical_module.wasm \
  ../module/testdata out
```

## Third-party material

- The fixture blocks in `module/testdata` come from `streamingfast/substreams`
  (`wasm/bench/testdata`), Apache-2.0.
- `bench/proto/ethereum.proto` is the Firehose Ethereum block definition (`sf.ethereum.type.v2`),
  taken from the copy vendored in `graphprotocol/graph-node`.
- `module/substreams-ethereum-v0.10.5.spkg` is the StreamingFast release used as the manifest import
  for the `sf.ethereum.type.v2` types.

## License

Apache-2.0, see `LICENSE`.
