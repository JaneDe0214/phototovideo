"""
端到端功能驗證測試
測試掃描器、章節生成器、Lanczos 縮放、毛玻璃背景、
FFmpeg 合成以及 YouTube 12 小時 / 256GB 限制自動分段功能
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
    print("=== [1/5] 測試硬體編碼器偵測 ===")
    detector = HardwareDetector()
    profiles = detector.get_recommended_profiles()
    print(f"偵測到可用的編碼器數量: {len(detector.available_encoders)}")
    print(f"推薦的輸出規格設定檔數量: {len(profiles)}")
    for p in profiles:
        print(f" - {p['name']}")
    assert len(profiles) > 0, "必須至少有一個可用設定檔"

    print("\n=== [2/5] 建立測試相簿結構（包含直式與橫式圖片） ===")
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

        print("\n=== [3/5] 測試目錄樹狀掃描與起點選取 ===")
        root_node = AlbumScanner.scan_directory_tree(temp_dir)
        assert root_node is not None, "根節點掃描不可為 None"

        japan_node = root_node.children[0]
        print(f"選取起點: {japan_node.name}")
        total_imgs = japan_node.total_images_count()
        assert total_imgs == 2, f"預期有 2 張照片，實際為 {total_imgs}"

        sorted_media = AlbumScanner.get_sorted_media_from_node(japan_node)
        print(f"排序後項目數量: {len(sorted_media)}")

        print("\n=== [4/5] 測試單一影片無分段合成 ===")
        single_config = RenderConfig(
            resolution="1280x720",
            fps=30,
            vcodec="libx264",
            bitrate="5M",
            maxrate="6M",
            bufsize="10M",
            image_duration=1.0,
            fill_mode="blur",
            enable_auto_split=False,
        )
        out_video_single = os.path.join(temp_dir, "Single_Test.mp4")
        out_chap_single = os.path.join(temp_dir, "Single_Chapters.txt")

        engine_single = VideoRenderEngine(single_config)
        res1 = engine_single.render_album_to_video(
            sorted_media,
            out_video_single,
            out_chap_single,
            "2024-05_日本行",
            log_callback=lambda msg: print(f"  [單一] {msg}"),
        )
        assert res1, "單一影片合成必須成功"
        assert os.path.exists(out_video_single), "單一影片檔案必須存在"
        assert os.path.exists(out_chap_single), "單一章節檔案必須存在"

        print("\n=== [5/5] 測試 YouTube 限制智慧自動分段（觸發切分為 Part 1, Part 2） ===")
        # 設定單部上限為 1.5 秒（兩張照片各 1 秒，總長 2 秒必定觸發切分）
        split_config = RenderConfig(
            resolution="1280x720",
            fps=30,
            vcodec="libx264",
            bitrate="5M",
            maxrate="6M",
            bufsize="10M",
            image_duration=1.0,
            fill_mode="blur",
            enable_auto_split=True,
            max_duration_seconds=1.5,
            max_size_gb=100.0,
        )

        out_video_split = os.path.join(temp_dir, "Split_Test.mp4")
        out_chap_split = os.path.join(temp_dir, "Split_Chapters.txt")

        engine_split = VideoRenderEngine(split_config)
        parts = engine_split.split_media_into_parts(sorted_media)
        print(f"分段排程分析結果：成功切分為 {len(parts)} 個 Parts")
        assert len(parts) == 2, f"預期切分為 2 個 Part，實際為 {len(parts)}"

        res2 = engine_split.render_album_to_video(
            sorted_media,
            out_video_split,
            out_chap_split,
            "2024-05_日本行",
            log_callback=lambda msg: print(f"  [分段] {msg}"),
        )
        assert res2, "分段合成必須成功"

        part1_video = os.path.join(temp_dir, "Split_Test_Part01.mp4")
        part2_video = os.path.join(temp_dir, "Split_Test_Part02.mp4")
        part1_chap = os.path.join(temp_dir, "Split_Chapters_Part01.txt")
        part2_chap = os.path.join(temp_dir, "Split_Chapters_Part02.txt")

        assert os.path.exists(part1_video), "Part 1 影片必須存在"
        assert os.path.exists(part2_video), "Part 2 影片必須存在"
        assert os.path.exists(part1_chap), "Part 1 章節檔案必須存在"
        assert os.path.exists(part2_chap), "Part 2 章節檔案必須存在"

        with open(part1_chap, "r", encoding="utf-8") as f:
            p1_text = f.read()
        print("\nPart 1 章節內容：\n" + p1_text)
        assert "Part 01/02" in p1_text

        print("\n=== [6/6] 測試自訂輸出資料夾（避免唯讀網路相簿目錄） ===")
        custom_out_dir = os.path.join(temp_dir, "Custom_Local_Output")
        os.makedirs(custom_out_dir, exist_ok=True)

        custom_video = os.path.join(custom_out_dir, "Custom_Output_8K.mp4")
        custom_chap = os.path.join(custom_out_dir, "Custom_Output_Chapters.txt")

        res3 = engine_single.render_album_to_video(
            sorted_media,
            custom_video,
            custom_chap,
            "2024-05_日本行(自訂輸出)",
            log_callback=lambda msg: print(f"  [自訂輸出] {msg}"),
        )
        assert res3, "自訂輸出目錄渲染必須成功"
        assert os.path.exists(custom_video), "自訂目錄中影片檔案必須存在"
        assert os.path.exists(custom_chap), "自訂目錄中章節檔案必須存在"
        print(f"自訂目錄檔案產出成功：{custom_video} (大小: {os.path.getsize(custom_video)} bytes)")

        print("\n[PASS] 全部測試項目全數通過！功能完全符合預期！")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    run_test()
