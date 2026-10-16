"""图片回传契约，不连接真实生成服务。"""
import base64
import importlib.util
from pathlib import Path
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("media_response_under_test",ROOT/"python/media_response.py")
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class MediaResponseRegression(unittest.TestCase):
    def test_cached_image_is_delivered_inline_in_json_and_sse(self):
        root=ROOT/"data/tmp";root.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as tmp:
            name="a"*32+".jpg";body=b"synthetic-jpeg"
            Path(tmp,name).write_bytes(body)
            url="/v0/resource/plugins/gflow/tmp/"+name
            video="/v0/resource/plugins/gflow/tmp/"+"b"*32+".mp4"
            self.assertEqual(module.inline_cached_images(video,tmp),video.replace("/tmp/","/tmp?file="))
            result=module.inline_cached_images({"url":url,"choices":[{"message":{"content":"![image]("+url+")"}}]},tmp)
            expected="data:image/jpeg;base64,"+base64.b64encode(body).decode()
            self.assertEqual(result["url"],expected)
            self.assertIn(expected,result["choices"][0]["message"]["content"])
            self.assertIn(expected,module.inline_cached_images('data: {"url":"'+url+'"}',tmp))
            self.assertEqual(module.inline_cached_images("/v0/resource/plugins/gflow/tmp/control-fake.json",tmp),"/v0/resource/plugins/gflow/tmp/control-fake.json")
            self.assertEqual(module.inline_cached_images("/v0/resource/plugins/gflow/tmp/../../secret.jpg",tmp),"/v0/resource/plugins/gflow/tmp/../../secret.jpg")

if __name__=="__main__":unittest.main()
