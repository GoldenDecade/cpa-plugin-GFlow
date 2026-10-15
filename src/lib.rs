mod abi;
mod worker;

use std::ffi::{c_char, c_void, CStr};
use std::path::{Path, PathBuf};
use std::sync::OnceLock;
use abi::{CliproxyBuffer, CliproxyHostApi, CliproxyPluginApi, ABI_VERSION};
use worker::WorkerManager;

static WORKER: OnceLock<WorkerManager> = OnceLock::new();

fn get_worker() -> &'static WorkerManager {
    WORKER.get_or_init(|| {
        let base = PathBuf::from(r"D:\zuhui\EasyCLIProxyAPI-main\EasyCLIProxyAPI-main\cpa-plugin-GFlow");
        let data_dir = base.join("data");
        let worker_script = base.join("python").join("worker.py");
        WorkerManager::new(data_dir, worker_script)
    })
}

const MANAGE_HTML: &str = include_str!("../static/manage.html");

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

fn handle_register(_req: &[u8]) -> Result<Vec<u8>, String> {
    let reg = serde_json::json!({
        "ok": true,
        "result": {
            "schema_version": 6,
            "metadata": {
                "Name": "GFlow",
                "Version": "0.1.0",
                "Author": "daodeqing",
                "Description": "Google Flow (Veo & Nano Banana) 模型接入与多账号池管理插件",
                "GitHubRepository": "https://github.com/daodeqing/cpa-plugin-GFlow",
                "Logo": "https://raw.githubusercontent.com/daodeqing/cpa-plugin-GFlow/main/assets/logo.png",
                "Homepage": "https://github.com/daodeqing/cpa-plugin-GFlow",
                "License": "MIT",
                "Tags": ["Model", "Video", "Image", "Google Flow", "Veo", "Nano Banana"],
                "ConfigFields": [
                    {
                        "Name": "python_path",
                        "Type": "string",
                        "Default": "",
                        "Description": "Python 可执行文件路径（留空自动使用插件内置或本机环境）"
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
    if !req.is_empty() {
        if let Ok(v) = serde_json::from_slice::<serde_json::Value>(req) {
            if let Some(config_yaml) = v.get("config_yaml").and_then(|c| c.as_str()) {
                // Parse python_path if specified
                for line in config_yaml.lines() {
                    let trimmed = line.trim();
                    if trimmed.starts_with("python_path:") {
                        let val = trimmed["python_path:".len()..].trim().trim_matches('"').trim_matches('\x27');
                        if !val.is_empty() {
                            get_worker().set_custom_python(val.to_string());
                        }
                    }
                }
            }
        }
    }
    handle_register(req)
}

fn handle_model_static(_req: &[u8]) -> Result<Vec<u8>, String> {
    let worker_models = get_worker().execute("list_models", serde_json::json!({})).unwrap_or(serde_json::json!({}));
    let mut models_list = Vec::new();

    if let Some(arr) = worker_models.get("models").and_then(|m| m.as_array()) {
        for m in arr {
            let id = m.get("id").and_then(|s| s.as_str()).unwrap_or("");
            let desc = m.get("description").and_then(|s| s.as_str()).unwrap_or("");
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
            ("gflow-gemini-3.1-flash-image-landscape", "Nano Banana 2.1 (16:9 横屏)"),
            ("gflow-gemini-3.1-flash-image-portrait", "Nano Banana 2.1 (9:16 竖屏)"),
            ("gflow-gemini-3.1-flash-image-square", "Nano Banana 2.1 (1:1 方图)"),
            ("gflow-veo-3.1-fast-8s-landscape", "Veo 3.1 Fast (8s 横屏视频)"),
            ("gflow-veo-3.1-fast-8s-portrait", "Veo 3.1 Fast (8s 竖屏视频)"),
            ("gflow-veo-3.1-lite", "Veo 3.1 Lite (8s 横屏视频)"),
            ("gflow-omni-1.1-flash", "Omni 1.1 Flash (图生视频/参考图)"),
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
        || requested_model.starts_with("veo-")
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

fn handle_executor_execute(req: &[u8]) -> Result<Vec<u8>, String> {
    use base64::Engine;
    let req_val: serde_json::Value = serde_json::from_slice(req).map_err(|e| e.to_string())?;

    // Extract request body (Payload or OriginalRequest)
    let body_bytes = if let Some(p) = req_val.get("Payload").and_then(|s| s.as_str()) {
        base64::engine::general_purpose::STANDARD.decode(p).unwrap_or_default()
    } else if let Some(orig) = req_val.get("OriginalRequest").and_then(|s| s.as_str()) {
        base64::engine::general_purpose::STANDARD.decode(orig).unwrap_or_default()
    } else {
        Vec::new()
    };

    let mut body_json: serde_json::Value = serde_json::from_slice(&body_bytes).unwrap_or_else(|_| serde_json::json!({}));
    if let Some(m) = req_val.get("Model").and_then(|s| s.as_str()) {
        if !m.is_empty() {
            body_json["model"] = serde_json::Value::String(m.to_string());
        }
    }

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
    use base64::Engine;
    let req_val: serde_json::Value = serde_json::from_slice(req).map_err(|e| e.to_string())?;

    let stream_id = req_val.get("stream_id").and_then(|s| s.as_str()).unwrap_or("");
    let body_bytes = if let Some(p) = req_val.get("Payload").and_then(|s| s.as_str()) {
        base64::engine::general_purpose::STANDARD.decode(p).unwrap_or_default()
    } else if let Some(orig) = req_val.get("OriginalRequest").and_then(|s| s.as_str()) {
        base64::engine::general_purpose::STANDARD.decode(orig).unwrap_or_default()
    } else {
        Vec::new()
    };

    let mut body_json: serde_json::Value = serde_json::from_slice(&body_bytes).unwrap_or_else(|_| serde_json::json!({}));
    if let Some(m) = req_val.get("Model").and_then(|s| s.as_str()) {
        if !m.is_empty() {
            body_json["model"] = serde_json::Value::String(m.to_string());
        }
    }
    body_json["stream"] = serde_json::Value::Bool(true);

    if !stream_id.is_empty() {
        let sid = stream_id.to_string();
        get_worker().execute_stream(body_json, |chunk| {
            let b64 = base64::engine::general_purpose::STANDARD.encode(chunk.as_bytes());
            let emit_req = serde_json::json!({
                "stream_id": sid,
                "payload": b64
            });
            if let Ok(emit_bytes) = serde_json::to_vec(&emit_req) {
                abi::call_host("host.stream.emit", &emit_bytes);
            }
            Ok(())
        })?;

        let close_req = serde_json::json!({
            "stream_id": sid,
            "error": ""
        });
        if let Ok(close_bytes) = serde_json::to_vec(&close_req) {
            abi::call_host("host.stream.close", &close_bytes);
        }
    }

    let out = serde_json::json!({
        "ok": true,
        "result": {
            "headers": {
                "content-type": ["text/event-stream"]
            },
            "chunks": []
        }
    });
    serde_json::to_vec(&out).map_err(|e| e.to_string())
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
                    "Path": "/tmp",
                    "Description": "GFlow 本地素材文件下载服务"
                }
            ],
            "Routes": [
                { "Method": "GET", "Path": "/plugins/gflow/api/status" },
                { "Method": "GET", "Path": "/plugins/gflow/api/models" },
                { "Method": "GET", "Path": "/plugins/gflow/api/tokens" },
                { "Method": "POST", "Path": "/plugins/gflow/api/tokens" },
                { "Method": "PUT", "Path": "/plugins/gflow/api/tokens" },
                { "Method": "DELETE", "Path": "/plugins/gflow/api/tokens" },
                { "Method": "POST", "Path": "/plugins/gflow/api/refresh" },
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

    // 1. Serve HTML dashboard resource
    if path.contains("/plugins/gflow/manage") {
        let b64 = base64::engine::general_purpose::STANDARD.encode(MANAGE_HTML.as_bytes());
        let out = serde_json::json!({
            "ok": true,
            "result": {
                "StatusCode": 200,
                "Headers": {
                    "content-type": ["text/html; charset=utf-8"],
                    "cache-control": ["no-cache"]
                },
                "Body": b64
            }
        });
        return serde_json::to_vec(&out).map_err(|e| e.to_string());
    }

    // 2. Serve cached media asset resource: /v0/resource/plugins/gflow/tmp/<filename>
    if path.contains("/plugins/gflow/tmp/") {
        let filename = path.split("/tmp/").last().unwrap_or("").trim();
        // sanitize filename to avoid directory traversal
        let clean_filename = Path::new(filename).file_name().and_then(|s| s.to_str()).unwrap_or("");
        if clean_filename.is_empty() {
            return Ok(management_error(404, "File not found"));
        }

        let tmp_path = PathBuf::from(r"D:\zuhui\EasyCLIProxyAPI-main\EasyCLIProxyAPI-main\cpa-plugin-GFlow\data\tmp").join(clean_filename);
        if !tmp_path.exists() {
            return Ok(management_error(404, "File not found"));
        }

        let content_type = if clean_filename.ends_with(".mp4") {
            "video/mp4"
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
                        "accept-ranges": ["bytes"],
                        "cache-control": ["public, max-age=86400"]
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
        get_worker().execute("status", serde_json::json!({}))
    } else if path.ends_with("/api/tokens") {
        match method {
            "GET" => get_worker().execute("list_tokens", serde_json::json!({})),
            "POST" => get_worker().execute("add_token", body_json),
            "PUT" => get_worker().execute("toggle_token", body_json),
            "DELETE" => get_worker().execute("delete_token", body_json),
            _ => Err("Method not allowed".to_string()),
        }
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
        Ok(data) => {
            let json_bytes = serde_json::to_vec(&data).unwrap_or_default();
            let b64 = base64::engine::general_purpose::STANDARD.encode(&json_bytes);
            let out = serde_json::json!({
                "ok": true,
                "result": {
                    "StatusCode": 200,
                    "Headers": {
                        "content-type": ["application/json; charset=utf-8"]
                    },
                    "Body": b64
                }
            });
            serde_json::to_vec(&out).map_err(|e| e.to_string())
        }
        Err(e) => Ok(management_error(500, &e)),
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
