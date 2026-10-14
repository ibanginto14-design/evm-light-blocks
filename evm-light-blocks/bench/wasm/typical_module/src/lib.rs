//! A module written the way most published Substreams packages are (substreams 0.6, prost,
//! eager `eth::Block` input): it extracts every ERC-20 Transfer event from the block.
use substreams::errors::Error;
use substreams::Hex;
use substreams_ethereum::pb::eth::v2 as eth;

const TRANSFER_TOPIC: [u8; 32] = [
    0xdd, 0xf2, 0x52, 0xad, 0x1b, 0xe2, 0xc8, 0x9b, 0x69, 0xc2, 0xb0, 0x68, 0xfc, 0x37, 0x8d, 0xaa,
    0x95, 0x2b, 0xa7, 0xf1, 0x63, 0xc4, 0xa1, 0x16, 0x28, 0xf5, 0x5a, 0x4d, 0xf5, 0x23, 0xb3, 0xef,
];

#[derive(Clone, PartialEq, prost::Message)]
pub struct Transfer {
    #[prost(string, tag = "1")] pub token: String,
    #[prost(string, tag = "2")] pub from: String,
    #[prost(string, tag = "3")] pub to: String,
    #[prost(string, tag = "4")] pub amount_hex: String,
    #[prost(string, tag = "5")] pub tx_hash: String,
    #[prost(uint32, tag = "6")] pub log_index: u32,
    #[prost(uint64, tag = "7")] pub block_number: u64,
    #[prost(uint64, tag = "8")] pub timestamp: u64,
}
#[derive(Clone, PartialEq, prost::Message)]
pub struct Transfers { #[prost(message, repeated, tag = "1")] pub transfers: Vec<Transfer> }

#[substreams::handlers::map]
fn map_transfers(blk: eth::Block) -> Result<Transfers, Error> {
    let mut out = Transfers::default();
    let ts = blk.timestamp_seconds();
    for log in blk.logs() {
        let topics = log.topics();
        if topics.len() != 3 || topics[0].as_slice() != TRANSFER_TOPIC { continue; }
        out.transfers.push(Transfer {
            token: Hex(log.address()).to_string(),
            from: Hex(&topics[1][12..]).to_string(),
            to: Hex(&topics[2][12..]).to_string(),
            amount_hex: Hex(log.data()).to_string(),
            tx_hash: Hex(&log.receipt.transaction.hash).to_string(),
            log_index: log.block_index(),
            block_number: blk.number,
            timestamp: ts,
        });
    }
    Ok(out)
}
