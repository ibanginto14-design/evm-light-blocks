use buffa::{LazyMessageView, Message};
use substreams_ethereum::pb::eth::v2::{Block, BlockLazyView};

#[no_mangle]
pub extern "C" fn bench_alloc(len: usize) -> *mut u8 {
    let mut v = Vec::<u8>::with_capacity(len);
    let p = v.as_mut_ptr();
    std::mem::forget(v);
    p
}

#[no_mangle]
pub extern "C" fn bench_free(ptr: *mut u8, len: usize) {
    unsafe { drop(Vec::from_raw_parts(ptr, 0, len)) }
}

/// Eager buffa decode of the whole block (substreams 0.8 default owned type).
#[no_mangle]
pub extern "C" fn decode_logs(ptr: *const u8, len: usize) -> u32 {
    let bytes = unsafe { std::slice::from_raw_parts(ptr, len) };
    let blk = Block::decode_from_slice(bytes).expect("decode");
    let mut n = 0u32;
    for log in blk.logs() {
        n += 1;
        std::hint::black_box(log.address());
    }
    n
}

/// Lazy buffa view: nested messages decoded only on access.
#[no_mangle]
pub extern "C" fn decode_logs_lazy(ptr: *const u8, len: usize) -> u32 {
    let bytes = unsafe { std::slice::from_raw_parts(ptr, len) };
    let blk = BlockLazyView::decode_lazy(bytes).expect("decode");
    let mut n = 0u32;
    for log in blk.logs() {
        n += 1;
        std::hint::black_box(log.address);
    }
    n
}
