use std::ffi::{c_char, c_void, CString};
use std::ptr;

pub const ABI_VERSION: u32 = 1;

#[repr(C)]
pub struct CliproxyBuffer {
    pub ptr: *mut u8,
    pub len: usize,
}

pub type HostCall = unsafe extern "C" fn(*mut c_void, *const c_char, *const u8, usize, *mut CliproxyBuffer) -> i32;
pub type HostFree = unsafe extern "C" fn(*mut c_void, usize);
pub type PluginCall = unsafe extern "C" fn(*const c_char, *const u8, usize, *mut CliproxyBuffer) -> i32;
pub type PluginFree = unsafe extern "C" fn(*mut c_void, usize);
pub type PluginShutdown = unsafe extern "C" fn();

#[repr(C)]
pub struct CliproxyHostApi {
    pub abi_version: u32,
    pub host_ctx: *mut c_void,
    pub call: Option<HostCall>,
    pub free_buffer: Option<HostFree>,
}

#[repr(C)]
pub struct CliproxyPluginApi {
    pub abi_version: u32,
    pub call: Option<PluginCall>,
    pub free_buffer: Option<PluginFree>,
    pub shutdown: Option<PluginShutdown>,
}

pub static mut STORED_HOST: *const CliproxyHostApi = ptr::null();

pub fn store_host_api(host: *const CliproxyHostApi) {
    unsafe {
        STORED_HOST = host;
    }
}

pub fn call_host(method: &str, payload: &[u8]) -> Option<Vec<u8>> {
    unsafe {
        if STORED_HOST.is_null() {
            return None;
        }
        let host = &*STORED_HOST;
        let call_fn = host.call?;
        let c_method = CString::new(method).ok()?;
        let mut resp_buf = CliproxyBuffer {
            ptr: ptr::null_mut(),
            len: 0,
        };

        let rc = call_fn(
            host.host_ctx,
            c_method.as_ptr(),
            payload.as_ptr(),
            payload.len(),
            &mut resp_buf,
        );

        if rc == 0 && !resp_buf.ptr.is_null() {
            let slice = std::slice::from_raw_parts(resp_buf.ptr, resp_buf.len);
            let result = slice.to_vec();
            if let Some(free_fn) = host.free_buffer {
                free_fn(resp_buf.ptr as *mut c_void, resp_buf.len);
            }
            Some(result)
        } else {
            None
        }
    }
}

pub fn write_response(response: *mut CliproxyBuffer, bytes: &[u8]) {
    if response.is_null() {
        return;
    }
    let mut vec_bytes = bytes.to_vec();
    let len = vec_bytes.len();
    let ptr = vec_bytes.as_mut_ptr();
    std::mem::forget(vec_bytes);
    unsafe {
        (*response).ptr = ptr;
        (*response).len = len;
    }
}
