"""
單元與整合測試：
1. 8K 畫質第一優先驗證（智慧推薦首選必定為 8K）。
2. UI 畫質切換連動驗證（8K / 4K 快速按鈕互鎖切換）。
3. 遇到無法硬體渲染時，自動無縫切換同畫質軟解（8K libx265）且不中斷。
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.encoder_detector import HardwareDetector
from core.ffmpeg_engine import VideoRenderEngine, RenderConfig
from core.scanner import MediaItem


class TestSmartQualityFallback(unittest.TestCase):
    def test_8k_priority_ranking(self):
        """驗證 8K 畫質第一優先原則"""
        detector = HardwareDetector()
        profiles = detector.get_recommended_profiles()
        self.assertGreater(len(profiles), 0, "應有至少一個可用的 profile")

        # 驗證第一項為 8K
        top_profile = profiles[0]
        self.assertTrue(
            "8k" in top_profile["id"].lower() or "8k" in top_profile["resolution"].lower(),
            f"預設第一項必須為 8K 畫質優先，實際為：{top_profile['id']}",
        )
        safe_name = top_profile['name'].encode('ascii', errors='ignore').decode('ascii')
        print(f"[PASS] 8K 畫質優先驗證成功！第一推薦設定檔ID為：{top_profile['id']}")

    def test_ui_k_presets(self):
        """驗證 UI 上的 8K / 4K 互鎖與切換邏輯"""
        from PyQt6.QtWidgets import QApplication
        from ui.main_window import MainWindow

        app = QApplication.instance() or QApplication(sys.argv)
        win = MainWindow()

        # 預設 8K 應為 Checked
        self.assertTrue(win.btn_preset_8k.isChecked(), "預設 8K 按鈕應為 Checked")
        self.assertFalse(win.btn_preset_4k.isChecked(), "預設 4K 按鈕不應為 Checked")

        # 切換至 4K
        win.btn_preset_4k.click()
        self.assertFalse(win.btn_preset_8k.isChecked(), "點選 4K 後 8K 應為 Unchecked")
        self.assertTrue(win.btn_preset_4k.isChecked(), "點選 4K 後 4K 應為 Checked")
        current_prof_id = win.combo_profile.currentData()
        self.assertTrue("4k" in current_prof_id.lower(), f"下拉選單應連動切換至 4K，實際為：{current_prof_id}")

        # 切回 8K
        win.btn_preset_8k.click()
        self.assertTrue(win.btn_preset_8k.isChecked(), "點選 8K 後 8K 應為 Checked")
        self.assertFalse(win.btn_preset_4k.isChecked(), "點選 8K 後 4K 應為 Unchecked")
        current_prof_id = win.combo_profile.currentData()
        self.assertTrue("8k" in current_prof_id.lower(), f"下拉選單應連動切換至 8K，實際為：{current_prof_id}")

        print("[PASS] UI 8K/4K 快速選鈕與詳細選單連動測試通過！")

    def test_hardware_to_software_fallback_on_failure(self):
        """
        驗證當硬體編碼器報錯（如 UHD 770 在 8K 遇到 Error allocating output packet 或 returncode != 0）時，
        系統自動且平滑地降級為同畫質軟解 (libx265)，絕不跳過或中斷！
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            out_video = os.path.join(temp_dir, "test_fallback.mp4")
            out_chap = os.path.join(temp_dir, "test_fallback_chapters.txt")

            # 建立測試用的假圖片
            from PIL import Image

            img_path = os.path.join(temp_dir, "sample.jpg")
            img = Image.new("RGB", (100, 100), color="blue")
            img.save(img_path)

            media_list = [(MediaItem(img_path), "")]

            # 設定為 8K + 模擬之硬體編碼器 (hevc_qsv)
            cfg = RenderConfig(
                resolution="7680x4320",
                fps=30,
                vcodec="hevc_qsv",
                bitrate="10M",
                maxrate="12M",
                bufsize="20M",
                image_duration=1.0,
                concurrency=1,
            )
            engine = VideoRenderEngine(cfg)

            logs = []

            def log_collector(msg):
                logs.append(msg)

            # 模擬硬體前置沙盒檢測回傳失敗（模擬 UHD 770 遇到 Error allocating output packet）
            def mock_test_hw(vcodec, w, h, pix):
                return False, "[hevc_qsv] Error allocating the output packet"

            engine._test_hardware_encode_capability = mock_test_hw

            success = engine.render_album_to_video(
                media_list,
                out_video,
                out_chap,
                "Fallback_Test",
                log_callback=log_collector,
            )

            # 驗證整體渲染必須成功，且產出檔案
            self.assertTrue(success, "遇硬體錯誤時，降級同畫質軟解後必須成功渲染！")
            self.assertTrue(os.path.exists(out_video), "目標 8K 影片必須存在！")
            self.assertGreater(os.path.getsize(out_video), 1000, "影片大小必須有效！")

            # 驗證日誌中有記錄智慧切換訊息
            fallback_logs = [l for l in logs if "智慧相容無感切換" in l or "同畫質 CPU 軟體無損運算" in l]
            self.assertTrue(len(fallback_logs) > 0, f"應記錄智慧平滑切換日誌，實際日誌：{logs}")

            print("[PASS] 遇到硬體顯存限制自動切換 8K 同畫質軟解渲染驗證成功！")


if __name__ == "__main__":
    unittest.main()
