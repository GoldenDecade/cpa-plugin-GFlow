mod abi;
mod runtime;
mod worker;

use std::ffi::{c_char, c_void, CStr};
use std::sync::OnceLock;
use abi::{CliproxyBuffer, CliproxyHostApi, CliproxyPluginApi, ABI_VERSION};
use worker::WorkerManager;

static WORKER: OnceLock<WorkerManager> = OnceLock::new();

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
                "Description": "Google Flow (Veo & Nano Banana) 模型接入与多账号池管理插件",
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
        let stream_result = get_worker().execute_stream(body_json, |chunk| {
            let b64 = base64::engine::general_purpose::STANDARD.encode(chunk.as_bytes());
            let emit_req = serde_json::json!({
                "stream_id": sid,
                "payload": b64
            });
            if let Ok(emit_bytes) = serde_json::to_vec(&emit_req) {
                abi::call_host("host.stream.emit", &emit_bytes);
            }
            Ok(())
        });

        let close_req = serde_json::json!({
            "stream_id": sid,
            "error": stream_result.as_ref().err().cloned().unwrap_or_default()
        });
        if let Ok(close_bytes) = serde_json::to_vec(&close_req) {
            abi::call_host("host.stream.close", &close_bytes);
        }
        stream_result?;
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

fn cached_media_name(filename: &str) -> Option<&str> {
    let (stem, extension) = filename.rsplit_once('.')?;
    if stem.len() != 32 || !stem.bytes().all(|c| c.is_ascii_hexdigit())
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
        assert!(cached_media_name("../aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.jpg").is_none());
        assert!(cached_media_name("control-00000000-0000-0000-0000-000000000001-0.json").is_none());
    }
}
