"""
Unit tests for GFlow model catalog and auto-dispatching:
1. Verifies get_gflow_model_catalog() returns strictly the 7 core models.
2. Verifies auto-dispatching for all 3 image models across 5 aspect ratios and 3 resolutions.
3. Verifies auto-dispatching for all 4 video models across durations and orientations.
4. Verifies direct Cartesian product variant calls and function calls are preserved.
"""

import sys
import unittest
from pathlib import Path

# Add python and flow2api to sys.path
root_dir = Path(__file__).resolve().parents[1]
flow_dir = root_dir / "python" / "flow2api"
sys.path.insert(0, str(root_dir / "python"))
sys.path.insert(0, str(flow_dir))

from worker import get_gflow_model_catalog
from model_adapter import resolve_model_name, normalize_model_alias
from src.services.generation_handler import MODEL_CONFIG


class DummyRequest:
    def __init__(self, **kwargs):
        self.__pydantic_extra__ = kwargs


class DummyGeminiRequest:
    def __init__(self, gen_config):
        self.generationConfig = gen_config


class TestGFlowModelDispatch(unittest.TestCase):
    def test_catalog_strictly_seven_models(self):
        """Verify client catalog contains strictly the 7 core models."""
        catalog = get_gflow_model_catalog()
        self.assertEqual(len(catalog), 7, f"Expected 7 models, got {len(catalog)}")
        
        expected_ids = {
            "gflow-nano-banana-pro",
            "gflow-nano-banana-2-lite",
            "gflow-nano-banana-2.1",
            "gflow-omni-1.1-flash",
            "gflow-veo-3.1-lite",
            "gflow-veo-3.1-fast",
            "gflow-veo-3.1-quality",
        }
        actual_ids = {m["id"] for m in catalog}
        self.assertEqual(actual_ids, expected_ids)

        image_models = [m for m in catalog if m["type"] == "image"]
        video_models = [m for m in catalog if m["type"] == "video"]
        self.assertEqual(len(image_models), 3)
        self.assertEqual(len(video_models), 4)

    def test_image_auto_dispatch_all_ratios_and_resolutions(self):
        """Verify 3 image bases x 5 ratios x 3 resolutions = 45 combinations auto-dispatch."""
        bases = [
            ("gflow-nano-banana-pro", "gemini-3.0-pro-image"),
            ("gflow-nano-banana-2-lite", "gemini-3.1-flash-lite-image"),
            ("gflow-nano-banana-2.1", "gemini-3.1-flash-image"),
        ]
        ratios = [
            ("16:9", "landscape"),
            ("9:16", "portrait"),
            ("1:1", "square"),
            ("4:3", "four-three"),
            ("3:4", "three-four"),
        ]
        sizes = [
            ("1k", ""),
            ("2k", "-2k"),
            ("4k", "-4k"),
        ]

        count = 0
        for client_id, internal_base in bases:
            for req_ratio, ratio_slug in ratios:
                for req_size, size_slug in sizes:
                    # Test via Gemini generationConfig
                    req_gemini = DummyGeminiRequest({
                        "imageConfig": {
                            "aspectRatio": req_ratio,
                            "imageSize": req_size,
                        }
                    })
                    resolved = resolve_model_name(client_id, request=req_gemini, model_config=MODEL_CONFIG)
                    expected = f"{internal_base}-{ratio_slug}{size_slug}"
                    self.assertEqual(resolved, expected)
                    self.assertIn(resolved, MODEL_CONFIG)

                    # Test via OpenAI extra fields
                    req_openai = DummyRequest(aspectRatio=req_ratio, imageSize=req_size)
                    resolved_oai = resolve_model_name(client_id, request=req_openai, model_config=MODEL_CONFIG)
                    self.assertEqual(resolved_oai, expected)
                    count += 1

        self.assertEqual(count, 45)

    def test_image_auto_dispatch_defaults(self):
        """When no parameters are passed, image models should default to 16:9 1K."""
        defaults = [
            ("gflow-nano-banana-pro", "gemini-3.0-pro-image-landscape"),
            ("gflow-nano-banana-2-lite", "gemini-3.1-flash-lite-image-landscape"),
            ("gflow-nano-banana-2.1", "gemini-3.1-flash-image-landscape"),
        ]
        for client_id, expected in defaults:
            resolved = resolve_model_name(client_id, request=None, model_config=MODEL_CONFIG)
            self.assertEqual(resolved, expected)
            self.assertIn(resolved, MODEL_CONFIG)

    def test_video_auto_dispatch_all_durations_and_ratios(self):
        """Verify video models auto-dispatch across durations and orientations."""
        # Omni: 4s, 6s, 8s, 10s x 2 orientations = 8 combinations
        for d in [4, 6, 8, 10]:
            for asp, slug in [("16:9", "landscape"), ("9:16", "portrait")]:
                req = DummyRequest(duration=d, aspectRatio=asp)
                resolved = resolve_model_name("gflow-omni-1.1-flash", request=req, model_config=MODEL_CONFIG)
                expected = f"omni-1.1-flash-{d}s-{slug}"
                self.assertEqual(resolved, expected)
                self.assertIn(resolved, MODEL_CONFIG)

        # Veo 3.1 Fast, Lite, Quality: 4s, 6s, 8s x 2 orientations = 6 combinations each (18 total)
        for base in ["gflow-veo-3.1-fast", "gflow-veo-3.1-lite", "gflow-veo-3.1-quality"]:
            clean_base = base[len("gflow-"):]
            for d in [4, 6, 8]:
                for asp, slug in [("16:9", "landscape"), ("9:16", "portrait")]:
                    req = DummyRequest(duration=d, aspectRatio=asp)
                    resolved = resolve_model_name(base, request=req, model_config=MODEL_CONFIG)
                    expected = f"{clean_base}-{d}s-{slug}"
                    self.assertEqual(resolved, expected)
                    self.assertIn(resolved, MODEL_CONFIG)

    def test_video_auto_dispatch_defaults(self):
        """When no parameters are passed, video models default to 8s landscape."""
        defaults = [
            ("gflow-omni-1.1-flash", "omni-1.1-flash-8s-landscape"),
            ("gflow-veo-3.1-fast", "veo-3.1-fast-8s-landscape"),
            ("gflow-veo-3.1-lite", "veo-3.1-lite-8s-landscape"),
            ("gflow-veo-3.1-quality", "veo-3.1-quality-8s-landscape"),
        ]
        for client_id, expected in defaults:
            resolved = resolve_model_name(client_id, request=None, model_config=MODEL_CONFIG)
            self.assertEqual(resolved, expected)
            self.assertIn(resolved, MODEL_CONFIG)

    def test_video_auto_dispatch_with_images(self):
        """When reference images are present, auto-dispatch to corresponding I2V/R2V variant."""
        fake_image = [b"fake-image-bytes"]

        # Omni maintains native reference image routing
        req = DummyRequest(duration=4, aspectRatio="landscape")
        res = resolve_model_name("gflow-omni-1.1-flash", request=req, model_config=MODEL_CONFIG, images=fake_image)
        self.assertEqual(res, "omni-1.1-flash-4s-landscape")

        # Veo Fast I2V/R2V
        res_fast_4s = resolve_model_name("gflow-veo-3.1-fast", request=DummyRequest(duration=4), model_config=MODEL_CONFIG, images=fake_image)
        self.assertEqual(res_fast_4s, "veo-3.1-fast-i2v-4s-landscape")
        res_fast_8s = resolve_model_name("gflow-veo-3.1-fast", request=DummyRequest(duration=8), model_config=MODEL_CONFIG, images=fake_image)
        self.assertEqual(res_fast_8s, "veo-3.1-fast-r2v-8s-landscape")

        # Veo Lite I2V/R2V
        res_lite_6s = resolve_model_name("gflow-veo-3.1-lite", request=DummyRequest(duration=6, aspectRatio="portrait"), model_config=MODEL_CONFIG, images=fake_image)
        self.assertEqual(res_lite_6s, "veo-3.1-lite-i2v-6s-portrait")

    def test_direct_variant_calls_preserved(self):
        """Clients can still explicitly invoke specific Cartesian product model names."""
        direct_cases = [
            ("gflow-nano-banana-pro-square-4k", "gemini-3.0-pro-image-square-4k"),
            ("gflow-nano-banana-2.1-four-three-2k", "gemini-3.1-flash-image-four-three-2k"),
            ("gflow-veo-3.1-fast-4s-portrait", "veo-3.1-fast-4s-portrait"),
            ("gflow-omni-1.1-flash-10s-landscape", "omni-1.1-flash-10s-landscape"),
        ]
        for inp, expected in direct_cases:
            resolved = resolve_model_name(inp, model_config=MODEL_CONFIG)
            self.assertEqual(resolved, expected)
            self.assertIn(resolved, MODEL_CONFIG)


if __name__ == "__main__":
    unittest.main()
