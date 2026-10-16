use std::io::{BufRead, BufReader, Write};
use std::path::PathBuf;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::{Arc, Mutex};

#[derive(Clone)]
pub struct WorkerManager {
    inner: Arc<Mutex<WorkerInner>>,
}

struct WorkerInner {
    child: Option<Child>,
    stdin: Option<ChildStdin>,
    reader: Option<BufReader<std::process::ChildStdout>>,
    custom_python: String,
    data_dir: PathBuf,
    worker_script: PathBuf,
}

impl WorkerManager {
    pub fn new(data_dir: PathBuf, worker_script: PathBuf) -> Self {
        Self {
            inner: Arc::new(Mutex::new(WorkerInner {
                child: None,
                stdin: None,
                reader: None,
                custom_python: String::new(),
                data_dir,
                worker_script,
            })),
        }
    }

    pub fn set_custom_python(&self, path: String) {
        if let Ok(mut lock) = self.inner.lock() {
            if lock.custom_python != path {
                lock.custom_python = path;
                lock.stop();
            }
        }
    }

    #[allow(dead_code)]
    pub fn set_data_dir(&self, dir: PathBuf) {
        if let Ok(mut lock) = self.inner.lock() {
            if lock.data_dir != dir {
                lock.data_dir = dir;
                lock.stop();
            }
        }
    }

    #[allow(dead_code)]
    pub fn set_worker_script(&self, path: PathBuf) {
        if let Ok(mut lock) = self.inner.lock() {
            lock.worker_script = path;
        }
    }

    pub fn execute(&self, cmd: &str, params: serde_json::Value) -> Result<serde_json::Value, String> {
        let mut lock = self.inner.lock().map_err(|e| e.to_string())?;
        let mut last_err = String::new();

        // Never replay a paid generation when transport loses its receipt.
        let attempts = if cmd == "chat_completion" { 1 } else { 2 };
        for _ in 0..attempts {
            if let Err(e) = lock.ensure_started() {
                last_err = e;
                continue;
            }

            let req_id = format!("req_{}", std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_nanos());
            let msg = serde_json::json!({
                "id": req_id,
                "cmd": cmd,
                "params": params,
            });

            let mut line = match serde_json::to_string(&msg) {
                Ok(l) => l,
                Err(e) => return Err(e.to_string()),
            };
            line.push('\n');

            let write_res = if let Some(stdin) = lock.stdin.as_mut() {
                stdin.write_all(line.as_bytes()).and_then(|_| stdin.flush())
            } else {
                Err(std::io::Error::new(std::io::ErrorKind::BrokenPipe, "stdin is None"))
            };

            if let Err(e) = write_res {
                last_err = e.to_string();
                lock.stop();
                continue;
            }

            let mut resp_line = String::new();
            let read_res = if let Some(reader) = lock.reader.as_mut() {
                reader.read_line(&mut resp_line)
            } else {
                Err(std::io::Error::new(std::io::ErrorKind::BrokenPipe, "reader is None"))
            };

            if let Err(e) = read_res {
                last_err = e.to_string();
                lock.stop();
                continue;
            }

            if resp_line.trim().is_empty() {
                last_err = "Worker connection ended before a generation receipt was confirmed; no automatic generation retry".to_string();
                lock.stop();
                continue;
            }

            let parsed: serde_json::Value = match serde_json::from_str(resp_line.trim()) {
                Ok(v) => v,
                Err(e) => {
                    last_err = format!("Failed to parse worker response: {e}");
                    lock.stop();
                    continue;
                }
            };

            if let Some(err) = parsed.get("error") {
                let msg = err.get("message").and_then(|m| m.as_str()).unwrap_or("Worker error");
                return Err(msg.to_string());
            }

            return Ok(parsed.get("result").cloned().unwrap_or(serde_json::Value::Null));
        }

        Err(format!("Worker command {cmd} failed after retries: {last_err}"))
    }

    pub fn execute_stream<F>(&self, params: serde_json::Value, mut on_chunk: F) -> Result<(), String>
    where
        F: FnMut(&str) -> Result<(), String>,
    {
        let mut lock = self.inner.lock().map_err(|e| e.to_string())?;
        lock.ensure_started()?;

        let req_id = format!("stream_{}", std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_nanos());
        let msg = serde_json::json!({
            "id": req_id,
            "cmd": "chat_completion",
            "params": params,
        });

        let mut line = serde_json::to_string(&msg).map_err(|e| e.to_string())?;
        line.push('\n');

        let stdin = lock.stdin.as_mut().ok_or_else(|| "Worker stdin unavailable".to_string())?;
        stdin.write_all(line.as_bytes()).map_err(|e| e.to_string())?;
        stdin.flush().map_err(|e| e.to_string())?;

        let reader = lock.reader.as_mut().ok_or_else(|| "Worker stdout unavailable".to_string())?;
        loop {
            let mut chunk_line = String::new();
            if reader.read_line(&mut chunk_line).map_err(|e| e.to_string())? == 0 {
                return Err("GFlow stream ended without a completion receipt; generation result is unknown".to_string());
            }
            let trimmed = chunk_line.trim();
            if trimmed.is_empty() {
                continue;
            }
            if let Ok(parsed) = serde_json::from_str::<serde_json::Value>(trimmed) {
                if parsed.get("id").and_then(|i| i.as_str()) == Some(&req_id) {
                    if let Some(err) = parsed.get("error") {
                        let msg = err.get("message").and_then(|m| m.as_str()).unwrap_or("Stream generation error");
                        return Err(msg.to_string());
                    }
                    if parsed.get("done").and_then(|d| d.as_bool()) == Some(true) {
                        break;
                    }
                    if let Some(chunk_text) = parsed.get("chunk").and_then(|c| c.as_str()) {
                        on_chunk(chunk_text)?;
                    }
                }
            }
        }
        Ok(())
    }

    pub fn shutdown(&self) {
        if let Ok(mut lock) = self.inner.lock() {
            lock.stop();
        }
    }
}

impl WorkerInner {
    fn ensure_started(&mut self) -> Result<(), String> {
        if let Some(child) = self.child.as_mut() {
            if let Ok(Some(_)) = child.try_wait() {
                self.stop();
            } else {
                return Ok(());
            }
        }

        let python = self.resolve_python();
        let script = self.resolve_script();

        let mut cmd = Command::new(&python);
        cmd.arg(&script);
        cmd.arg(&self.data_dir);
        cmd.stdin(Stdio::piped());
        cmd.stdout(Stdio::piped());
        // Python 的 stderr 无人读取时会塞满管道并卡住同步；安全诊断由状态接口提供。
        cmd.stderr(Stdio::null());
        cmd.env("PYTHONDONTWRITEBYTECODE", "1");

        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            const CREATE_NO_WINDOW: u32 = 0x08000000;
            cmd.creation_flags(CREATE_NO_WINDOW);
        }

        let mut child = cmd.spawn().map_err(|e| {
            format!("Failed to spawn Python worker (cmd={:?}, script={:?}): {}", python, script, e)
        })?;

        let stdin = child.stdin.take().ok_or_else(|| "Failed to capture stdin".to_string())?;
        let stdout = child.stdout.take().ok_or_else(|| "Failed to capture stdout".to_string())?;
        let mut reader = BufReader::new(stdout);

        let mut ready_line = String::new();
        reader.read_line(&mut ready_line).map_err(|e| {
            format!("Failed to read worker ready handshake: {e}")
        })?;

        self.child = Some(child);
        self.stdin = Some(stdin);
        self.reader = Some(reader);

        Ok(())
    }

    fn stop(&mut self) {
        if let Some(mut stdin) = self.stdin.take() {
            let _ = stdin.write_all(b"{\"cmd\":\"shutdown\"}\n");
            let _ = stdin.flush();
        }
        if let Some(mut child) = self.child.take() {
            let _ = child.kill();
            let _ = child.wait();
        }
        self.reader = None;
    }

    fn resolve_python(&self) -> PathBuf {
        if !self.custom_python.trim().is_empty() {
            let p = PathBuf::from(self.custom_python.trim());
            if p.exists() {
                return p;
            }
        }

        // Try local virtualenv on D drive
        let d_venv = PathBuf::from(r"D:\zuhui\google flow\.venv\Scripts\python.exe");
        if d_venv.exists() {
            return d_venv;
        }

        // Try plugin-local venv
        let local_venv = self.data_dir.join("venv").join("Scripts").join("python.exe");
        if local_venv.exists() {
            return local_venv;
        }

        // Fallback to "python"
        PathBuf::from("python")
    }

    fn resolve_script(&self) -> PathBuf {
        if self.worker_script.exists() {
            return self.worker_script.clone();
        }
        // Fallback to searching relative to current exe or known dir
        PathBuf::from(r"D:\zuhui\EasyCLIProxyAPI-main\EasyCLIProxyAPI-main\cpa-plugin-GFlow\python\worker.py")
    }
}

impl Drop for WorkerInner {
    fn drop(&mut self) {
        self.stop();
    }
}
#[cfg(test)]
mod tests {
    use super::*;

    fn fixture() -> WorkerManager {
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        WorkerManager::new(root.join("data/tmp"), root.join("tests/worker_failure_fixture.py"))
    }

    #[test]
    fn upstream_failure_is_an_executor_error() {
        let worker = fixture();
        let result = worker.execute_stream(serde_json::json!({"stream": true}), |_| Ok(()));
        assert_eq!(result.unwrap_err(), "synthetic upstream rejection");
        worker.shutdown();
    }

    #[test]
    fn unexpected_stream_eof_is_not_a_success() {
        let worker = fixture();
        let result = worker.execute_stream(serde_json::json!({"stream": true, "force_eof": true}), |_| Ok(()));
        assert!(result.unwrap_err().contains("without a completion receipt"));
        worker.shutdown();
    }
}
