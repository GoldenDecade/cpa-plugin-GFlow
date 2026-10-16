"""返回已缓存的图片内容，兼容只注册精确资源路径的宿主内核。"""
import base64
from pathlib import Path
import re

CACHE_IMAGE = re.compile(r"/v0/resource/plugins/gflow/tmp/([a-f0-9]{32}\.(?:png|jpg|jpeg|webp))")

def inline_cached_images(value, cache_dir):
    """只替换本插件图片缓存；不读取任意文件或短期控制令牌。"""
    memo = {}
    def replace(match):
        filename = match.group(1)
        if filename not in memo:
            path = Path(cache_dir) / filename
            if not path.is_file() or path.stat().st_size > 24 * 1024 * 1024:
                return match.group(0)
            mime = {".png":"image/png",".jpg":"image/jpeg",".jpeg":"image/jpeg",".webp":"image/webp"}[path.suffix]
            memo[filename] = "data:" + mime + ";base64," + base64.b64encode(path.read_bytes()).decode("ascii")
        return memo[filename]
    def walk(item):
        if isinstance(item, str): return CACHE_IMAGE.sub(replace, item)
        if isinstance(item, dict): return {key:walk(child) for key,child in item.items()}
        if isinstance(item, list): return [walk(child) for child in item]
        return item
    return walk(value)
