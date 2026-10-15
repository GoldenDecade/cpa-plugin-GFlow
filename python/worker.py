# -*- coding: utf-8 -*-
"""
GFlow worker process:
Communicates with the GFlow native plugin via standard input/output (line-delimited JSON).
Executes Flow2API tasks: token management, quota inquiry, configuration, and media generation.
"""

import asyncio
import base64
import json
import os
import secrets
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional

# Reconfigure standard streams to UTF-8
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")

# Save dedicated RPC stdout before redirecting sys.stdout to sys.stderr
_rpc_stdout = sys.stdout
sys.stdout = sys.stderr

# Ensure flow2api package is in sys.path
base_dir = Path(__file__).resolve().parent
flow_pkg = base_dir / "flow2api"
if str(flow_pkg) not in sys.path:
    sys.path.insert(0, str(flow_pkg))

# Windows event loop setup
if os.name == "nt":
    try:
        policy = getattr(asyncio, "WindowsProactorEventLoopPolicy", None)
        if policy and not isinstance(asyncio.get_event_loop_policy(), policy):
            asyncio.set_event_loop_policy(policy())
    except Exception:
        pass


def get_gflow_model_catalog() -> List[Dict[str, Any]]:
    models = []

    # 1. 基础模型（保留客户端可调用的函数）
    base_models = [
        ("gflow-nano-banana-pro", "nano-banana-pro", "image", "Nano Banana Pro (自适应/默认)", "Google Flow 图片生成 - Nano Banana Pro (GEM_PIX_2) 基础函数"),
        ("gflow-nano-banana-2-lite", "nano-banana-2-lite", "image", "Nano Banana 2 Lite (自适应/默认)", "Google Flow 图片生成 - Nano Banana 2 Lite (HARBOR_SEAL) 基础函数"),
        ("gflow-nano-banana-2.1", "nano-banana-2.1", "image", "Nano Banana 2.1 (自适应/默认)", "Google Flow 图片生成 - Nano Banana 2.1 (BELUGA) 基础函数"),
        ("gflow-omni-1.1-flash", "omni-1.1-flash", "video", "Omni 1.1 Flash (默认 8s 横屏)", "Google Flow 视频生成 - Omni 1.1 Flash 基础函数"),
        ("gflow-veo-3.1-lite", "veo-3.1-lite", "video", "Veo 3.1 - Lite (默认 8s 横屏)", "Google Flow 视频生成 - Veo 3.1 Lite 基础函数"),
        ("gflow-veo-3.1-fast", "veo-3.1-fast", "video", "Veo 3.1 - Fast (默认 8s 横屏)", "Google Flow 视频生成 - Veo 3.1 Fast 基础函数"),
        ("gflow-veo-3.1-quality", "veo-3.1-quality", "video", "Veo 3.1 - Quality (默认 8s 横屏)", "Google Flow 视频生成 - Veo 3.1 Quality 基础函数"),
    ]
    for mid, orig_id, mtype, dname, desc in base_models:
        models.append({
            "id": mid,
            "original_id": orig_id,
            "type": mtype,
            "display_name": dname,
            "description": desc,
        })

    # 2. 图片笛卡尔积组合: 3 基础模型 x 5 比例 x 3 分辨率 = 45 变体
    image_bases = [
        ("nano-banana-pro", "Nano Banana Pro"),
        ("nano-banana-2-lite", "Nano Banana 2 Lite"),
        ("nano-banana-2.1", "Nano Banana 2.1"),
    ]
    ratios = [
        ("landscape", "16:9 横屏"),
        ("portrait", "9:16 竖屏"),
        ("square", "1:1 方图"),
        ("four-three", "4:3 横屏"),
        ("three-four", "3:4 竖屏"),
    ]
    sizes = [
        ("", "标准 1K"),
        ("-2k", "2K 放大"),
        ("-4k", "4K 放大"),
    ]
    for b_slug, b_name in image_bases:
        for r_slug, r_name in ratios:
            for s_slug, s_name in sizes:
                mid = f"gflow-{b_slug}-{r_slug}{s_slug}"
                orig = f"{b_slug}-{r_slug}{s_slug}"
                dname = f"{b_name} ({r_name} {s_name})".strip()
                desc = f"Google Flow 图片生成 - {b_name} {r_name} {s_name}".strip()
                models.append({
                    "id": mid,
                    "original_id": orig,
                    "type": "image",
                    "display_name": dname,
                    "description": desc,
                })

    # 3. 视频笛卡尔积组合: Veo 3.1 系列 (4s, 6s, 8s x 16:9, 9:16) + Omni 1.1 Flash (4s, 6s, 8s, 10s x 16:9, 9:16)
    veo_families = [
        ("veo-3.1-fast", "Veo 3.1 Fast"),
        ("veo-3.1-lite", "Veo 3.1 Lite"),
        ("veo-3.1-quality", "Veo 3.1 Quality"),
    ]
    durations = [4, 6, 8]
    v_ratios = [("landscape", "16:9 横屏"), ("portrait", "9:16 竖屏")]
    for v_slug, v_name in veo_families:
        for d in durations:
            for vr_slug, vr_name in v_ratios:
                mid = f"gflow-{v_slug}-{d}s-{vr_slug}"
                orig = f"{v_slug}-{d}s-{vr_slug}"
                dname = f"{v_name} ({d}s {vr_name})"
                desc = f"Google Flow 视频生成 - {v_name} {d}秒 {vr_name}"
                models.append({
                    "id": mid,
                    "original_id": orig,
                    "type": "video",
                    "display_name": dname,
                    "description": desc,
                })

    omni_durations = [4, 6, 8, 10]
    for d in omni_durations:
        for vr_slug, vr_name in v_ratios:
            mid = f"gflow-omni-1.1-flash-{d}s-{vr_slug}"
            orig = f"omni-1.1-flash-{d}s-{vr_slug}"
            dname = f"Omni 1.1 Flash ({d}s {vr_name})"
            desc = f"Google Flow 视频生成 - Omni 1.1 Flash {d}秒 {vr_name}"
            models.append({
                "id": mid,
                "original_id": orig,
                "type": "video",
                "display_name": dname,
                "description": desc,
            })

    return models

class GFlowService:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.tmp_dir = self.data_dir / "tmp"
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = str(self.data_dir / "flow.db")

        self.db = None
        self.proxy_manager = None
        self.flow_client = None
        self.token_manager = None
        self.concurrency_manager = None
        self.load_balancer = None
        self.generation_handler = None
        self.initialized = False

    async def initialize(self):
        if self.initialized:
            return

        from src.core.config import config
        from src.core.database import Database
        from src.services.proxy_manager import ProxyManager
        from src.services.flow_client import FlowClient
        from src.services.token_manager import TokenManager
        from src.services.concurrency_manager import ConcurrencyManager
        from src.services.load_balancer import LoadBalancer
        from src.services.generation_handler import GenerationHandler
        from src.api import routes

        self.db = Database(self.db_path)
        is_first = not self.db.db_exists()
        await self.db.init_db()

        raw_cfg = config.get_raw_config()
        if is_first:
            await self.db.init_config_from_toml(raw_cfg, is_first_startup=True)
        else:
            await self.db.check_and_migrate_db(raw_cfg)

        await self.db.reload_config_to_memory()

        self.proxy_manager = ProxyManager(self.db)
        self.flow_client = FlowClient(self.proxy_manager, self.db)
        self.token_manager = TokenManager(self.db, self.flow_client)
        self.concurrency_manager = ConcurrencyManager()
        self.load_balancer = LoadBalancer(self.token_manager, self.concurrency_manager)
        self.generation_handler = GenerationHandler(
            self.flow_client,
            self.token_manager,
            self.load_balancer,
            self.db,
            self.concurrency_manager,
            self.proxy_manager,
        )

        # Set cache dir to our local tmp_dir
        self.generation_handler.file_cache.cache_dir = self.tmp_dir
        self.generation_handler.file_cache.default_timeout = config.cache_timeout

        tokens = await self.token_manager.get_all_tokens()
        await self.concurrency_manager.initialize(tokens)

        # Register handler into routes module so normalization works
        routes.set_generation_handler(self.generation_handler)

        self.initialized = True
        sys.stderr.write(f"[GFlowService] Initialized. DB={self.db_path}, Accounts={len(tokens)}\n")
        sys.stderr.flush()

    def send_line(self, data: Dict[str, Any]):
        out = json.dumps(data, ensure_ascii=False)
        _rpc_stdout.write(out + "\n")
        _rpc_stdout.flush()

    async def handle_ui_nonce(self, _params: Dict[str, Any]) -> Dict[str, Any]:
        return {"nonce": secrets.token_urlsafe(32)}

    async def handle_ping(self, _params: Dict[str, Any]) -> Dict[str, Any]:
        return {"pong": True}

    async def handle_status(self, _params: Dict[str, Any]) -> Dict[str, Any]:
        await self.initialize()
        tokens = await self.token_manager.get_all_tokens()
        active = [t for t in tokens if t.is_active and not t.ban_reason]
        total_credits = sum(getattr(t, "credits", 0) or 0 for t in active)
        return {
            "initialized": self.initialized,
            "python": sys.executable,
            "version": sys.version.split()[0],
            "database_path": self.db_path,
            "cache_dir": str(self.tmp_dir),
            "total_tokens": len(tokens),
            "active_tokens": len(active),
            "total_credits": total_credits,
        }

    async def handle_list_tokens(self, _params: Dict[str, Any]) -> Dict[str, Any]:
        await self.initialize()
        tokens = await self.token_manager.get_all_tokens()
        items = []
        for t in tokens:
            email = t.email or ""
            if "@" in email:
                user, dom = email.split("@", 1)
                masked = (user[0] + "***" if len(user) > 0 else "***") + "@" + dom
            else:
                masked = email[:2] + "***" if len(email) > 2 else "***"

            items.append({
                "id": t.id,
                "email": masked,
                "name": t.name or "",
                "remark": t.remark or "",
                "is_active": t.is_active,
                "credits": t.credits,
                "user_paygate_tier": t.user_paygate_tier or "FREE",
                "current_project_id": t.current_project_id or "",
                "current_project_name": t.current_project_name or "",
                "image_enabled": t.image_enabled,
                "video_enabled": t.video_enabled,
                "ban_reason": t.ban_reason,
                "banned_at": t.banned_at.isoformat() if t.banned_at else None,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "last_used_at": t.last_used_at.isoformat() if t.last_used_at else None,
                "use_count": t.use_count,
            })
        return {"tokens": items, "total": len(items)}

    async def handle_add_token(self, params: Dict[str, Any]) -> Dict[str, Any]:
        await self.initialize()
        from credentials import normalize_account_input
        st, google_cookies = normalize_account_input(params.get("st"), params.get("google_cookies"))
        project_id = params.get("project_id", "").strip() or None
        project_name = params.get("project_name", "").strip() or None
        remark = params.get("remark", "").strip() or None
        captcha_proxy = params.get("captcha_proxy_url", "").strip() or None

        token_st = st
        if not token_st and not google_cookies:
            raise ValueError("Cookie 或 st 不能为空")

        new_token = await self.token_manager.add_token(
            st=token_st,
            project_id=project_id,
            project_name=project_name,
            remark=remark,
            captcha_proxy_url=captcha_proxy,
            google_cookies=google_cookies or None,
        )
        if google_cookies:
            await self.token_manager.update_token(
                new_token.id,
                google_cookies=google_cookies,
            )

        try:
            await self.token_manager.refresh_credits(new_token.id)
        except Exception as e:
            sys.stderr.write(f"[GFlowService] Warning: credit refresh failed on add: {e}\n")

        return {"success": True, "token_id": new_token.id}

    async def handle_extension_sync(self, params: Dict[str, Any]) -> Dict[str, Any]:
        from extension_sync import sync_extension_account
        return await sync_extension_account(self, params)

    async def handle_delete_token(self, params: Dict[str, Any]) -> Dict[str, Any]:
        await self.initialize()
        tid = params.get("token_id")
        if not tid:
            raise ValueError("token_id 必须指定")
        await self.token_manager.delete_token(int(tid))
        return {"success": True}

    async def handle_toggle_token(self, params: Dict[str, Any]) -> Dict[str, Any]:
        await self.initialize()
        tid = int(params.get("token_id", 0))
        enabled = bool(params.get("enabled", True))
        if enabled:
            await self.token_manager.enable_token(tid)
        else:
            await self.token_manager.disable_token(tid)
        return {"success": True, "token_id": tid, "is_active": enabled}

    async def handle_refresh_credits(self, params: Dict[str, Any]) -> Dict[str, Any]:
        await self.initialize()
        tid = int(params.get("token_id", 0))
        res = await self.token_manager.refresh_credits(tid)
        return {"success": True, "credits": getattr(res, "credits", 0) if res else 0}

    async def handle_get_config(self, _params: Dict[str, Any]) -> Dict[str, Any]:
        await self.initialize()
        cap_cfg = await self.db.get_captcha_config()
        proxy_cfg = await self.db.get_proxy_config()
        call_cfg = await self.db.get_call_logic_config()
        cache_cfg = await self.db.get_cache_config()

        return {
            "captcha": {
                "method": cap_cfg.captcha_method,
                "yescaptcha_api_key": cap_cfg.yescaptcha_api_key or "",
                "yescaptcha_base_url": cap_cfg.yescaptcha_base_url or "",
                "twocaptcha_api_key": cap_cfg.twocaptcha_api_key or "",
                "capsolver_api_key": cap_cfg.capsolver_api_key or "",
            },
            "proxy": {
                "enabled": proxy_cfg.enabled if proxy_cfg else False,
                "url": getattr(proxy_cfg, "proxy_url", "") if proxy_cfg else "",
            },
            "call_logic": {
                "mode": getattr(call_cfg, "call_mode", "polling") if call_cfg else "polling",
            },
            "cache": {
                "timeout": cache_cfg.cache_timeout if cache_cfg else 7200,
            }
        }

    async def handle_update_config(self, params: Dict[str, Any]) -> Dict[str, Any]:
        await self.initialize()
        if "captcha" in params:
            c = params["captcha"]
            await self.db.update_captcha_config(
                captcha_method=c.get("method"),
                yescaptcha_api_key=c.get("yescaptcha_api_key"),
                yescaptcha_base_url=c.get("yescaptcha_base_url"),
                twocaptcha_api_key=c.get("twocaptcha_api_key"),
                capsolver_api_key=c.get("capsolver_api_key"),
            )
        if "proxy" in params:
            p = params["proxy"]
            await self.db.update_proxy_config(
                enabled=p.get("enabled"),
                url=p.get("url"),
            )
        return {"success": True}

    async def handle_list_models(self, _params: Dict[str, Any]) -> Dict[str, Any]:
        return {"models": get_gflow_model_catalog()}

    async def handle_chat_completion(self, req_id: str, params: Dict[str, Any]):
        await self.initialize()
        from src.api.routes import (
            ChatCompletionRequest,
            _normalize_openai_request,
            _collect_non_stream_result,
            _parse_handler_result,
            _iterate_openai_stream,
        )

        model_raw = params.get("model", "")
        if model_raw.startswith("gflow-"):
            actual_model = model_raw[len("gflow-"):]
        else:
            actual_model = model_raw

        params_clean = dict(params)
        params_clean["model"] = actual_model

        active_tokens = await self.token_manager.get_active_tokens()
        if not active_tokens:
            err_msg = "没有可用的 GFlow 账号，请先在 EasyCPA 插件控制台 (GFlow) 导入或添加 Google Flow Cookie 账号"
            self.send_line({
                "id": req_id,
                "done": True,
                "error": {
                    "message": err_msg,
                    "type": "no_active_tokens",
                    "code": "gflow_empty_account_pool",
                    "status_code": 400,
                }
            })
            return

        is_stream = bool(params.get("stream", False))
        base_url_override = params.get("base_url_override", "/v0/resource/plugins/gflow")

        try:
            req_obj = ChatCompletionRequest(**params_clean)
            normalized = await _normalize_openai_request(req_obj)

            if is_stream:
                async for chunk in _iterate_openai_stream(normalized, base_url_override):
                    self.send_line({
                        "id": req_id,
                        "stream": True,
                        "chunk": chunk,
                    })
                self.send_line({
                    "id": req_id,
                    "stream": True,
                    "done": True,
                })
            else:
                raw_chunk = await _collect_non_stream_result(
                    normalized.model,
                    normalized.prompt,
                    normalized.images,
                    base_url_override=base_url_override,
                    video_media_id=normalized.video_media_id,
                )
                payload = _parse_handler_result(raw_chunk)
                self.send_line({
                    "id": req_id,
                    "done": True,
                    "result": payload,
                })
        except Exception as e:
            tb = traceback.format_exc()
            sys.stderr.write(f"[GFlowService] Generation error: {tb}\n")
            self.send_line({
                "id": req_id,
                "done": True,
                "error": {
                    "message": str(e),
                    "type": "generation_error",
                    "traceback": tb,
                    "status_code": 500,
                }
            })


async def main():
    if len(sys.argv) > 1:
        data_dir = Path(sys.argv[1])
    else:
        data_dir = Path(__file__).resolve().parent.parent / "data"

    service = GFlowService(data_dir)
    service.send_line({"ready": True, "pid": os.getpid(), "data_dir": str(data_dir)})

    loop = asyncio.get_running_loop()

    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        if not line:
            break
        line = line.strip()
        if not line:
            continue

        try:
            msg = json.loads(line)
        except Exception as e:
            sys.stderr.write(f"[GFlowService] Invalid JSON: {e}\n")
            continue

        req_id = msg.get("id", "")
        cmd = msg.get("cmd", "")
        params = msg.get("params", {})

        if cmd == "shutdown":
            service.send_line({"id": req_id, "done": True, "result": {"shutdown": True}})
            break

        if cmd == "chat_completion":
            asyncio.create_task(service.handle_chat_completion(req_id, params))
            continue

        handler = getattr(service, f"handle_{cmd}", None)
        if handler:
            try:
                res = await handler(params)
                service.send_line({"id": req_id, "done": True, "result": res})
            except Exception as e:
                tb = traceback.format_exc()
                sys.stderr.write(f"[GFlowService] Error in {cmd}: {tb}\n")
                service.send_line({"id": req_id, "done": True, "error": {"message": str(e), "traceback": tb}})
        else:
            service.send_line({"id": req_id, "done": True, "error": {"message": f"Unknown command: {cmd}"}})


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
