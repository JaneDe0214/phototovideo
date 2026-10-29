import os
import unittest
from core.ffmpeg_engine import (
    RenderConfig,
    VideoRenderEngine,
    PHOTO_BITRATE_RATIO,
    VIDEO_BITRATE_RATIO,
    AUDIO_BITRATE_KBPS,
)
from core.scanner import MediaItem


class DummyMediaItem:
    def __init__(self, file_path: str, is_image: bool = True, duration: float = 0.0):
        self.file_path = file_path
        self.file_name = os.path.basename(file_path)
        self.is_image = is_image
        self.is_video = not is_image
        self.duration = duration
        self.file_size = 1024 * 1024


class TestAccurateCapacityAndSplit(unittest.TestCase):
    """測試相片與影片精準容量模型及防提前切檔機制"""

    def test_bitrate_ratios_constants(self):
        """驗證相片與影片加權壓縮常數設定"""
        self.assertEqual(PHOTO_BITRATE_RATIO, 0.52)
        self.assertEqual(VIDEO_BITRATE_RATIO, 0.92)
        self.assertEqual(AUDIO_BITRATE_KBPS, 512.0)

    def test_accurate_capacity_estimation(self):
        """驗證精準容量計算：相片約52%，影片約92%"""
        config = RenderConfig(
            bitrate="240M",
            image_duration=3.0,
            enable_auto_split=True,
            max_size_gb=240.0,
            max_duration_seconds=42000.0,
        )
        engine = VideoRenderEngine(config)
        bitrate_num = 240
        gb_per_sec = bitrate_num / (8 * 1024)

        img_item = DummyMediaItem("photo.jpg", is_image=True)
        img_size_gb = engine.estimate_media_item_size_gb(img_item, 3.0, gb_per_sec)

        vid_item = DummyMediaItem("clip.mp4", is_image=False, duration=10.0)
        vid_size_gb = engine.estimate_media_item_size_gb(vid_item, 10.0, gb_per_sec)

        # 相片 3 秒 理論上限約 0.0879 GB，精準估計約 0.0458 GB (約 52%)
        theoretical_img = 3.0 * gb_per_sec
        self.assertAlmostEqual(img_size_gb / theoretical_img, 0.52, delta=0.01)

        # 影片 10 秒 理論上限約 0.293 GB，精準估計約 0.270 GB (約 92%)
        theoretical_vid = 10.0 * gb_per_sec
        self.assertAlmostEqual(vid_size_gb / theoretical_vid, 0.92, delta=0.01)

    def test_no_premature_split_for_photos(self):
        """驗證痛點修正：3,000 張相片（理論極限263GB但真實容量137GB、時間2.5小時）絕不提前切檔！"""
        config = RenderConfig(
            bitrate="240M",
            image_duration=3.0,
            enable_auto_split=True,
            max_size_gb=240.0,
            max_duration_seconds=42000.0,  # 11.6 小時
        )
        engine = VideoRenderEngine(config)

        # 模擬 3,000 張相片，總時長 9,000 秒 (2.5小時)
        # 舊邏輯：9,000 * (240 / 8192) = 263.67 GB > 240GB -> 誤切成 Part 1 (120GB) 和 Part 2
        # 新精準邏輯：263.67 * 0.52 = 137.1 GB < 240GB 且 2.5小時 < 11.6小時 -> 完美合併為單一影片！
        dummy_media = [(DummyMediaItem(f"img_{i:04d}.jpg", is_image=True), "") for i in range(3000)]
        parts = engine.split_media_into_parts(dummy_media)

        self.assertEqual(
            len(parts),
            1,
            f"3,000 張相片實際容量約 137GB，未達 240GB 且時間未超過限制，必須為單一 Part，實際切為 {len(parts)} 個！",
        )

    def test_normal_split_when_actual_limit_exceeded(self):
        """驗證當真正超過實際容量限制或時間限制時，依然精準切檔"""
        config = RenderConfig(
            bitrate="240M",
            image_duration=3.0,
            enable_auto_split=True,
            max_size_gb=240.0,
            max_duration_seconds=42000.0,
        )
        engine = VideoRenderEngine(config)

        # 模擬 6,000 張相片，總時長 18,000 秒 (5小時)，真實容量約 274 GB > 240 GB
        dummy_media = [(DummyMediaItem(f"img_{i:04d}.jpg", is_image=True), "") for i in range(6000)]
        parts = engine.split_media_into_parts(dummy_media)

        self.assertGreater(len(parts), 1, "真實預估容量達 274GB 時必須安全切分 Parts")
        # 檢查第一 Part 是否充分填滿接近 240GB 而非只有 120GB 就切
        self.assertGreaterEqual(len(parts[0]), 5000, "Part 1 應容納超過 5,000 張相片，充分利用上限頻寬")

    def test_video_duration_cache(self):
        """驗證影片時長快取機制運作正常"""
        config = RenderConfig()
        engine = VideoRenderEngine(config)

        # 手動注入快取
        engine._video_duration_cache["test_video.mp4"] = 42.5
        dur = engine._get_video_duration("test_video.mp4")
        self.assertEqual(dur, 42.5)


if __name__ == "__main__":
    unittest.main()
