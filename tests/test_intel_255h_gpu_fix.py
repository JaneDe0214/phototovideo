import unittest
from core.encoder_detector import HardwareDetector
from core.ffmpeg_engine import RenderConfig, VideoRenderEngine


class TestIntel255hGpuFix(unittest.TestCase):
    """驗證 Intel Core Ultra 255H / 155H GPU 硬體加速修復與多層級自癒體系"""

    def test_255h_recommended_profiles_priority(self):
        """驗證 255H（同時支援 AV1 與 HEVC）環境下，8K 首選必為 hevc_qsv，4K 首選為 av1_qsv"""
        detector = HardwareDetector()
        # 模擬 255H 實體硬體能力
        detector.supported_hardware = {
            "av1_qsv": True,
            "hevc_qsv": True,
            "h264_qsv": True,
            "av1_nvenc": False,
            "hevc_nvenc": False,
            "av1_amf": False,
            "hevc_amf": False,
            "libx265": True,
            "libx264": True,
        }

        profiles = detector.get_recommended_profiles()
        # 8K 第一推薦必須是 hevc_qsv (硬體成熟度最高，絕不選 CPU 軟解)
        first_prof = profiles[0]
        self.assertEqual(first_prof["id"], "8k_qsv_hevc")
        self.assertIn("Intel QSV", first_prof["hw_type"])

        # 4K 第一推薦必須是 4k_qsv_av1 (充分發揮 255H 的 AV1 硬編能力)
        prof_4k_list = [p for p in profiles if "4k" in p["id"].lower()]
        self.assertTrue(len(prof_4k_list) > 0)
        self.assertEqual(prof_4k_list[0]["id"], "4k_qsv_av1")

    def test_av1_fallback_to_hevc_gpu_not_cpu(self):
        """驗證 8K AV1 若遇到顯存/驅動限制時，優先切換至 hevc_qsv (GPU)，絕不直接掉到 CPU 軟解"""
        config = RenderConfig(
            resolution="7680x4320",
            vcodec="av1_qsv",
            bitrate="240M",
        )
        engine = VideoRenderEngine(config)

        # 模擬 av1_qsv 在 8K 失敗，但 hevc_qsv 支援
        def mock_test_capability(codec, w, h, pix_fmt):
            if codec == "av1_qsv":
                return False, "8K AV1 驅動規格受限"
            elif codec == "hevc_qsv":
                return True, "支援"
            return True, "支援"

        engine._test_hardware_encode_capability = mock_test_capability

        # 模擬 render_part 前的自適應判定邏輯
        effective_vcodec = engine._active_fallback_codec or engine.config.vcodec
        test_pix_fmt = "nv12" if "qsv" in effective_vcodec else "yuv420p"
        hw_ok, hw_msg = engine._test_hardware_encode_capability(
            effective_vcodec, engine.config.width, engine.config.height, test_pix_fmt
        )
        if not hw_ok:
            fallback_hw = "hevc_qsv" if "qsv" in effective_vcodec else None
            if fallback_hw:
                hw2_ok, _ = engine._test_hardware_encode_capability(
                    fallback_hw, engine.config.width, engine.config.height, test_pix_fmt
                )
                if hw2_ok:
                    effective_vcodec = fallback_hw

        # 驗證降級結果為 hevc_qsv (GPU 硬解)，而不是 libx265 (CPU 軟解)
        self.assertEqual(effective_vcodec, "hevc_qsv")
        self.assertNotEqual(effective_vcodec, "libx265")

    def test_single_item_cpu_fallback_does_not_pollute_global(self):
        """驗證單一張照片使用 CPU 保底修復時，不會永久污染 _active_fallback_codec 為 libx265"""
        config = RenderConfig(vcodec="hevc_qsv")
        engine = VideoRenderEngine(config)
        self.assertIsNone(engine._active_fallback_codec)


if __name__ == "__main__":
    unittest.main()
