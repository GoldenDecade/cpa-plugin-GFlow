use std::fs::{self, File, OpenOptions};
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

include!(concat!(env!("OUT_DIR"), "/worker_bundle.rs"));

#[cfg(windows)]
pub fn library_path() -> Option<PathBuf> {
    use std::ffi::c_void;
    use std::os::windows::ffi::OsStringExt;
    #[link(name = "kernel32")]
    extern "system" {
        fn GetModuleHandleExW(flags: u32, address: *const u16, module: *mut *mut c_void) -> i32;
        fn GetModuleFileNameW(module: *mut c_void, filename: *mut u16, size: u32) -> u32;
    }
    let mut module = std::ptr::null_mut();
    let mut filename = vec![0u16; 32768];
    unsafe {
        if GetModuleHandleExW(6, library_path as *const () as *const u16, &mut module) == 0 {
            return None;
        }
        let count = GetModuleFileNameW(module, filename.as_mut_ptr(), filename.len() as u32);
        if count == 0 || count as usize >= filename.len() {
            return None;
        }
        Some(PathBuf::from(std::ffi::OsString::from_wide(&filename[..count as usize])))
    }
}

#[cfg(unix)]
pub fn library_path() -> Option<PathBuf> {
    use std::ffi::{c_char, c_void, CStr, OsStr};
    use std::os::unix::ffi::OsStrExt;
    #[repr(C)]
    struct LibraryInfo {
        filename: *const c_char,
        base: *mut c_void,
        symbol: *const c_char,
        address: *mut c_void,
    }
    #[cfg_attr(target_os = "linux", link(name = "dl"))]
    extern "C" {
        fn dladdr(address: *const c_void, info: *mut LibraryInfo) -> i32;
    }
    let mut info = LibraryInfo {
        filename: std::ptr::null(), base: std::ptr::null_mut(),
        symbol: std::ptr::null(), address: std::ptr::null_mut(),
    };
    unsafe {
        if dladdr(library_path as *const () as *const c_void, &mut info) == 0 || info.filename.is_null() {
            return None;
        }
        Some(PathBuf::from(OsStr::from_bytes(CStr::from_ptr(info.filename).to_bytes())))
    }
}

pub fn default_data_dir() -> PathBuf {
    let module = library_path().or_else(|| std::env::current_exe().ok());
    module.and_then(|path| path.canonicalize().ok()).and_then(|path| path.parent().map(Path::to_path_buf))
        .unwrap_or_else(|| PathBuf::from("."))
        .join("gflow-data")
}

pub fn configured_data_dir(value: &str) -> PathBuf {
    if value.trim().is_empty() {
        return default_data_dir();
    }
    let path = PathBuf::from(value);
    if path.is_absolute() { path } else { default_data_dir().join(path) }
}

fn matches_payload(path: &Path, payload: &[u8]) -> bool {
    let Ok(metadata) = fs::symlink_metadata(path) else { return false; };
    if !metadata.is_file() || metadata.len() != payload.len() as u64 {
        return false;
    }
    let Ok(mut file) = File::open(path) else { return false; };
    let mut buffer = [0u8; 65536];
    let mut offset = 0;
    while offset < payload.len() {
        let Ok(count) = file.read(&mut buffer) else { return false; };
        if count == 0 || offset + count > payload.len() || buffer[..count] != payload[offset..offset + count] {
            return false;
        }
        offset += count;
    }
    true
}

pub fn prepare_worker(data_dir: &Path) -> Result<PathBuf, String> {
    if WORKER_BINARY.is_empty() {
        return Err("This development build has no bundled worker; install a complete GFlow release".to_string());
    }
    let fresh = !data_dir.exists();
    fs::create_dir_all(data_dir).map_err(|error| error.to_string())?;
    #[cfg(unix)]
    if fresh {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(data_dir, fs::Permissions::from_mode(0o700)).map_err(|error| error.to_string())?;
    }
    #[cfg(windows)]
    let _ = fresh;
    let version = format!("{}-{}", env!("CARGO_PKG_VERSION"), &WORKER_DIGEST[..12]);
    let directory = data_dir.join("runtime").join(version);
    fs::create_dir_all(&directory).map_err(|error| format!("Create GFlow runtime directory: {error}"))?;
    let executable = directory.join(if cfg!(windows) { "gflow-worker.exe" } else { "gflow-worker" });
    if matches_payload(&executable, WORKER_BINARY) {
        return Ok(executable);
    }
    let nonce = SystemTime::now().duration_since(UNIX_EPOCH).map_err(|error| error.to_string())?.as_nanos();
    let temporary = directory.join(format!(".worker-{}-{nonce}", std::process::id()));
    let mut file = OpenOptions::new().write(true).create_new(true).open(&temporary)
        .map_err(|error| format!("Create bundled worker: {error}"))?;
    file.write_all(WORKER_BINARY).and_then(|_| file.sync_all()).map_err(|error| error.to_string())?;
    drop(file);
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(&temporary, fs::Permissions::from_mode(0o700)).map_err(|error| error.to_string())?;
    }
    fs::rename(&temporary, &executable).map_err(|error| format!("Install bundled GFlow worker: {error}"))?;
    Ok(executable)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn module_path_is_resolved_without_a_developer_directory() {
        assert!(library_path().is_some());
        assert_eq!(default_data_dir().file_name().unwrap(), "gflow-data");
    }

    #[test]
    fn relative_configuration_stays_under_the_plugin_data_directory() {
        assert_eq!(configured_data_dir("accounts"), default_data_dir().join("accounts"));
        assert_eq!(configured_data_dir(""), default_data_dir());
    }

    #[test]
    fn development_build_cannot_silently_depend_on_local_python() {
        if WORKER_BINARY.is_empty() {
            assert!(prepare_worker(Path::new("unused")).unwrap_err().contains("no bundled worker"));
        }
    }

    #[test]
    fn extracted_worker_is_compared_with_its_embedded_payload() {
        let nonce = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos();
        let directory = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join(".build/runtime-tests").join(nonce.to_string());
        fs::create_dir_all(&directory).unwrap();
        let path = directory.join("payload.bin");
        fs::write(&path, b"original").unwrap();
        assert!(matches_payload(&path, b"original"));
        fs::write(&path, b"modified").unwrap();
        assert!(!matches_payload(&path, b"original"));
    }
}
