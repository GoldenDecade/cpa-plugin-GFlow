"""Model name resolver - converts simplified model names + generationConfig params to internal MODEL_CONFIG keys.

When upstream services (e.g. New API) send requests with a generic model name
along with generationConfig containing aspectRatio / imageSize, this module
resolves them to the specific internal model name used by flow2api.

Example:
    model = "gemini-3.0-pro-image"
    generationConfig.imageConfig.aspectRatio = "16:9"
    generationConfig.imageConfig.imageSize = "2k"
    → resolved to "gemini-3.0-pro-image-landscape-2k"
"""

import re
from io import BytesIO
from typing import Optional, Dict, Any, Tuple
from ..core.logger import debug_logger

# ──────────────────────────────────────────────
# 简化模型名 → 基础模型名前缀 的映射
# ──────────────────────────────────────────────
IMAGE_BASE_MODELS = {
    # Gemini 3.0 Pro (GEM_PIX_2)
   # Nano Banana Pro (GEM_PIX_2)
    "nano-banana-pro": "gemini-3.0-pro-image",
    "gemini-3.0-pro-image": "gemini-3.0-pro-image",
    # Nano Banana 2 Lite (HARBOR_SEAL)
    "nano-banana-2-lite": "gemini-3.1-flash-lite-image",
    "nano-banana-2.0-lite": "gemini-3.1-flash-lite-image",
    # Nano Banana 2.1 (BELEQA)
    "nano-banana-2.1": "gemini-3.1-flash-image",
    "nano-banana": "gemini-3.1-flash-image",
    # Nano Banana 2.1, with the existing Gemini 3.1 alias retained.
    "gemini-3.1-flash-image": "gemini-3.1-flash-image",
    "gemini-3.1-flash-lite-image": "gemini-3.1-flash-lite-image",
}

# ──────────────────────────────────────────────
# aspectRatio 转换映射
# 支持 Gemini 原生格式 ("16:9") 和内部格式 ("landscape")
# ──────────────────────────────────────────────
ASPECT_RATIO_MAP = {
    # Gemini 标准 ratio 格式
    "16:9": "landscape",
    "9:16": "portrait",
    "1:1": "square",
    "4:3": "four-three",
    "3:4": "three-four",
    # 英文名直接映射
    "landscape": "landscape",
    "portrait": "portrait",
    "square": "square",
    "four-three": "four-three",
    "three-four": "three-four",
    "four_three": "four-three",
    "three_four": "three-four",
    # 大写形式
    "LANDSCAPE": "landscape",
    "PORTRAIT": "portrait",
    "SQUARE": "square",
}

# 每个基础模型支持的 aspectRatio 列表
# 如果请求的 ratio 不在支持列表中，降级到默认值
MODEL_SUPPORTED_ASPECTS = {
    "gemini-3.0-pro-image": [
        "landscape",
        "portrait",
        "square",
        "four-three",
        "three-four",
    ],
    "gemini-3.1-flash-image": [
        "landscape",
        "portrait",
        "square",
        "four-three",
        "three-four",
    ],
    "gemini-3.1-flash-lite-image": [
        "landscape", "portrait", "square", "four-three", "three-four",
    ],
}

# 每个基础模型支持的 imageSize（分辨率）列表
MODEL_SUPPORTED_SIZES = {
    "gemini-3.0-pro-image": ["2k", "4k"],
    "gemini-3.1-flash-image": ["2k", "4k"],
    "gemini-3.1-flash-lite-image": ["2k", "4k"],
}

# imageSize 归一化映射
IMAGE_SIZE_MAP = {
    "1k": "1k",
    "1K": "1k",
    "2k": "2k",
    "2K": "2k",
    "4k": "4k",
    "4K": "4k",
    "1080p": "1080p",
    "1080P": "1080p",
    "": "",
}

# 默认 aspectRatio
DEFAULT_ASPECT = "landscape"

OPENAI_IMAGE_SIZE_RE = re.compile(r"^(?P<w>\d{2,5})\s*[xX]\s*(?P<h>\d{2,5})$")

# OpenAI 常见 quality → imageSize 映射
# - 这里的 imageSize 是 flow2api 的“放大档位”，并不等价于 OpenAI 的像素尺寸；
#   但可用作“画质/清晰度”的近似映射。
OPENAI_QUALITY_MAP = {
    "low": None,
    "standard": None,
    "medium": "2k",
    "high": "4k",
    "hd": "4k",
    "ultra": "4k",
}

# 用于把 OpenAI size（如 1024x1792）映射到最接近的 flow2api aspect 选项
ASPECT_RATIO_FLOAT_MAP = {
    "landscape": 16 / 9,
    "portrait": 9 / 16,
    "square": 1.0,
    "four-three": 4 / 3,
    "three-four": 3 / 4,
}


def _aspect_from_dimensions(
    width: int, height: int, *, video_mode: bool = False
) -> Optional[str]:
    if width <= 0 or height <= 0:
        return None

    ratio = width / height
    inferred = min(
        ASPECT_RATIO_FLOAT_MAP.items(),
        key=lambda item: abs(ratio - item[1]),
    )[0]

    if video_mode and inferred not in {"landscape", "portrait"}:
        return "portrait" if height > width else "landscape"
    return inferred


def _infer_aspect_ratio_from_images(
    images: Any,
    *,
    video_mode: bool = False,
) -> Optional[str]:
    if not isinstance(images, (list, tuple)):
        return None

    source_bytes = next(
        (
            bytes(item)
            for item in images
            if isinstance(item, (bytes, bytearray)) and item
        ),
        None,
    )
    if not source_bytes:
        return None

    try:
        from PIL import Image, ImageOps

        with Image.open(BytesIO(source_bytes)) as image:
            normalized = ImageOps.exif_transpose(image)
            width, height = normalized.size
    except Exception as exc:
        debug_logger.log_warning(
            f"[MODEL_RESOLVER] 参考图尺寸解析失败，跳过自动比例跟随: {exc}"
        )
        return None

    inferred = _aspect_from_dimensions(width, height, video_mode=video_mode)
    if inferred:
        debug_logger.log_info(
            f"[MODEL_RESOLVER] 未显式指定 aspectRatio，已按参考图尺寸自动推断: {width}x{height} -> {inferred}"
        )
    return inferred


# ──────────────────────────────────────────────
# 视频模型简化名映射
# ──────────────────────────────────────────────

VIDEO_MODERN_BASES = {
    "veo-3.1-fast": "veo-3.1-fast",
    "veo-3.1-lite": "veo-3.1-lite",
    "veo-3.1-quality": "veo-3.1-quality",
    "omni-1.1-flash": "omni-1.1-flash",
}

VIDEO_BASE_MODELS = {
    # T2V models
    "veo_3_1_t2v_fast": {
        "landscape": "veo_3_1_t2v_fast_landscape",
        "portrait": "veo_3_1_t2v_fast_portrait",
    },
    "veo_3_1_t2v_fast_4s": {
        "landscape": "veo_3_1_t2v_fast_4s",
        "portrait": "veo_3_1_t2v_fast_portrait_4s",
    },
    "veo_3_1_t2v_fast_6s": {
        "landscape": "veo_3_1_t2v_fast_6s",
        "portrait": "veo_3_1_t2v_fast_portrait_6s",
    },
    "veo_3_1_t2v_fast_8s": {
        "landscape": "veo_3_1_t2v_fast_8s",
        "portrait": "veo_3_1_t2v_fast_portrait_8s",
    },
    "veo_3_1_t2v_fast_ultra": {
        "landscape": "veo_3_1_t2v_fast_ultra",
        "portrait": "veo_3_1_t2v_fast_portrait_ultra",
    },
    "veo_3_1_t2v_fast_ultra_relaxed": {
        "landscape": "veo_3_1_t2v_fast_ultra_relaxed",
        "portrait": "veo_3_1_t2v_fast_portrait_ultra_relaxed",
    },
    "veo_3_1_t2v": {
        "landscape": "veo_3_1_t2v_landscape",
        "portrait": "veo_3_1_t2v_portrait",
    },
    "veo_3_1_t2v_4s": {
        "landscape": "veo_3_1_t2v_4s",
        "portrait": "veo_3_1_t2v_portrait_4s",
    },
    "veo_3_1_t2v_6s": {
        "landscape": "veo_3_1_t2v_6s",
        "portrait": "veo_3_1_t2v_portrait_6s",
    },
    "veo_3_1_t2v_8s": {
        "landscape": "veo_3_1_t2v_8s",
        "portrait": "veo_3_1_t2v_portrait_8s",
    },
    "veo_3_1_t2v_4s_4k": {
        "landscape": "veo_3_1_t2v_4s_4k",
        "portrait": "veo_3_1_t2v_portrait_4s_4k",
    },
    "veo_3_1_t2v_4s_1080p": {
        "landscape": "veo_3_1_t2v_4s_1080p",
        "portrait": "veo_3_1_t2v_portrait_4s_1080p",
    },
    "veo_3_1_t2v_6s_4k": {
        "landscape": "veo_3_1_t2v_6s_4k",
        "portrait": "veo_3_1_t2v_portrait_6s_4k",
    },
    "veo_3_1_t2v_6s_1080p": {
        "landscape": "veo_3_1_t2v_6s_1080p",
        "portrait": "veo_3_1_t2v_portrait_6s_1080p",
    },
    "veo_3_1_t2v_8s_4k": {
        "landscape": "veo_3_1_t2v_8s_4k",
        "portrait": "veo_3_1_t2v_portrait_8s_4k",
    },
    "veo_3_1_t2v_8s_1080p": {
        "landscape": "veo_3_1_t2v_8s_1080p",
        "portrait": "veo_3_1_t2v_portrait_8s_1080p",
    },
    "veo_3_1_t2v_4k": {
        "landscape": "veo_3_1_t2v_4k",
        "portrait": "veo_3_1_t2v_portrait_4k",
    },
    "veo_3_1_t2v_1080p": {
        "landscape": "veo_3_1_t2v_1080p",
        "portrait": "veo_3_1_t2v_portrait_1080p",
    },
    "veo_3_1_t2v_lite": {
        "landscape": "veo_3_1_t2v_lite_landscape",
        "portrait": "veo_3_1_t2v_lite_portrait",
    },
    "veo_3_1_t2v_lite_4s": {
        "landscape": "veo_3_1_t2v_lite_4s_landscape",
        "portrait": "veo_3_1_t2v_lite_4s_portrait",
    },
    "veo_3_1_t2v_lite_6s": {
        "landscape": "veo_3_1_t2v_lite_6s_landscape",
        "portrait": "veo_3_1_t2v_lite_6s_portrait",
    },
    "veo_3_1_t2v_lite_8s": {
        "landscape": "veo_3_1_t2v_lite_8s_landscape",
        "portrait": "veo_3_1_t2v_lite_8s_portrait",
    },
    "omni": {
        "landscape": "omni",
        "portrait": "omni_portrait",
    },
    # I2V models
    "veo_3_1_i2v_s_fast_fl": {
        "landscape": "veo_3_1_i2v_s_fast_fl",
        "portrait": "veo_3_1_i2v_s_fast_portrait_fl",
    },
    "veo_3_1_i2v_s_fast_4s_fl": {
        "landscape": "veo_3_1_i2v_s_fast_4s_fl",
        "portrait": "veo_3_1_i2v_s_fast_portrait_4s_fl",
    },
    "veo_3_1_i2v_s_fast_6s_fl": {
        "landscape": "veo_3_1_i2v_s_fast_6s_fl",
        "portrait": "veo_3_1_i2v_s_fast_portrait_6s_fl",
    },
    "veo_3_1_i2v_s_fast_8s_fl": {
        "landscape": "veo_3_1_i2v_s_fast_8s_fl",
        "portrait": "veo_3_1_i2v_s_fast_portrait_8s_fl",
    },
    "veo_3_1_i2v_s_fast_ultra_fl": {
        "landscape": "veo_3_1_i2v_s_fast_ultra_fl",
        "portrait": "veo_3_1_i2v_s_fast_portrait_ultra_fl",
    },
    "veo_3_1_i2v_s_fast_ultra_relaxed": {
        "landscape": "veo_3_1_i2v_s_fast_ultra_relaxed",
        "portrait": "veo_3_1_i2v_s_fast_portrait_ultra_relaxed",
    },
    "veo_3_1_i2v_s": {
        "landscape": "veo_3_1_i2v_s_landscape",
        "portrait": "veo_3_1_i2v_s_portrait",
    },
    "veo_3_1_i2v_s_4s": {
        "landscape": "veo_3_1_i2v_s_4s",
        "portrait": "veo_3_1_i2v_s_portrait_4s",
    },
    "veo_3_1_i2v_s_6s": {
        "landscape": "veo_3_1_i2v_s_6s",
        "portrait": "veo_3_1_i2v_s_portrait_6s",
    },
    "veo_3_1_i2v_s_8s": {
        "landscape": "veo_3_1_i2v_s_8s",
        "portrait": "veo_3_1_i2v_s_portrait_8s",
    },
    "veo_3_1_i2v_s_4s_4k": {
        "landscape": "veo_3_1_i2v_s_4s_4k",
        "portrait": "veo_3_1_i2v_s_portrait_4s_4k",
    },
    "veo_3_1_i2v_s_4s_1080p": {
        "landscape": "veo_3_1_i2v_s_4s_1080p",
        "portrait": "veo_3_1_i2v_s_portrait_4s_1080p",
    },
    "veo_3_1_i2v_s_6s_4k": {
        "landscape": "veo_3_1_i2v_s_6s_4k",
        "portrait": "veo_3_1_i2v_s_portrait_6s_4k",
    },
    "veo_3_1_i2v_s_6s_1080p": {
        "landscape": "veo_3_1_i2v_s_6s_1080p",
        "portrait": "veo_3_1_i2v_s_portrait_6s_1080p",
    },
    "veo_3_1_i2v_s_8s_4k": {
        "landscape": "veo_3_1_i2v_s_8s_4k",
        "portrait": "veo_3_1_i2v_s_portrait_8s_4k",
    },
    "veo_3_1_i2v_s_8s_1080p": {
        "landscape": "veo_3_1_i2v_s_8s_1080p",
        "portrait": "veo_3_1_i2v_s_portrait_8s_1080p",
    },
    "veo_3_1_i2v_s_4k": {
        "landscape": "veo_3_1_i2v_s_4k",
        "portrait": "veo_3_1_i2v_s_portrait_4k",
    },
    "veo_3_1_i2v_s_1080p": {
        "landscape": "veo_3_1_i2v_s_1080p",
        "portrait": "veo_3_1_i2v_s_portrait_1080p",
    },
    "veo_3_1_i2v_lite": {
        "landscape": "veo_3_1_i2v_lite_landscape",
        "portrait": "veo_3_1_i2v_lite_portrait",
    },
    "veo_3_1_i2v_lite_4s": {
        "landscape": "veo_3_1_i2v_lite_4s_landscape",
        "portrait": "veo_3_1_i2v_lite_4s_portrait",
    },
    "veo_3_1_i2v_lite_6s": {
        "landscape": "veo_3_1_i2v_lite_6s_landscape",
        "portrait": "veo_3_1_i2v_lite_6s_portrait",
    },
    "veo_3_1_i2v_lite_8s": {
        "landscape": "veo_3_1_i2v_lite_8s_landscape",
        "portrait": "veo_3_1_i2v_lite_8s_portrait",
    },
    "veo_3_1_interpolation_lite": {
        "landscape": "veo_3_1_interpolation_lite_landscape",
        "portrait": "veo_3_1_interpolation_lite_portrait",
    },
    "veo_3_1_interpolation_lite_4s": {
        "landscape": "veo_3_1_interpolation_lite_4s_landscape",
        "portrait": "veo_3_1_interpolation_lite_4s_portrait",
    },
    "veo_3_1_interpolation_lite_6s": {
        "landscape": "veo_3_1_interpolation_lite_6s_landscape",
        "portrait": "veo_3_1_interpolation_lite_6s_portrait",
    },
    "veo_3_1_interpolation_lite_8s": {
        "landscape": "veo_3_1_interpolation_lite_8s_landscape",
        "portrait": "veo_3_1_interpolation_lite_8s_portrait",
    },
    # R2V models
    "veo_3_1_r2v_fast": {
        "landscape": "veo_3_1_r2v_fast",
        "portrait": "veo_3_1_r2v_fast_portrait",
    },
    "veo_3_1_r2v_fast_8s": {
        "landscape": "veo_3_1_r2v_fast_8s",
        "portrait": "veo_3_1_r2v_fast_portrait_8s",
    },
    "veo_3_1_r2v_fast_ultra": {
        "landscape": "veo_3_1_r2v_fast_ultra",
        "portrait": "veo_3_1_r2v_fast_portrait_ultra",
    },
    "veo_3_1_r2v_fast_ultra_8s": {
        "landscape": "veo_3_1_r2v_fast_ultra_8s",
        "portrait": "veo_3_1_r2v_fast_portrait_ultra_8s",
    },
    "veo_3_1_r2v_fast_ultra_relaxed": {
        "landscape": "veo_3_1_r2v_fast_ultra_relaxed",
        "portrait": "veo_3_1_r2v_fast_portrait_ultra_relaxed",
    },
    "veo_3_1_r2v_fast_ultra_relaxed_8s": {
        "landscape": "veo_3_1_r2v_fast_ultra_relaxed_8s",
        "portrait": "veo_3_1_r2v_fast_portrait_ultra_relaxed_8s",
    },
    # Extend models (视频续写)
    "veo_3_1_extend": {
        "landscape": "veo_3_1_extend",
        "portrait": "veo_3_1_extend_portrait",
    },
}


def _extract_generation_params(request) -> Tuple[Optional[str], Optional[str]]:
    """从请求中提取 aspectRatio 和 imageSize 参数。

    优先级：
    1. request.generationConfig.imageConfig (顶层 Gemini 参数)
    2. extra fields 中的 generationConfig (extra_body 透传)
    3. OpenAI 风格字段（size/quality）兼容：可在 generationConfig/imageConfig 或顶层 extra 中出现

    Returns:
        (aspect_ratio, image_size) 归一化后的值
    """

    def _normalize_str(value: Any) -> Optional[str]:
        if not isinstance(value, str):
            return None
        text = value.strip()
        return text if text else None

    def _read_value(obj: Any, *keys: str) -> Any:
        if obj is None:
            return None
        if isinstance(obj, dict):
            for key in keys:
                if key in obj:
                    return obj.get(key)
            return None

        for key in keys:
            if hasattr(obj, key):
                value = getattr(obj, key, None)
                if value is not None:
                    return value

        extra = getattr(obj, "__pydantic_extra__", None) or {}
        for key in keys:
            if key in extra:
                return extra.get(key)
        return None

    def _normalize_aspect_ratio(value: Any) -> Optional[str]:
        raw = _normalize_str(value)
        if not raw:
            return None

        token = (
            raw.replace("：", ":")
            .replace("/", ":")
            .replace("x", ":")
            .replace("X", ":")
            .replace(" ", "")
            .strip()
        )

        mapped = ASPECT_RATIO_MAP.get(token)
        if mapped:
            return mapped
        mapped = ASPECT_RATIO_MAP.get(token.lower())
        if mapped:
            return mapped
        mapped = ASPECT_RATIO_MAP.get(token.upper())
        if mapped:
            return mapped
        return token

    def _normalize_image_size(value: Any) -> Optional[str]:
        raw = _normalize_str(value)
        if not raw:
            return None

        token = raw.replace(" ", "").strip()
        mapped = IMAGE_SIZE_MAP.get(token)
        if mapped is not None:
            return mapped or None
        mapped = IMAGE_SIZE_MAP.get(token.lower())
        if mapped is not None:
            return mapped or None
        mapped = IMAGE_SIZE_MAP.get(token.upper())
        if mapped is not None:
            return mapped or None
        return token.lower()

    def _aspect_from_openai_size(value: Any) -> Optional[str]:
        raw = _normalize_str(value)
        if not raw:
            return None

        match = OPENAI_IMAGE_SIZE_RE.match(raw)
        if not match:
            return None

        try:
            width = int(match.group("w"))
            height = int(match.group("h"))
        except Exception:
            return None

        return _aspect_from_dimensions(width, height)

    def _image_size_from_openai_quality(value: Any) -> Optional[str]:
        raw = _normalize_str(value)
        if not raw:
            return None

        token = raw.strip().lower()
        if token in IMAGE_SIZE_MAP:
            return _normalize_image_size(token)

        mapped = OPENAI_QUALITY_MAP.get(token)
        if mapped:
            return mapped
        return None

    def _apply_image_config(
        image_config: Any, aspect_ratio: Optional[str], image_size: Optional[str]
    ) -> Tuple[Optional[str], Optional[str]]:
        # 显式 aspectRatio/imageSize
        if not aspect_ratio:
            aspect_ratio = _normalize_aspect_ratio(
                _read_value(image_config, "aspectRatio", "aspect_ratio", "aspect")
            )
        if not image_size:
            image_size = _normalize_image_size(
                _read_value(image_config, "imageSize", "image_size", "resolution")
            )

        # OpenAI size/quality
        if not aspect_ratio:
            aspect_ratio = _aspect_from_openai_size(_read_value(image_config, "size"))
        if not image_size:
            image_size = _image_size_from_openai_quality(
                _read_value(image_config, "quality", "imageQuality", "image_quality")
            )

        return aspect_ratio, image_size

    aspect_ratio: Optional[str] = None
    image_size: Optional[str] = None

    # 1) 优先从 request.generationConfig 解析
    gen_config = getattr(request, "generationConfig", None)
    if gen_config is not None:
        image_config = _read_value(gen_config, "imageConfig", "image_config")
        if image_config is not None:
            aspect_ratio, image_size = _apply_image_config(
                image_config, aspect_ratio, image_size
            )

        # 有些上游会把字段放在 generationConfig 顶层
        if not aspect_ratio:
            aspect_ratio = _normalize_aspect_ratio(
                _read_value(gen_config, "aspectRatio", "aspect_ratio")
            )
        if not image_size:
            image_size = _normalize_image_size(
                _read_value(gen_config, "imageSize", "image_size")
            )

        if not aspect_ratio:
            aspect_ratio = _aspect_from_openai_size(_read_value(gen_config, "size"))
        if not image_size:
            image_size = _image_size_from_openai_quality(
                _read_value(gen_config, "quality")
            )

    # 2) 顶层没有时，再尝试从 extra fields (Pydantic extra="allow") 中透传的 generationConfig
    if (aspect_ratio is None or image_size is None) and hasattr(
        request, "__pydantic_extra__"
    ):
        extra = request.__pydantic_extra__ or {}
        gen_config_raw = extra.get("generationConfig")
        if not isinstance(gen_config_raw, dict):
            extra_body = extra.get("extra_body") or extra.get("extraBody")
            if isinstance(extra_body, dict):
                gen_config_raw = extra_body.get("generationConfig")

        if isinstance(gen_config_raw, dict):
            image_config_raw = (
                gen_config_raw.get("imageConfig")
                or gen_config_raw.get("image_config")
                or {}
            )
            if image_config_raw:
                aspect_ratio, image_size = _apply_image_config(
                    image_config_raw, aspect_ratio, image_size
                )

            if aspect_ratio is None:
                aspect_ratio = _normalize_aspect_ratio(
                    gen_config_raw.get("aspectRatio")
                    or gen_config_raw.get("aspect_ratio")
                )
            if image_size is None:
                image_size = _normalize_image_size(
                    gen_config_raw.get("imageSize") or gen_config_raw.get("image_size")
                )

            if aspect_ratio is None:
                aspect_ratio = _aspect_from_openai_size(gen_config_raw.get("size"))
            if image_size is None:
                image_size = _image_size_from_openai_quality(
                    gen_config_raw.get("quality")
                )

    # 3) OpenAI 风格 size/quality（顶层 extra）兼容
    if (aspect_ratio is None or image_size is None) and hasattr(
        request, "__pydantic_extra__"
    ):
        extra = request.__pydantic_extra__ or {}
        if aspect_ratio is None:
            aspect_ratio = _aspect_from_openai_size(extra.get("size"))
        if image_size is None:
            image_size = _image_size_from_openai_quality(extra.get("quality"))

        # 一些上游可能直接传 aspect_ratio/image_size
        if aspect_ratio is None:
            aspect_ratio = _normalize_aspect_ratio(
                extra.get("aspect_ratio") or extra.get("aspectRatio")
            )
        if image_size is None:
            image_size = _normalize_image_size(
                extra.get("image_size") or extra.get("imageSize")
            )

    return aspect_ratio, image_size


def _normalize_duration(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        val = int(round(value))
        return val if val > 0 else None
    if isinstance(value, str):
        val_str = (
            value.lower()
            .replace("seconds", "")
            .replace("second", "")
            .replace("sec", "")
            .replace("s", "")
            .replace("秒", "")
            .strip()
        )
        try:
            val = int(round(float(val_str)))
            return val if val > 0 else None
        except ValueError:
            return None
    return None


def _extract_video_params(request) -> Tuple[Optional[str], Optional[int]]:
    """从请求中提取视频 aspectRatio 和 duration 参数。"""
    aspect_ratio: Optional[str] = None
    duration: Optional[int] = None

    if request is None:
        return aspect_ratio, duration

    def _read_val(obj: Any, *keys: str) -> Any:
        if obj is None:
            return None
        if isinstance(obj, dict):
            for k in keys:
                if k in obj and obj[k] is not None:
                    return obj[k]
            return None
        for k in keys:
            if hasattr(obj, k):
                v = getattr(obj, k, None)
                if v is not None:
                    return v
        extra = getattr(obj, "__pydantic_extra__", None) or {}
        for k in keys:
            if k in extra and extra[k] is not None:
                return extra[k]
        return None

    # 1. 直接从 request 顶层读取
    duration = _normalize_duration(
        _read_val(request, "duration", "durationSeconds", "duration_seconds", "seconds")
    )
    aspect_raw = _read_val(
        request, "aspectRatio", "aspect_ratio", "orientation", "aspect"
    )

    # 2. 从 generationConfig 读取
    gen_config = getattr(request, "generationConfig", None)
    if gen_config is not None:
        if duration is None:
            duration = _normalize_duration(
                _read_val(gen_config, "duration", "durationSeconds", "duration_seconds", "seconds")
            )
        video_config = _read_val(gen_config, "videoConfig", "video_config")
        if video_config is not None:
            if duration is None:
                duration = _normalize_duration(
                    _read_val(video_config, "duration", "durationSeconds", "duration_seconds", "seconds")
                )
            if aspect_raw is None:
                aspect_raw = _read_val(video_config, "aspectRatio", "aspect_ratio", "orientation", "aspect")
        if aspect_raw is None:
            aspect_raw = _read_val(gen_config, "aspectRatio", "aspect_ratio", "orientation", "aspect")

    # 3. 从 extra 或 extra_body 读取
    extra = getattr(request, "__pydantic_extra__", None) or {}
    if duration is None:
        duration = _normalize_duration(
            _read_val(extra, "duration", "durationSeconds", "duration_seconds", "seconds")
        )
    if aspect_raw is None:
        aspect_raw = _read_val(extra, "aspectRatio", "aspect_ratio", "orientation", "aspect")

    extra_body = extra.get("extra_body") or extra.get("extraBody") or {}
    if isinstance(extra_body, dict):
        if duration is None:
            duration = _normalize_duration(
                _read_val(extra_body, "duration", "durationSeconds", "duration_seconds", "seconds")
            )
        eb_vid = extra_body.get("videoConfig") or extra_body.get("video_config") or {}
        eb_gen = extra_body.get("generationConfig") or extra_body.get("generation_config") or {}
        if duration is None:
            duration = _normalize_duration(
                _read_val(eb_vid, "duration", "durationSeconds", "duration_seconds", "seconds")
            )
        if duration is None:
            duration = _normalize_duration(
                _read_val(eb_gen, "duration", "durationSeconds", "duration_seconds", "seconds")
            )
        if aspect_raw is None:
            aspect_raw = _read_val(eb_vid, "aspectRatio", "aspect_ratio", "orientation", "aspect")
        if aspect_raw is None:
            aspect_raw = _read_val(eb_gen, "aspectRatio", "aspect_ratio", "orientation", "aspect")

    # 4. 从 OpenAI size 尺寸推断视频方向
    if aspect_raw is None:
        sz = _read_val(request, "size") or _read_val(extra, "size")
        if isinstance(sz, str):
            m = OPENAI_IMAGE_SIZE_RE.match(sz.strip())
            if m:
                w, h = int(m.group("w")), int(m.group("h"))
                aspect_raw = "portrait" if h > w else "landscape"

    # 归一化 aspect_ratio
    if aspect_raw:
        ar_str = str(aspect_raw).lower().strip()
        if ar_str in ("9:16", "9-16", "portrait"):
            aspect_ratio = "portrait"
        elif ar_str in ("16:9", "16-9", "landscape"):
            aspect_ratio = "landscape"
        else:
            mapped = ASPECT_RATIO_MAP.get(ar_str)
            if mapped in ("landscape", "portrait"):
                aspect_ratio = mapped
            else:
                aspect_ratio = None

    return aspect_ratio, duration


def normalize_model_alias(m: str) -> str:
    """统一模型前缀与比例后缀，例如 gflow-nano-banana-* -> gemini-*，-16-9 -> -landscape。"""
    if m.startswith("gflow-"):
        m = m[len("gflow-"):]
    prefixes = [
        ("nano-banana-2-lite", "gemini-3.1-flash-lite-image"),
        ("nano-banana-2.0-lite", "gemini-3.1-flash-lite-image"),
        ("nano-banana-pro", "gemini-3.0-pro-image"),
        ("nano-banana-2.1", "gemini-3.1-flash-image"),
        ("nano-banana", "gemini-3.1-flash-image"),
    ]
    for nb, gem in prefixes:
        if m == nb or m.startswith(nb + "-"):
            m = gem + m[len(nb):]
            break

    ratios = [
        ("-16-9", "-landscape"),
        ("-16:9", "-landscape"),
        ("-9-16", "-portrait"),
        ("-9:16", "-portrait"),
        ("-1-1", "-square"),
        ("-1:1", "-square"),
        ("-4-3", "-four-three"),
        ("-4:3", "-four-three"),
        ("-3-4", "-three-four"),
        ("-3:4", "-three-four"),
    ]
    for r_num, r_name in ratios:
        if r_num in m:
            m = m.replace(r_num, r_name)
    return m

def resolve_model_name(
    model: str, request=None, model_config: Dict[str, Any] = None, images: Any = None
) -> str:
    """将简化模型名 + generationConfig 参数解析为内部 MODEL_CONFIG key。

    如果 model 已经是有效的 MODEL_CONFIG key，直接返回。
    如果 model 是简化名（基础模型名），则根据 generationConfig 中的
    aspectRatio / imageSize 拼接出完整的内部模型名。

    Args:
        model: 请求中的模型名
        request: ChatCompletionRequest 实例（用于提取 generationConfig）
        model_config: MODEL_CONFIG 字典（用于验证解析后的模型名）

    Returns:
        解析后的内部模型名
    """
    model = normalize_model_alias(model)

    # ────── 图片模型解析 ──────
    if model in IMAGE_BASE_MODELS:
        base = IMAGE_BASE_MODELS[model]
        aspect_ratio, image_size = (
            _extract_generation_params(request) if request else (None, None)
        )

        if not aspect_ratio:
            aspect_ratio = _infer_aspect_ratio_from_images(images)

        # 默认 aspect ratio
        if not aspect_ratio:
            aspect_ratio = DEFAULT_ASPECT

        # 检查支持的 aspect ratio
        supported_aspects = MODEL_SUPPORTED_ASPECTS.get(base, [])
        if aspect_ratio not in supported_aspects and supported_aspects:
            debug_logger.log_warning(
                f"[MODEL_RESOLVER] 模型 {base} 不支持 aspectRatio={aspect_ratio}，"
                f"降级到 {DEFAULT_ASPECT}"
            )
            aspect_ratio = DEFAULT_ASPECT

        # 拼接模型名
        resolved = f"{base}-{aspect_ratio}"

        # 检查支持的 imageSize
        if image_size and image_size != "1k":
            supported_sizes = MODEL_SUPPORTED_SIZES.get(base, [])
            if image_size in supported_sizes:
                resolved = f"{resolved}-{image_size}"
            else:
                debug_logger.log_warning(
                    f"[MODEL_RESOLVER] 模型 {base} 不支持 imageSize={image_size}，忽略"
                )

        # 最终验证
        if model_config and resolved not in model_config:
            debug_logger.log_warning(
                f"[MODEL_RESOLVER] 解析后的模型名 {resolved} 不在 MODEL_CONFIG 中，"
                f"回退到原始模型名 {model}"
            )
            return model

        debug_logger.log_info(
            f"[MODEL_RESOLVER] 模型名转换: {model} → {resolved} "
            f"(aspectRatio={aspect_ratio}, imageSize={image_size or 'default'})"
        )
        return resolved

    # ────── 视频模型解析 ──────
        # 2. 现代视频基础模型自动调配 (4 个基础模型 x 时长 x 比例 = 26 种组合)
    if model in VIDEO_MODERN_BASES:
        aspect_ratio, duration = (
            _extract_video_params(request) if request else (None, None)
        )

        if not aspect_ratio:
            aspect_ratio = _infer_aspect_ratio_from_images(images, video_mode=True)

        if not aspect_ratio or aspect_ratio not in ("landscape", "portrait"):
            aspect_ratio = "landscape"

        if model == "omni-1.1-flash":
            allowed_durations = [4, 6, 8, 10]
            duration = min(allowed_durations, key=lambda x: abs(x - duration)) if duration else 8
        else:
            allowed_durations = [4, 6, 8]
            duration = min(allowed_durations, key=lambda x: abs(x - duration)) if duration else 8

        has_images = bool(images)
        if has_images:
            if model == "omni-1.1-flash":
                resolved = f"omni-1.1-flash-{duration}s-{aspect_ratio}"
            elif model == "veo-3.1-quality":
                resolved = f"veo-3.1-quality-i2v-{duration}s-{aspect_ratio}" if duration in (4, 6) else f"veo-3.1-quality-8s-{aspect_ratio}"
            else:
                family = "fast" if "fast" in model else "lite"
                resolved = f"veo-3.1-{family}-i2v-{duration}s-{aspect_ratio}" if duration in (4, 6) else f"veo-3.1-{family}-r2v-8s-{aspect_ratio}"
        else:
            resolved = f"{model}-{duration}s-{aspect_ratio}"

        if model_config and resolved in model_config:
            debug_logger.log_info(
                f"[MODEL_RESOLVER] 视频模型自动调配: {model} -> {resolved} "
                f"(duration={duration}s, aspect={aspect_ratio}, has_images={has_images})"
            )
            return resolved

        debug_logger.log_warning(
            f"[MODEL_RESOLVER] 视频模型 {model} 调配失败 (target={resolved})，使用原始模型名"
        )
        return model

    # 3. 兼容历史/扩展的视频别名 (Legacy video models)
    if model in VIDEO_BASE_MODELS:
        aspect_ratio, image_size = (
            _extract_generation_params(request) if request else (None, None)
        )

        if not aspect_ratio:
            aspect_ratio = _infer_aspect_ratio_from_images(images, video_mode=True)

        # 视频默认横屏
        if not aspect_ratio or aspect_ratio not in ("landscape", "portrait"):
            aspect_ratio = "landscape"

        if (
            image_size in ("4k", "1080p")
            and f"{model}_{image_size}" in VIDEO_BASE_MODELS
        ):
            model = f"{model}_{image_size}"

        orientation_map = VIDEO_BASE_MODELS[model]
        resolved = orientation_map.get(aspect_ratio)

        if resolved and model_config and resolved in model_config:
            debug_logger.log_info(
                f"[MODEL_RESOLVER] 视频模型名转换: {model} → {resolved} "
                f"(aspectRatio={aspect_ratio})"
            )
            return resolved

        debug_logger.log_warning(
            f"[MODEL_RESOLVER] 视频模型 {model} 解析失败 (aspect={aspect_ratio})，"
            f"使用原始模型名"
        )
        return model

    # 如果已经是有效的 MODEL_CONFIG key，直接返回
    if model_config and model in model_config:
        return model

    # 未知模型名，原样返回（由下游 MODEL_CONFIG 校验报错）
    return model


def get_base_model_aliases() -> Dict[str, str]:
    """返回所有简化模型名（别名）及其描述，用于 /v1/models 接口展示。"""
    aliases = {}

    for alias, base in IMAGE_BASE_MODELS.items():
        aspects = MODEL_SUPPORTED_ASPECTS.get(base, [])
        sizes = MODEL_SUPPORTED_SIZES.get(base, [])
        desc_parts = [f"aspects: {', '.join(aspects)}"]
        if sizes:
            desc_parts.append(f"sizes: {', '.join(sizes)}")
        aliases[alias] = f"Image generation (alias) - {'; '.join(desc_parts)}"

    for alias in VIDEO_BASE_MODELS:
        aliases[alias] = (
            "Video generation (alias) - supports landscape/portrait via generationConfig"
        )

    return aliases
