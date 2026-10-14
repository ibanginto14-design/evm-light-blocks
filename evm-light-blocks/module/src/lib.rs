//! `blocks_without_traces`: the EVM counterpart of Solana's `blocks_without_votes`.
//!
//! It outputs the very same `sf.ethereum.type.v2.Block` it receives, minus the data that only
//! execution tracing produces and that most modules never read:
//!
//! - `transaction_traces[].calls` (internal calls, with their storage/balance/nonce/code changes,
//!   and the duplicate copy of every log they emitted),
//! - `system_calls`, `balance_changes` and `code_changes` at the block level.
//!
//! Every other field is kept untouched, including the header, every transaction-level field and
//! the receipts with their logs. `detail_level` is set to `DETAILLEVEL_BASE`, the level Firehose
//! already uses for blocks that carry no trace data, so a module that branches on it takes the
//! path written for trace-less blocks.
//!
//! A module that only reads headers, transactions, receipts and logs (for example through
//! `Block::logs()` or `Block::events()`) gets identical results from this output, while reading
//! a fraction of the bytes. Swap `source: sf.ethereum.type.v2.Block` for
//! `map: <import>:blocks_without_traces` in the manifest; the handler code does not change.

use substreams::errors::Error;
use substreams_ethereum::pb::eth::v2::{block::DetailLevel, Block};

/// Removes call traces and block-level state changes in place.
pub fn strip_traces(blk: &mut Block) {
    for trx in blk.transaction_traces.iter_mut() {
        trx.calls.clear();
    }
    blk.system_calls.clear();
    blk.balance_changes.clear();
    blk.code_changes.clear();
    blk.detail_level = DetailLevel::DETAILLEVEL_BASE.into();
}

#[substreams::handlers::map]
fn blocks_without_traces(mut blk: Block) -> Result<Block, Error> {
    strip_traces(&mut blk);
    Ok(blk)
}

#[cfg(test)]
mod tests {
    use super::*;
    use buffa::Message;

    const FIXTURES: [&str; 3] = [
        "testdata/ethereum_mainnet_block_16021772.binpb",
        "testdata/bnb_mainnet_block_78347457.binpb",
        "testdata/polygon_mainnet_block_82340855.binpb",
    ];

    fn load(path: &str) -> (Vec<u8>, Block) {
        let bytes = std::fs::read(path).expect("read fixture");
        let blk = Block::decode_from_slice(&bytes).expect("decode fixture");
        (bytes, blk)
    }

    /// Everything a log-based module sees through `Block::logs()`, encoded for comparison.
    fn logs_seen(blk: &Block) -> Vec<(Vec<u8>, Vec<u8>, u32)> {
        blk.logs()
            .map(|log| {
                (
                    log.receipt.transaction.hash.clone(),
                    log.log.encode_to_vec(),
                    log.block_index(),
                )
            })
            .collect()
    }

    #[test]
    fn logs_are_identical_and_block_is_smaller() {
        for path in FIXTURES {
            let (full_bytes, full) = load(path);
            let mut light = full.clone();
            strip_traces(&mut light);

            let light_bytes = light.encode_to_vec();
            let light = Block::decode_from_slice(&light_bytes).expect("light block decodes");

            assert!(!logs_seen(&full).is_empty(), "{path}: fixture has logs");
            assert_eq!(logs_seen(&full), logs_seen(&light), "{path}: logs differ");

            let ratio = light_bytes.len() as f64 / full_bytes.len() as f64;
            println!(
                "{path}: {} -> {} bytes ({:.1}%), {} logs",
                full_bytes.len(),
                light_bytes.len(),
                ratio * 100.0,
                logs_seen(&full).len()
            );
            assert!(ratio < 0.25, "{path}: expected a large reduction, got {ratio:.3}");
        }
    }

    #[test]
    fn keeps_header_transactions_and_receipts() {
        for path in FIXTURES {
            let (_, full) = load(path);
            let mut light = full.clone();
            strip_traces(&mut light);

            assert_eq!(full.hash, light.hash);
            assert_eq!(full.number, light.number);
            assert_eq!(full.header.encode_to_vec(), light.header.encode_to_vec());
            assert_eq!(full.transaction_traces.len(), light.transaction_traces.len());
            for (a, b) in full.transaction_traces.iter().zip(light.transaction_traces.iter()) {
                assert_eq!(a.hash, b.hash);
                assert_eq!(a.from, b.from);
                assert_eq!(a.to, b.to);
                assert_eq!(a.input, b.input);
                assert_eq!(a.status, b.status);
                assert_eq!(a.receipt.encode_to_vec(), b.receipt.encode_to_vec());
                assert!(b.calls.is_empty());
            }
            assert!(light.system_calls.is_empty());
            assert!(light.balance_changes.is_empty());
            assert!(light.code_changes.is_empty());
            assert!(light.detail_level == DetailLevel::DETAILLEVEL_BASE);
        }
    }

    #[test]
    fn is_idempotent() {
        let (_, full) = load(FIXTURES[0]);
        let mut once = full.clone();
        strip_traces(&mut once);
        let mut twice = once.clone();
        strip_traces(&mut twice);
        assert_eq!(once.encode_to_vec(), twice.encode_to_vec());
    }
}
