mod abi;
mod runtime;
mod worker;

use std::ffi::{c_char, c_void, CStr};
use std::sync::{Mutex, OnceLock};
use abi::{CliproxyBuffer, CliproxyHostApi, CliproxyPluginApi, ABI_VERSION};
use worker::WorkerManager;

static WORKER: OnceLock<WorkerManager> = OnceLock::new();

#[derive(Default)]
struct StreamThreads {
    stopping: bool,
    tasks: Vec<StreamThread>,
}

struct StreamThread {
    id: String,
    worker: WorkerManager,
    handle: std::thread::JoinHandle<()>,
}

static STREAM_THREADS: OnceLock<Mutex<StreamThreads>> = OnceLock::new();

fn stream_threads() -> &'static Mutex<StreamThreads> {
    STREAM_THREADS.get_or_init(|| Mutex::new(StreamThreads::default()))
}

#[cfg(test)]
thread_local! {
    static TEST_STREAM_WORKER: std::cell::RefCell<Option<WorkerManager>> = const { std::cell::RefCell::new(None) };
}

fn stream_worker() -> WorkerManager {
    #[cfg(test)]
    if let Some(worker) = TEST_STREAM_WORKER.with(|value| value.borrow().clone()) { return worker; }
    get_worker().clone()
}

fn apply_plugin_config(req: &[u8]) -> Result<(), String> {
    let value: serde_json::Value = serde_json::from_slice(req).unwrap_or_default();
    if let Some(encoded) = value.get("config_yaml").and_then(|value| value.as_str()) {
        use base64::Engine;
        let decoded = base64::engine::general_purpose::STANDARD.decode(encoded)
            .ok().and_then(|bytes| String::from_utf8(bytes).ok());
        let yaml = decoded.as_deref().unwrap_or(encoded);
        let mut directory = String::new();
        for line in yaml.lines() {
            if let Some(raw) = line.trim().strip_prefix("data_dir:") {
                directory = serde_json::from_str::<String>(raw.trim())
                    .unwrap_or_else(|_| raw.trim().trim_matches(char::from(39)).to_string());
            }
        }
        if directory.len() > 4096 || directory.chars().any(char::is_control) {
            return Err("data_dir contains invalid characters".to_string());
        }
        get_worker().set_data_dir(runtime::configured_data_dir(&directory));
    }
    Ok(())
}

fn get_worker() -> &'static WorkerManager {
    WORKER.get_or_init(|| WorkerManager::new(runtime::default_data_dir()))
}

const MANAGE_HTML: &str = include_str!("../static/manage.html");
const EXTENSION_ZIP: &[u8] = include_bytes!("../downloads/GFlow-browser-extension.zip");

#[no_mangle]
pub extern "C" fn cliproxy_plugin_init(
    host: *const CliproxyHostApi,
    plugin: *mut CliproxyPluginApi,
) -> i32 {
    if plugin.is_null() {
        return 1;
    }
    abi::store_host_api(host);
    let _ = get_worker();
    if let Ok(mut streams) = stream_threads().lock() { streams.stopping = false; }

    unsafe {
        (*plugin).abi_version = ABI_VERSION;
        (*plugin).call = Some(plugin_call);
        (*plugin).free_buffer = Some(plugin_free);
        (*plugin).shutdown = Some(plugin_shutdown);
    }
    0
}

unsafe extern "C" fn plugin_call(
    method: *const c_char,
    request: *const u8,
    request_len: usize,
    response: *mut CliproxyBuffer,
) -> i32 {
    if !response.is_null() {
        (*response).ptr = std::ptr::null_mut();
        (*response).len = 0;
    }
    if method.is_null() {
        write_error(response, "invalid_method", "method is required", 400);
        return 1;
    }
    let method_str = match CStr::from_ptr(method).to_str() {
        Ok(v) => v,
        Err(_) => {
            write_error(response, "invalid_method", "method is not valid utf-8", 400);
            return 1;
        }
    };

    let req_bytes = if !request.is_null() && request_len > 0 {
        std::slice::from_raw_parts(request, request_len)
    } else {
        &[]
    };

    match handle_method(method_str, req_bytes) {
        Ok(resp_bytes) => {
            abi::write_response(response, &resp_bytes);
            0
        }
        Err(e) => {
            write_error(response, "plugin_error", &e, 500);
            1
        }
    }
}

unsafe extern "C" fn plugin_free(ptr: *mut c_void, len: usize) {
    if !ptr.is_null() && len > 0 {
        let _ = Vec::from_raw_parts(ptr as *mut u8, len, len);
    }
}

unsafe extern "C" fn plugin_shutdown() {
    let tasks = {
        let mut streams = stream_threads().lock().unwrap_or_else(|error| error.into_inner());
        streams.stopping = true;
        std::mem::take(&mut streams.tasks)
    };
    // Closing the host bridge releases a callback waiting on its bounded queue.
    // The host callback table must remain valid until shutdown returns. A host
    // that never returns from a callback cannot safely unload this DLL.
    for task in &tasks {
        if let Err(error) = close_host_stream(&task.id, "GFlow plugin is shutting down; generation was not retried") {
            eprintln!("[GFlow] {error}");
        }
    }
    for task in &tasks { task.worker.shutdown(); }
    for task in tasks {
        let worker = task.worker.clone();
        if task.handle.join().is_err() { eprintln!("[GFlow] stream thread terminated unexpectedly"); }
        // A task racing shutdown may only have started its child after the
        // first stop. No background native thread survives this join.
        worker.shutdown();
    }
    get_worker().shutdown();
}

fn handle_method(method: &str, req_bytes: &[u8]) -> Result<Vec<u8>, String> {
    match method {
        "plugin.register" => handle_register(req_bytes),
        "plugin.reconfigure" => handle_reconfigure(req_bytes),
        "model.static" => handle_model_static(req_bytes),
        "model.route" => handle_model_route(req_bytes),
        "executor.identifier" => handle_executor_identifier(),
        "executor.count_tokens" => handle_count_tokens(),
        "executor.execute" => handle_executor_execute(req_bytes),
        "executor.execute_stream" => handle_executor_stream(req_bytes),
        "management.register" => handle_management_register(),
        "management.handle" => handle_management_handle(req_bytes),
        _ => Err(format!("unsupported plugin method: {method}")),
    }
}

fn handle_register(req: &[u8]) -> Result<Vec<u8>, String> {
    apply_plugin_config(req)?;
    let reg = serde_json::json!({
        "ok": true,
        "result": {
            "schema_version": 6,
            "metadata": {
                "Name": "GFlow",
                "Version": env!("CARGO_PKG_VERSION"),
                "Author": "daodeqing",
                "Description": "Google Flow 图片/视频生成、固定项目绑定与多账号池管理插件",
                "GitHubRepository": "https://github.com/daodeqing/cpa-plugin-GFlow",
                "Logo": "https://raw.githubusercontent.com/daodeqing/cpa-plugin-GFlow/main/assets/logo.png",
                "Homepage": "https://github.com/daodeqing/cpa-plugin-GFlow",
                "License": "MIT",
                "Tags": ["Model", "Video", "Image", "Google Flow", "Veo", "Nano Banana"],
                "ConfigFields": [
                    {
                        "Name": "data_dir",
                        "Type": "string",
                        "Default": "",
                        "Description": "数据目录（留空使用插件动态库旁的 gflow-data；内含账号数据库、日志和独立后台运行时）"
                    }
                ]
            },
            "capabilities": {
                "model_provider": true,
                "model_router": true,
                "executor": true,
                "executor_model_scope": "both",
                "executor_input_formats": ["chat-completions"],
                "executor_output_formats": ["chat-completions"],
                "management_api": true
            }
        }
    });
    serde_json::to_vec(&reg).map_err(|e| e.to_string())
}

fn handle_reconfigure(req: &[u8]) -> Result<Vec<u8>, String> {
    handle_register(req)
}

fn handle_model_static(_req: &[u8]) -> Result<Vec<u8>, String> {
    let worker_models = get_worker().execute("list_models", serde_json::json!({})).unwrap_or(serde_json::json!({}));
    let mut models_list = Vec::new();

    if let Some(arr) = worker_models.get("models").and_then(|m| m.as_array()) {
        for m in arr {
            let id = m.get("id").and_then(|s| s.as_str()).unwrap_or("");
            let desc = m.get("display_name").or_else(|| m.get("DisplayName")).or_else(|| m.get("description")).and_then(|s| s.as_str()).unwrap_or("");
            if !id.is_empty() {
                models_list.push(serde_json::json!({
                    "ID": id,
                    "Object": "model",
                    "OwnedBy": "gflow",
                    "DisplayName": desc,
                    "SupportedGenerationMethods": ["chat", "generateContent"],
                    "ContextLength": 8192,
                    "UserDefined": true
                }));
            }
        }
    }

    if models_list.is_empty() {
        // Fallback default catalog
        let defaults = [
            ("gflow-nano-banana-pro", "Nano Banana Pro"),
            ("gflow-nano-banana-2-lite", "Nano Banana 2 Lite"),
            ("gflow-nano-banana-2.1", "Nano Banana 2.1"),
            ("gflow-omni-1.1-flash", "Omni 1.1 Flash"),
            ("gflow-veo-3.1-lite", "Veo 3.1 - Lite"),
            ("gflow-veo-3.1-fast", "Veo 3.1 - Fast"),
            ("gflow-veo-3.1-quality", "Veo 3.1 - Quality"),
        ];
        for (id, desc) in defaults {
            models_list.push(serde_json::json!({
                "ID": id,
                "Object": "model",
                "OwnedBy": "gflow",
                "DisplayName": desc,
                "SupportedGenerationMethods": ["chat", "generateContent"],
                "ContextLength": 8192,
                "UserDefined": true
            }));
        }
    }

    models_list.push(project_control_model());
    let out = serde_json::json!({
        "ok": true,
        "result": {
            "Provider": "gflow",
            "Models": models_list
        }
    });
    serde_json::to_vec(&out).map_err(|e| e.to_string())
}

fn handle_model_route(req: &[u8]) -> Result<Vec<u8>, String> {
    let req_val: serde_json::Value = serde_json::from_slice(req).map_err(|e| e.to_string())?;
    let requested_model = req_val.get("RequestedModel").and_then(|m| m.as_str()).unwrap_or("");

    let should_handle = requested_model.starts_with("gflow-")
        || requested_model.starts_with("nano-banana")
        || requested_model.starts_with("veo-")
        || requested_model.starts_with("omni-")
        || (requested_model.starts_with("gemini-3.") && requested_model.contains("-image"));

    let out = if should_handle {
        serde_json::json!({
            "ok": true,
            "result": {
                "Handled": true,
                "TargetKind": "self",
                "Reason": "matched_gflow"
            }
        })
    } else {
        serde_json::json!({
            "ok": true,
            "result": {
                "Handled": false
            }
        })
    };
    serde_json::to_vec(&out).map_err(|e| e.to_string())
}

fn handle_executor_identifier() -> Result<Vec<u8>, String> {
    let out = serde_json::json!({
        "ok": true,
        "result": {
            "identifier": "gflow"
        }
    });
    serde_json::to_vec(&out).map_err(|e| e.to_string())
}

fn handle_count_tokens() -> Result<Vec<u8>, String> {
    use base64::Engine;
    let b64 = base64::engine::general_purpose::STANDARD.encode(b"{\"total_tokens\":0}");
    let out = serde_json::json!({
        "ok": true,
        "result": {
            "Payload": b64
        }
    });
    serde_json::to_vec(&out).map_err(|e| e.to_string())
}

const PROJECT_CONTROL_MODEL: &str = "gflow-project-control";

fn project_control_model() -> serde_json::Value {
    serde_json::json!({
        "ID": PROJECT_CONTROL_MODEL, "Object": "model", "OwnedBy": "gflow",
        "DisplayName": "GFlow Project Control (no media generation)",
        "SupportedGenerationMethods": ["chat"], "ContextLength": 8192,
        "UserDefined": true
    })
}

// 宿主格式适配可能只保留标准字段，项目绑定必须从原请求完整保留。
fn executor_body(request: &serde_json::Value) -> Result<serde_json::Value, String> {
    use base64::Engine;
    let decode = |field: &str| -> serde_json::Value {
        request.get(field).and_then(|v| v.as_str())
            .and_then(|v| base64::engine::general_purpose::STANDARD.decode(v).ok())
            .and_then(|v| serde_json::from_slice(&v).ok())
            .unwrap_or_else(|| serde_json::json!({}))
    };
    let original = decode("OriginalRequest");
    let mut body = if request.get("Payload").and_then(|v| v.as_str()).is_some() {
        decode("Payload")
    } else { original.clone() };
    if !body.is_object() { return Err("Invalid executor request object".into()); }
    for field in ["gflow_workspace_id", "gflow_project_id", "gflow_instance_id"] {
        if let Some(value) = original.get(field) {
            if body.get(field).is_some_and(|existing| existing != value) {
                return Err("Conflicting GFlow project binding fields".into());
            }
            body[field] = value.clone();
        }
    }
    if let Some(model) = request.get("Model").and_then(|v| v.as_str()).filter(|v| !v.is_empty()) {
        body["model"] = serde_json::json!(model);
    }
    Ok(body)
}

fn handle_executor_execute(req: &[u8]) -> Result<Vec<u8>, String> {
    use base64::Engine;
    let req_val: serde_json::Value = serde_json::from_slice(req).map_err(|e| e.to_string())?;

    let body_json = executor_body(&req_val)?;

    let worker_res = get_worker().execute("chat_completion", body_json)?;
    let res_bytes = serde_json::to_vec(&worker_res).map_err(|e| e.to_string())?;
    let b64 = base64::engine::general_purpose::STANDARD.encode(&res_bytes);

    let out = serde_json::json!({
        "ok": true,
        "result": {
            "Payload": b64,
            "Headers": {
                "content-type": ["application/json; charset=utf-8"]
            }
        }
    });
    serde_json::to_vec(&out).map_err(|e| e.to_string())
}

fn handle_executor_stream(req: &[u8]) -> Result<Vec<u8>, String> {
    let req_val: serde_json::Value = serde_json::from_slice(req).map_err(|e| e.to_string())?;

    let stream_id = req_val.get("stream_id").and_then(|s| s.as_str()).unwrap_or("");
    if stream_id.is_empty() { return Err("stream_id is required for streaming execution".into()); }
    let mut body_json = executor_body(&req_val)?;
    body_json["stream"] = serde_json::Value::Bool(true);
    let out = serde_json::json!({
        "ok": true,
        "result": {
            "headers": {
                "content-type": ["text/event-stream"]
            },
            "chunks": []
        }
    });
    let response = serde_json::to_vec(&out).map_err(|e| e.to_string())?;
    let worker = stream_worker();
    let mut streams = stream_threads().lock().map_err(|_| "stream lifecycle lock failed".to_string())?;
    if streams.stopping { return Err("GFlow plugin is shutting down".into()); }
    let mut active = Vec::new();
    for task in streams.tasks.drain(..) {
        if task.handle.is_finished() {
            if task.handle.join().is_err() { eprintln!("[GFlow] stream thread terminated unexpectedly"); }
        } else { active.push(task); }
    }
    streams.tasks = active;
    let sid = stream_id.to_string();
    let task_id = sid.clone();
    let task_worker = worker.clone();
    let handle = std::thread::Builder::new().name("gflow-stream".into()).spawn(move || {
        run_executor_stream(task_worker, task_id, body_json);
    }).map_err(|_| "GFlow stream thread could not start".to_string())?;
    streams.tasks.push(StreamThread { id: sid, worker, handle });
    // The host starts consuming its bounded stream queue only after this ABI
    // call returns. Running emit synchronously here deadlocks a full queue.
    Ok(response)
}

fn run_executor_stream(worker: WorkerManager, stream_id: String, body: serde_json::Value) {
    use base64::Engine;
    let stopping = stream_threads().lock().map(|streams| streams.stopping).unwrap_or(true);
    let result = if stopping { Err("GFlow plugin is shutting down".to_string()) } else {
        worker.execute_stream(body, |chunk| {
            let request = serde_json::json!({"stream_id":stream_id,
                "payload":base64::engine::general_purpose::STANDARD.encode(chunk.as_bytes())});
            host_stream_callback("host.stream.emit", &request)
        })
    };
    if let Err(error) = close_host_stream(&stream_id, result.as_ref().err().map(String::as_str).unwrap_or("")) {
        eprintln!("[GFlow] {error}");
    }
}

fn close_host_stream(stream_id: &str, error: &str) -> Result<(), String> {
    host_stream_callback("host.stream.close", &serde_json::json!({"stream_id":stream_id,"error":error}))
}

fn host_stream_callback(method: &str, request: &serde_json::Value) -> Result<(), String> {
    let bytes = serde_json::to_vec(request).map_err(|_| "stream callback request encoding failed".to_string())?;
    let method_name = std::ffi::CString::new(method).map_err(|_| "invalid stream callback name".to_string())?;
    // Capture and release the host's response even for a nonzero ABI status.
    // Never treat a rejected/invalid callback receipt as delivered media.
    let (status, response) = unsafe {
        let host = abi::STORED_HOST.as_ref().ok_or_else(|| format!("{method} callback is unavailable"))?;
        let callback = host.call.ok_or_else(|| format!("{method} callback is unavailable"))?;
        let mut buffer = CliproxyBuffer { ptr:std::ptr::null_mut(), len:0 };
        let status = callback(host.host_ctx, method_name.as_ptr(), bytes.as_ptr(), bytes.len(), &mut buffer);
        let response = if buffer.ptr.is_null() { Vec::new() } else {
            let response = std::slice::from_raw_parts(buffer.ptr, buffer.len).to_vec();
            if let Some(free) = host.free_buffer { free(buffer.ptr.cast(), buffer.len); }
            response
        };
        (status, response)
    };
    if status != 0 { return Err(format!("{method} callback failed; generation was not retried")); }
    let result: serde_json::Value = serde_json::from_slice(&response)
        .map_err(|_| format!("{method} returned an invalid callback receipt"))?;
    if result.get("ok").and_then(serde_json::Value::as_bool) != Some(true) {
        return Err(format!("{method} callback was rejected; generation was not retried"));
    }
    Ok(())
}

fn handle_management_register() -> Result<Vec<u8>, String> {
    let out = serde_json::json!({
        "ok": true,
        "result": {
            "Resources": [
                {
                    "Path": "/manage",
                    "Menu": "GFlow",
                    "Description": "GFlow 账号与模型管理控制台"
                },
                {
                    "Path": "/extension.zip",
                    "Description": "下载 GFlow 登录助手"
                }
            ],
            "Routes": [
                { "Method": "GET", "Path": "/plugins/gflow/api/status" },
                { "Method": "GET", "Path": "/plugins/gflow/api/models" },
                { "Method": "GET", "Path": "/plugins/gflow/api/media" },
                { "Method": "GET", "Path": "/plugins/gflow/api/tokens" },
                { "Method": "POST", "Path": "/plugins/gflow/api/tokens" },
                { "Method": "PUT", "Path": "/plugins/gflow/api/tokens" },
                { "Method": "DELETE", "Path": "/plugins/gflow/api/tokens" },
                { "Method": "POST", "Path": "/plugins/gflow/api/refresh" },
                { "Method": "POST", "Path": "/plugins/gflow/api/extension-sync" },
                { "Method": "GET", "Path": "/plugins/gflow/api/config" },
                { "Method": "POST", "Path": "/plugins/gflow/api/config" }
            ]
        }
    });
    serde_json::to_vec(&out).map_err(|e| e.to_string())
}

fn handle_management_handle(req: &[u8]) -> Result<Vec<u8>, String> {
    use base64::Engine;
    let req_val: serde_json::Value = serde_json::from_slice(req).map_err(|e| e.to_string())?;

    let path = req_val.get("Path").and_then(|s| s.as_str()).unwrap_or("");
    let method = req_val.get("Method").and_then(|s| s.as_str()).unwrap_or("GET");

    if path == "/v0/resource/plugins/gflow/extension.zip" && method == "GET" {
        let out = serde_json::json!({"ok":true,"result":{
            "StatusCode":200,
            "Headers":{
                "content-type":["application/zip"],
                "content-disposition":["attachment; filename=GFlow-browser-extension.zip"],
                "cache-control":["no-cache"],
                "x-content-type-options":["nosniff"]
            },
            "Body":base64::engine::general_purpose::STANDARD.encode(EXTENSION_ZIP)
        }});
        return serde_json::to_vec(&out).map_err(|e| e.to_string());
    }

    // 1. Serve HTML dashboard resource
    if path == "/v0/resource/plugins/gflow/manage" && method == "GET" {
        let b64 = base64::engine::general_purpose::STANDARD.encode(MANAGE_HTML.as_bytes());
        let out = serde_json::json!({
            "ok": true,
            "result": {
                "StatusCode": 200,
                "Headers": {
                    "content-type": ["text/html; charset=utf-8"],
                    "cache-control": ["no-store"],
                    "referrer-policy": ["no-referrer"],
                    "x-content-type-options": ["nosniff"]
                },
                "Body": b64
            }
        });
        return serde_json::to_vec(&out).map_err(|e| e.to_string());
    }

    let Some(route) = path.strip_prefix("/v0/management/plugins/gflow/api/") else {
        return Ok(management_error(404, "Not found"));
    };
    let allowed = match route {
        "status" | "models" | "media" => method == "GET",
        "tokens" => matches!(method, "GET" | "POST" | "PUT" | "DELETE"),
        "config" => matches!(method, "GET" | "POST"),
        "refresh" | "extension-sync" => method == "POST",
        _ => return Ok(management_error(404, "Not found")),
    };
    if !allowed {
        return Ok(management_error(405, "Method not allowed"));
    }
    if route == "media" {
        let filename = req_val["Query"]["file"].as_array().and_then(|items| items.first())
            .and_then(|item| item.as_str()).or_else(|| req_val["Query"]["file"].as_str()).unwrap_or("");
        let Some(clean_filename) = cached_media_name(filename) else {
            return Ok(management_error(404, "File not found"));
        };

        let cache_root = get_worker().data_dir()?.join("tmp");
        let tmp_path = cache_root.join(clean_filename);
        if !tmp_path.is_file() || tmp_path.is_symlink()
            || tmp_path.canonicalize().ok().and_then(|value| value.parent().map(std::path::Path::to_path_buf)) != cache_root.canonicalize().ok() {
            return Ok(management_error(404, "File not found"));
        }

        let content_type = if clean_filename.ends_with(".mp4") {
            "video/mp4"
        } else if clean_filename.ends_with(".webm") {
            "video/webm"
        } else if clean_filename.ends_with(".mov") {
            "video/quicktime"
        } else if clean_filename.ends_with(".jpg") || clean_filename.ends_with(".jpeg") {
            "image/jpeg"
        } else if clean_filename.ends_with(".png") {
            "image/png"
        } else if clean_filename.ends_with(".webp") {
            "image/webp"
        } else {
            "application/octet-stream"
        };

        if let Ok(bytes) = std::fs::read(&tmp_path) {
            let b64 = base64::engine::general_purpose::STANDARD.encode(&bytes);
            let out = serde_json::json!({
                "ok": true,
                "result": {
                    "StatusCode": 200,
                    "Headers": {
                        "content-type": [content_type],
                        "cache-control": ["no-store, private"],
                        "x-content-type-options": ["nosniff"]
                    },
                    "Body": b64
                }
            });
            return serde_json::to_vec(&out).map_err(|e| e.to_string());
        } else {
            return Ok(management_error(500, "Failed to read cached file"));
        }
    }

    // 3. Management API routes
    let body_bytes = if let Some(b) = req_val.get("Body").and_then(|s| s.as_str()) {
        base64::engine::general_purpose::STANDARD.decode(b).unwrap_or_default()
    } else {
        Vec::new()
    };
    let body_json: serde_json::Value = serde_json::from_slice(&body_bytes).unwrap_or_else(|_| serde_json::json!({}));

    let result = if path.ends_with("/api/models") {
        get_worker().execute("list_models", serde_json::json!({}))
    } else if path.ends_with("/api/status") {
        get_worker().execute("status", serde_json::json!({})).map(|mut value| {
            value["plugin_version"] = serde_json::json!(env!("CARGO_PKG_VERSION"));
            value
        })
    } else if path.ends_with("/api/tokens") {
        match method {
            "GET" => get_worker().execute("list_tokens", serde_json::json!({})),
            "POST" => get_worker().execute("add_token", body_json),
            "PUT" => get_worker().execute("toggle_token", body_json),
            "DELETE" => get_worker().execute("delete_token", body_json),
            _ => Err("Method not allowed".to_string()),
        }
    } else if path.ends_with("/api/extension-sync") {
        get_worker().execute("extension_sync", body_json)
    } else if path.ends_with("/api/refresh") {
        get_worker().execute("refresh_credits", body_json)
    } else if path.ends_with("/api/config") {
        match method {
            "GET" => get_worker().execute("get_config", serde_json::json!({})),
            "POST" => get_worker().execute("update_config", body_json),
            _ => Err("Method not allowed".to_string()),
        }
    } else {
        Err(format!("Not found: {path}"))
    };

    match result {
        Ok(mut data) => {
            // 同步的业务失败保留分类与 HTTP 状态，不再统一包装成 500 或假成功。
            let status_code = data.get("status_code").and_then(|v| v.as_u64())
                .filter(|status| (400..600).contains(status)).unwrap_or(200);
            if let Some(object) = data.as_object_mut() { object.remove("status_code"); }
            let json_bytes = serde_json::to_vec(&data).unwrap_or_default();
            let b64 = base64::engine::general_purpose::STANDARD.encode(&json_bytes);
            let out = serde_json::json!({
                "ok": true,
                "result": {
                    "StatusCode": status_code,
                    "Headers": {
                        "content-type": ["application/json; charset=utf-8"]
                    },
                    "Body": b64
                }
            });
            serde_json::to_vec(&out).map_err(|e| e.to_string())
        }
        Err(e) => Ok(management_error(if e.starts_with("GFlow backend request timed out") { 504 } else { 500 }, &e)),
    }
}

fn management_error(status: i32, msg: &str) -> Vec<u8> {
    use base64::Engine;
    let err_json = serde_json::json!({ "error": { "message": msg, "code": status } });
    let bytes = serde_json::to_vec(&err_json).unwrap_or_default();
    let b64 = base64::engine::general_purpose::STANDARD.encode(&bytes);
    let out = serde_json::json!({
        "ok": true,
        "result": {
            "StatusCode": status,
            "Headers": { "content-type": ["application/json; charset=utf-8"] },
            "Body": b64
        }
    });
    serde_json::to_vec(&out).unwrap_or_default()
}

fn write_error(response: *mut CliproxyBuffer, code: &str, message: &str, status: i32) {
    let err = serde_json::json!({
        "ok": false,
        "error": {
            "code": code,
            "message": message,
            "http_status": status
        }
    });
    if let Ok(bytes) = serde_json::to_vec(&err) {
        abi::write_response(response, &bytes);
    }
}

fn cached_media_name(filename: &str) -> Option<&str> {
    let (stem, extension) = filename.rsplit_once('.')?;
    let id = stem.strip_suffix("_2K").or_else(|| stem.strip_suffix("_4K")).unwrap_or(stem);
    if id.len() != 32 || !id.bytes().all(|c| c.is_ascii_hexdigit())
        || !matches!(extension, "png" | "jpg" | "jpeg" | "webp" | "mp4" | "webm" | "mov") {
        return None;
    }
    Some(filename)
}

#[cfg(test)]
mod cached_media_regressions {
    use super::*;
    #[test]
    fn cached_media_route_rejects_paths_and_control_files() {
        assert!(cached_media_name("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.mp4").is_some());
        assert!(cached_media_name("c14431778c5ba20a07c61802a12dfc71_2K.jpg").is_some());
        assert!(cached_media_name("c14431778c5ba20a07c61802a12dfc71_4K.png").is_some());
        assert!(cached_media_name("c14431778c5ba20a07c61802a12dfc71_4K.mp4").is_some());
        assert!(cached_media_name("../aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.jpg").is_none());
        assert!(cached_media_name("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa_1K.jpg").is_none());
        assert!(cached_media_name("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa_2K_more.jpg").is_none());
        assert!(cached_media_name("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa_2k.jpg").is_none());
        assert!(cached_media_name("control-00000000-0000-0000-0000-000000000001-0.json").is_none());
    }
}


#[cfg(test)]
mod project_control_contract {
    use super::*;
    use base64::Engine;

    fn encoded(value: serde_json::Value) -> String {
        base64::engine::general_purpose::STANDARD.encode(serde_json::to_vec(&value).unwrap())
    }

    #[test]
    fn control_model_routes_without_management_registration() {
        let route = handle_model_route(br#"{"RequestedModel":"gflow-project-control"}"#).unwrap();
        let result: serde_json::Value = serde_json::from_slice(&route).unwrap();
        assert_eq!(result["result"]["Handled"], true);
        assert_eq!(project_control_model()["ID"], PROJECT_CONTROL_MODEL);
        assert_eq!(project_control_model()["SupportedGenerationMethods"], serde_json::json!(["chat"]));
    }

    #[test]
    fn project_binding_survives_host_normalization() {
        let request = serde_json::json!({
            "Payload": encoded(serde_json::json!({"model":"old","messages":[]})),
            "OriginalRequest": encoded(serde_json::json!({
                "gflow_workspace_id":"workspace", "gflow_project_id":"flow",
                "gflow_instance_id":"instance"
            })), "Model":"gflow-nano-banana-2-lite"
        });
        let body = executor_body(&request).unwrap();
        assert_eq!(body["gflow_project_id"], "flow");
        assert_eq!(body["gflow_workspace_id"], "workspace");
        assert_eq!(body["gflow_instance_id"], "instance");
        assert_eq!(body["model"], "gflow-nano-banana-2-lite");
    }

    #[test]
    fn conflicting_binding_is_rejected_before_worker() {
        let request = serde_json::json!({
            "Payload": encoded(serde_json::json!({"gflow_project_id":"wrong"})),
            "OriginalRequest": encoded(serde_json::json!({"gflow_project_id":"expected"}))
        });
        assert!(executor_body(&request).is_err());
    }

    #[test]
    fn control_standard_message_is_forwarded_unchanged() {
        let body = serde_json::json!({"model":PROJECT_CONTROL_MODEL,"stream":false,
            "messages":[{"role":"user","content":"{\"version\":1,\"op\":\"capabilities\"}"}]});
        assert_eq!(executor_body(&serde_json::json!({"OriginalRequest":encoded(body.clone())})).unwrap(), body);
    }
}

#[cfg(test)]
mod stream_abi_regressions {
    use super::*;
    use base64::Engine;
    use std::sync::{Arc, Condvar, mpsc};
    use std::time::{Duration, Instant};

    static ABI_TEST_LOCK: Mutex<()> = Mutex::new(());

    #[derive(Default)]
    struct State {
        rpc_returned: bool,
        cancelled: bool,
        emit_entered: bool,
        emits: usize,
        media_bytes: usize,
        closes: Vec<String>,
        reject_emit: bool,
        reject_close: bool,
    }

    #[derive(Default)]
    struct MockHost {
        state: Mutex<State>,
        changed: Condvar,
    }

    unsafe extern "C" fn host_free(ptr: *mut c_void, len: usize) {
        plugin_free(ptr, len);
    }

    unsafe extern "C" fn host_call(
        context: *mut c_void, method: *const c_char, request: *const u8,
        request_len: usize, response: *mut CliproxyBuffer,
    ) -> i32 {
        let host = &*(context as *const MockHost);
        let name = match CStr::from_ptr(method).to_str() { Ok(name) => name, Err(_) => return 1 };
        let value: serde_json::Value = match serde_json::from_slice(std::slice::from_raw_parts(request, request_len)) {
            Ok(value) => value, Err(_) => return 1,
        };
        let mut state = match host.state.lock() { Ok(state) => state, Err(_) => return 1 };
        let accepted = match name {
            "host.stream.emit" => {
                state.emit_entered = true;
                host.changed.notify_all();
                // This models the actual host's backpressure: no consumer is
                // available until executor.execute_stream has returned.
                while !state.rpc_returned && !state.cancelled {
                    let (next, timeout) = match host.changed.wait_timeout(state, Duration::from_secs(5)) {
                        Ok(value) => value, Err(_) => return 1,
                    };
                    state = next;
                    if timeout.timed_out() { return 1; }
                }
                state.emits += 1;
                let bytes = match value["payload"].as_str()
                    .and_then(|payload| base64::engine::general_purpose::STANDARD.decode(payload).ok()) {
                    Some(bytes) => bytes, None => return 1,
                };
                if bytes.len() > 1024 * 1024 { state.media_bytes = bytes.len(); }
                !state.cancelled && !state.reject_emit
            }
            "host.stream.close" => {
                state.closes.push(value["error"].as_str().unwrap_or("").to_string());
                state.cancelled = true;
                host.changed.notify_all();
                !state.reject_close
            }
            _ => return 1,
        };
        let output = serde_json::json!({"ok":accepted, "result":{}});
        abi::write_response(response, &serde_json::to_vec(&output).unwrap());
        0
    }

    fn fixture() -> WorkerManager {
        let root = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        let nonce = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_nanos();
        WorkerManager::new_fixture(
            root.join(".build/abi-stream-tests").join(nonce.to_string()),
            std::path::PathBuf::from(std::env::var("GFLOW_TEST_PYTHON").unwrap_or_else(|_| "python".into())),
            root.join("tests/worker_failure_fixture.py"),
        )
    }

    fn initialize(host: &Arc<MockHost>) -> (Box<CliproxyHostApi>, CliproxyPluginApi) {
        let table = Box::new(CliproxyHostApi {
            abi_version: ABI_VERSION, host_ctx: Arc::as_ptr(host) as *mut c_void,
            call: Some(host_call), free_buffer: Some(host_free),
        });
        let mut api = CliproxyPluginApi { abi_version:0, call:None, free_buffer:None, shutdown:None };
        assert_eq!(cliproxy_plugin_init(&*table, &mut api), 0);
        (table, api)
    }

    fn invoke_stream(api: &CliproxyPluginApi, worker: WorkerManager) -> (mpsc::Receiver<(i32, Vec<u8>)>, std::thread::JoinHandle<()>) {
        let callback = api.call.unwrap();
        let free = api.free_buffer.unwrap();
        let (send, receive) = mpsc::channel();
        let thread = std::thread::spawn(move || {
            TEST_STREAM_WORKER.with(|slot| *slot.borrow_mut() = Some(worker));
            let body = serde_json::json!({"model":"gflow-fixture", "stream":true, "abi_stream_fixture":true});
            let request = serde_json::to_vec(&serde_json::json!({
                "stream_id":"fixture-stream",
                "Payload":base64::engine::general_purpose::STANDARD.encode(serde_json::to_vec(&body).unwrap()),
            })).unwrap();
            let method = std::ffi::CString::new("executor.execute_stream").unwrap();
            let mut response = CliproxyBuffer { ptr:std::ptr::null_mut(), len:0 };
            let status = unsafe { callback(method.as_ptr(), request.as_ptr(), request.len(), &mut response) };
            let bytes = if response.ptr.is_null() { Vec::new() } else {
                let bytes = unsafe { std::slice::from_raw_parts(response.ptr, response.len).to_vec() };
                unsafe { free(response.ptr.cast(), response.len); }
                bytes
            };
            TEST_STREAM_WORKER.with(|slot| *slot.borrow_mut() = None);
            let _ = send.send((status, bytes));
        });
        (receive, thread)
    }

    fn wait_for(host: &MockHost, predicate: impl Fn(&State) -> bool) -> bool {
        let deadline = Instant::now() + Duration::from_secs(10);
        let mut state = host.state.lock().unwrap();
        while !predicate(&state) {
            let remaining = deadline.saturating_duration_since(Instant::now());
            if remaining.is_zero() { return false; }
            let (next, timeout) = host.changed.wait_timeout(state, remaining).unwrap();
            state = next;
            if timeout.timed_out() && !predicate(&state) { return false; }
        }
        true
    }

    #[test]
    fn executor_returns_before_host_consumes_then_delivers_many_events_and_large_media() {
        let _serial = ABI_TEST_LOCK.lock().unwrap();
        let host = Arc::new(MockHost::default());
        let (_table, api) = initialize(&host);
        let (receive, invocation) = invoke_stream(&api, fixture());
        let early = receive.recv_timeout(Duration::from_secs(1));
        let immediate = early.is_ok();
        {
            let mut state = host.state.lock().unwrap();
            if immediate { state.rpc_returned = true; } else { state.cancelled = true; }
            host.changed.notify_all();
        }
        let (status, response) = early.unwrap_or_else(|_| receive.recv_timeout(Duration::from_secs(5)).unwrap());
        invocation.join().unwrap();
        let closed = wait_for(&host, |state| !state.closes.is_empty());
        let state = host.state.lock().unwrap();
        let emits = state.emits;
        let media_bytes = state.media_bytes;
        let clean_close = state.closes.first().is_some_and(String::is_empty);
        drop(state);
        unsafe { api.shutdown.unwrap()(); }
        assert!(immediate, "ABI waited for host consumption instead of returning headers");
        assert_eq!(status, 0);
        let response: serde_json::Value = serde_json::from_slice(&response).unwrap();
        assert_eq!(response["result"]["headers"]["content-type"][0], "text/event-stream");
        assert!(closed);
        assert_eq!(emits, 49);
        assert!(media_bytes > 5 * 1024 * 1024);
        assert!(clean_close);
        assert!(stream_threads().lock().unwrap().tasks.is_empty());
    }

    #[test]
    fn rejected_host_emit_closes_with_error_instead_of_silently_succeeding() {
        let _serial = ABI_TEST_LOCK.lock().unwrap();
        let host = Arc::new(MockHost::default());
        {
            let mut state = host.state.lock().unwrap();
            state.rpc_returned = true;
            state.reject_emit = true;
        }
        let (_table, api) = initialize(&host);
        let (receive, invocation) = invoke_stream(&api, fixture());
        assert_eq!(receive.recv_timeout(Duration::from_secs(1)).unwrap().0, 0);
        invocation.join().unwrap();
        assert!(wait_for(&host, |state| !state.closes.is_empty()));
        let state = host.state.lock().unwrap();
        let close_error = state.closes[0].clone();
        let emits = state.emits;
        drop(state);
        unsafe { api.shutdown.unwrap()(); }
        assert_eq!(emits, 1);
        assert!(close_error.contains("host.stream.emit callback was rejected"));
        assert!(stream_threads().lock().unwrap().tasks.is_empty());
    }

    #[test]
    fn shutdown_closes_backpressured_host_before_joining_all_stream_threads() {
        let _serial = ABI_TEST_LOCK.lock().unwrap();
        let host = Arc::new(MockHost::default());
        let (_table, api) = initialize(&host);
        let (receive, invocation) = invoke_stream(&api, fixture());
        assert_eq!(receive.recv_timeout(Duration::from_secs(1)).unwrap().0, 0);
        invocation.join().unwrap();
        assert!(wait_for(&host, |state| state.emit_entered));
        let started = Instant::now();
        unsafe { api.shutdown.unwrap()(); }
        assert!(started.elapsed() < Duration::from_secs(5));
        assert!(stream_threads().lock().unwrap().tasks.is_empty());
        let callbacks = {
            let state = host.state.lock().unwrap();
            assert!(state.closes.iter().any(|error| error.contains("shutting down")));
            (state.emits, state.closes.len())
        };
        std::thread::sleep(Duration::from_millis(30));
        let state = host.state.lock().unwrap();
        assert_eq!((state.emits, state.closes.len()), callbacks);
    }

    #[test]
    fn callback_receipt_rejection_is_an_error() {
        let _serial = ABI_TEST_LOCK.lock().unwrap();
        let host = Arc::new(MockHost::default());
        host.state.lock().unwrap().reject_close = true;
        let (_table, api) = initialize(&host);
        assert!(close_host_stream("fixture-stream", "").unwrap_err().contains("was rejected"));
        host.state.lock().unwrap().reject_close = false;
        unsafe { api.shutdown.unwrap()(); }
    }
}
