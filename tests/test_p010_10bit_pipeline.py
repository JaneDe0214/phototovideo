import os
import subprocess
import unittest
from core.encoder_detector import find_ffmpeg
from core.ffmpeg_engine import RenderConfig, VideoRenderEngine
from core.scanner import MediaItem


class DummyMediaItem:
    def __init__(self, file_path: str):
        self.file_path = file_path
        self.file_name = os.path.basename(file_path)
        self.is_image = True
        self.is_video = False
        self.duration = 1.0


class TestP010Pipeline(unittest.TestCase):
    """驗證最高規格 P010 10-bit (10.7億色) 最低失真渲染管線"""

    def test_render_config_p010_default(self):
        """驗證 RenderConfig 預設採用 10-bit p010le"""
        config = RenderConfig()
        self.assertEqual(config.pix_fmt, "p010le")

    def test_cmd_p010_generation_hardware(self):
        """驗證硬體加速 (QSV / NVENC) 下自動生成 p010le 與 main10 參數"""
        config = RenderConfig(vcodec="hevc_qsv", pix_fmt="p010le")
        engine = VideoRenderEngine(config)
        item = DummyMediaItem("test.jpg")
        cmd = engine._build_image_encode_cmd(
            item, "out.mp4", 1.0, "hevc_qsv", "240M", "260M", "480M"
        )
        self.assertIn("-pix_fmt", cmd)
        idx_pix = cmd.index("-pix_fmt")
        self.assertEqual(cmd[idx_pix + 1], "p010le")
        self.assertIn("-profile:v", cmd)
        idx_prof = cmd.index("-profile:v")
        self.assertEqual(cmd[idx_prof + 1], "main10")

    def test_cmd_p010_generation_cpu(self):
        """驗證 CPU 軟解 (libx265) 下自動轉譯為 yuv420p10le 與 main10 參數"""
        config = RenderConfig(vcodec="libx265", pix_fmt="p010le")
        engine = VideoRenderEngine(config)
        item = DummyMediaItem("test.jpg")
        cmd = engine._build_image_encode_cmd(
            item, "out.mp4", 1.0, "libx265", "180M", "200M", "360M"
        )
        self.assertIn("-pix_fmt", cmd)
        idx_pix = cmd.index("-pix_fmt")
        self.assertEqual(cmd[idx_pix + 1], "yuv420p10le")
        self.assertIn("-profile:v", cmd)
        idx_prof = cmd.index("-profile:v")
        self.assertEqual(cmd[idx_prof + 1], "main10")

    def test_actual_render_p010_profile(self):
        """實測渲染 10-bit 檔案並以 ffprobe 驗證其產出為 Main 10"""
        ffmpeg_path, ffprobe_path = find_ffmpeg()
        if not ffmpeg_path or not ffprobe_path:
            self.skipTest("未找到 FFmpeg/FFprobe，跳過實際硬體檢驗")

        temp_out = os.path.join(os.environ.get("TEMP", "."), "_test_p010_probe.mp4")
        if os.path.exists(temp_out):
            try:
                os.remove(temp_out)
            except Exception:
                pass

        # 透過 FFmpeg 快速產出 0.1 秒 p010le 測試片
        cmd = [
            ffmpeg_path,
            "-y",
            "-f", "lavfi",
            "-i", "color=c=blue:s=320x240:d=0.1",
            "-c:v", "libx265",
            "-profile:v", "main10",
            "-pix_fmt", "yuv420p10le",
            temp_out,
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"測試轉檔失敗: {res.stderr}")

        # 使用 ffprobe 檢查 profile
        probe_cmd = [
            ffprobe_path,
            "-v", "error",
            "-show_entries", "stream=profile,pix_fmt",
            "-of", "default=noprint_wrappers=1:nokey=1",
            temp_out,
        ]
        probe_res = subprocess.run(probe_cmd, capture_output=True, text=True)
        lines = [line.strip() for line in probe_res.stdout.split("\n") if line.strip()]

        if os.path.exists(temp_out):
            try:
                os.remove(temp_out)
            except Exception:
                pass

        self.assertIn("Main 10", lines, f"預期包含 Main 10 profile，實際回傳：{lines}")


if __name__ == "__main__":
    unittest.main()
