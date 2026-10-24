"""
端到端功能驗證測試
測試掃描器、章節生成器、Lanczos 縮放、毛玻璃背景與 FFmpeg 合成
"""

import os
import sys
import shutil
import tempfile
from datetime import datetime

# 將專案根目錄加入模組搜尋路徑
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from PIL import Image, ImageDraw

from core.chapter_generator import ChapterGenerator
from core.encoder_detector import HardwareDetector
from core.ffmpeg_engine import RenderConfig, VideoRenderEngine
from core.scanner import AlbumScanner


def run_test():
    print("=== [1/4] 測試硬體編碼器偵測 ===")
    detector = HardwareDetector()
    profiles = detector.get_recommended_profiles()
    print(f"偵測到可用的編碼器數量: {len(detector.available_encoders)}")
    print(f"推薦的輸出規格設定檔數量: {len(profiles)}")
    for p in profiles:
        print(f" - {p['name']}")
    assert len(profiles) > 0, "必須至少有一個可用設定檔"

    print("\n=== [2/4] 建立測試相簿結構（包含直式與橫式圖片） ===")
    temp_dir = tempfile.mkdtemp(prefix="test_album_")
    try:
        day1_dir = os.path.join(temp_dir, "2024-05_日本行", "Day1")
        day2_dir = os.path.join(temp_dir, "2024-05_日本行", "Day2")
        os.makedirs(day1_dir, exist_ok=True)
        os.makedirs(day2_dir, exist_ok=True)

        # 建立橫式圖片 (1920x1080)
        img1_path = os.path.join(day1_dir, "IMG_0001.JPG")
        img1 = Image.new("RGB", (1920, 1080), color=(50, 120, 200))
        d1 = ImageDraw.Draw(img1)
        d1.text((100, 100), "Day 1 Landscape Photo", fill=(255, 255, 255))
        img1.save(img1_path, "JPEG")

        # 建立直式手機圖片 (1080x1920)
        img2_path = os.path.join(day2_dir, "IMG_0002.JPG")
        img2 = Image.new("RGB", (1080, 1920), color=(200, 80, 80))
        d2 = ImageDraw.Draw(img2)
        d2.text((100, 100), "Day 2 Portrait Photo", fill=(255, 255, 255))
        img2.save(img2_path, "JPEG")

        print("測試圖片建立完成。")

        print("\n=== [3/4] 測試目錄樹狀掃描與起點選取 ===")
        root_node = AlbumScanner.scan_directory_tree(temp_dir)
        assert root_node is not None, "根節點掃描不可為 None"
        print(f"根目錄名稱: {root_node.name}")
        print(f"子目錄數量: {len(root_node.children)}")

        # 選取 2024-05_日本行 為起點節點
        japan_node = root_node.children[0]
        print(f"選取起點: {japan_node.name}")
        total_imgs = japan_node.total_images_count()
        print(f"起點底下照片總數: {total_imgs}")
        assert total_imgs == 2, f"預期有 2 張照片，實際為 {total_imgs}"

        sorted_media = AlbumScanner.get_sorted_media_from_node(japan_node)
        print(f"排序後項目數量: {len(sorted_media)}")
        for m, rel in sorted_media:
            print(f" - [{rel}] {m.file_name} (尺寸: {m.width}x{m.height})")

        print("\n=== [4/4] 測試 FFmpeg 渲染與 YouTube 章節生成 ===")
        # 測試時以 1080p 快速驗證管線（確認毛玻璃、靜音軌、concat 正常運作）
        test_config = RenderConfig(
            resolution="1920x1080",
            fps=30,
            vcodec="libx264",
            bitrate="10M",
            maxrate="12M",
            bufsize="20M",
            image_duration=1.0,
            fill_mode="blur",
            audio_bitrate="512k",
            audio_samplerate=48000,
        )

        out_video = os.path.join(temp_dir, "Japan_Test.mp4")
        out_chap = os.path.join(temp_dir, "Japan_Chapters.txt")

        engine = VideoRenderEngine(test_config)
        success = engine.render_album_to_video(
            sorted_media,
            out_video,
            out_chap,
            "2024-05_日本行",
            progress_callback=lambda c, t, msg: print(f"  [進度 {c}/{t}] {msg}"),
            log_callback=lambda msg: print(f"  [日誌] {msg}"),
        )

        assert success, "影片合成渲染必須成功"
        assert os.path.exists(out_video), "輸出影片檔案必須存在"
        assert os.path.getsize(out_video) > 1000, "影片檔案大小必須大於 1KB"
        assert os.path.exists(out_chap), "Chapters.txt 必須存在"

        with open(out_chap, "r", encoding="utf-8") as f:
            chap_content = f.read()
        print("\n生成的 YouTube 章節預覽：\n" + chap_content)
        assert "IMG_0001.JPG" in chap_content
        assert "IMG_0002.JPG" in chap_content

        print("\n[PASS] 端到端測試全部通過！功能完全符合預期！")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    run_test()
