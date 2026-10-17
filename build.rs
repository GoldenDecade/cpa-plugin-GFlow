use std::env;
use std::fs;
use std::path::PathBuf;

fn main() {
    println!("cargo:rerun-if-env-changed=GFLOW_WORKER_BINARY");
    println!("cargo:rerun-if-env-changed=GFLOW_WORKER_SHA256");
    let source = match env::var("GFLOW_WORKER_BINARY") {
        Ok(filename) => {
            let path = fs::canonicalize(filename).expect("bundled worker must exist");
            let digest = env::var("GFLOW_WORKER_SHA256").expect("worker SHA256 must be supplied");
            assert!(digest.len() == 64 && digest.bytes().all(|value| value.is_ascii_hexdigit()));
            println!("cargo:rerun-if-changed={}", path.display());
            format!(
                "pub const WORKER_BINARY: &[u8] = include_bytes!({:?});\npub const WORKER_DIGEST: &str = {:?};\n",
                path.to_str().expect("UTF-8 worker path"), digest,
            )
        }
        Err(_) => "pub const WORKER_BINARY: &[u8] = &[];\npub const WORKER_DIGEST: &str = \"development\";\n".to_string(),
    };
    fs::write(PathBuf::from(env::var_os("OUT_DIR").unwrap()).join("worker_bundle.rs"), source)
        .expect("write embedded worker metadata");
}
