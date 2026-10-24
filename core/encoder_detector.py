"""
硬體編碼器探測與環境設定模組
支援自動探測 Intel QSV、NVIDIA NVENC、AMD AMF 與 CPU 編碼器
特別適配 Intel UHD 770 與 Intel Core Ultra / Arc GPU (255H / 155H)
"""

import os
import shutil
import subprocess
import glob
from typing import Dict, List, Optional, Tuple


def find_ffmpeg() -> Tuple[Optional[str], Optional[str]]:
    """
    尋找系統中的 ffmpeg 與 ffprobe 可執行檔路徑。
    依序搜尋：
    1. 專案目錄下的 bin/
    2. PATH 環境變數
    3. Winget 常見安裝目錄
    """
    # 1. 檢查專案目錄
    local_ffmpeg = os.path.join(os.getcwd(), "bin", "ffmpeg.exe")
    local_ffprobe = os.path.join(os.getcwd(), "bin", "ffprobe.exe")
    if os.path.exists(local_ffmpeg):
        return local_ffmpeg, local_ffprobe if os.path.exists(local_ffprobe) else None

    # 2. 檢查系統 PATH
    ffmpeg_path = shutil.which("ffmpeg")
    ffprobe_path = shutil.which("ffprobe")
    if ffmpeg_path:
        return ffmpeg_path, ffprobe_path

    # 3. 檢查 Winget 安裝路徑
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if local_app_data:
        winget_pattern = os.path.join(
            local_app_data,
            "Microsoft",
            "WinGet",
            "Packages",
            "*FFmpeg*",
            "**",
            "ffmpeg.exe",
        )
        matches = glob.glob(winget_pattern, recursive=True)
        if matches:
            ffmpeg_path = matches[0]
            ffprobe_candidate = os.path.join(os.path.dirname(ffmpeg_path), "ffprobe.exe")
            ffprobe_path = ffprobe_candidate if os.path.exists(ffprobe_candidate) else None
            return ffmpeg_path, ffprobe_path

    return None, None


class HardwareDetector:
    """硬體加速與編碼器偵測器"""

    def __init__(self, ffmpeg_path: Optional[str] = None):
        self.ffmpeg_path = ffmpeg_path or find_ffmpeg()[0]
        self.available_encoders: List[str] = []
        self._detect_encoders()

    def _detect_encoders(self):
        if not self.ffmpeg_path or not os.path.exists(self.ffmpeg_path):
            return

        try:
            startupinfo = None
            if os.name == "nt":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            result = subprocess.run(
                [self.ffmpeg_path, "-encoders"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                startupinfo=startupinfo,
                timeout=5,
            )
            output = result.stdout

            target_encoders = [
                "av1_qsv",
                "hevc_qsv",
                "h264_qsv",
                "av1_nvenc",
                "hevc_nvenc",
                "h264_nvenc",
                "av1_amf",
                "hevc_amf",
                "h264_amf",
                "libsvtav1",
                "libx265",
                "libx264",
            ]

            for enc in target_encoders:
                if f" {enc} " in output:
                    self.available_encoders.append(enc)
        except Exception:
            pass

    def get_recommended_profiles(self) -> List[Dict]:
        """
        傳回推薦的輸出設定檔清單，優先推薦最高規格箱子（8K / 4K 極致品質與硬體加速）
        """
        profiles = []

        # 檢查是否有 Intel QSV AV1 (例如 Core Ultra 255H / 155H Arc GPU)
        has_qsv_av1 = "av1_qsv" in self.available_encoders
        has_qsv_hevc = "hevc_qsv" in self.available_encoders
        has_nvenc_av1 = "av1_nvenc" in self.available_encoders
        has_nvenc_hevc = "hevc_nvenc" in self.available_encoders

        # 1. 8K 極致規格 (最高流量 240Mbps, 60fps, 10-bit 色深, Lanczos 銳利縮放)
        if has_qsv_av1:
            profiles.append({
                "id": "8k_qsv_av1",
                "name": "【8K 極速旗艦】8K 60FPS (Intel Arc AV1 10-bit 硬體極速, 240Mbps)",
                "resolution": "7680x4320",
                "fps": 60,
                "vcodec": "av1_qsv",
                "pix_fmt": "p010le",
                "bitrate": "240M",
                "maxrate": "260M",
                "bufsize": "480M",
                "tag": "YouTube 8K 終極推薦 (255H 筆電專屬狂飆)",
                "extra_args": ["-load_plugin", "hevc_hw"],
            })
        elif has_nvenc_av1:
            profiles.append({
                "id": "8k_nvenc_av1",
                "name": "【8K 極速旗艦】8K 60FPS (NVIDIA NVENC AV1 10-bit, 240Mbps)",
                "resolution": "7680x4320",
                "fps": 60,
                "vcodec": "av1_nvenc",
                "pix_fmt": "p010le",
                "bitrate": "240M",
                "maxrate": "260M",
                "bufsize": "480M",
                "tag": "YouTube 8K 旗艦 (NVIDIA 40系顯卡加速)",
                "extra_args": ["-preset", "p6", "-tune", "hq"],
            })

        # 8K CPU 軟體無損級旗艦 (任何電腦均可執行，包含 UHD 770)
        profiles.append({
            "id": "8k_cpu_hevc",
            "name": "【8K 極致畫質 (CPU)】8K 60FPS (HEVC 10-bit 視覺無損, 240Mbps)",
            "resolution": "7680x4320",
            "fps": 60,
            "vcodec": "libx265",
            "pix_fmt": "yuv420p10le",
            "bitrate": "240M",
            "maxrate": "260M",
            "bufsize": "480M",
            "tag": "UHD 770 可夜間排程 / 畫質最頂級無失真",
            "extra_args": ["-preset", "medium", "-x265-params", "crf=16:aq-mode=3"],
        })

        # 2. 4K QSV 雙引擎極速模式 (Intel UHD 770 桌機極致推薦！)
        if has_qsv_hevc:
            profiles.append({
                "id": "4k_qsv_hevc",
                "name": "【4K 極速旗艦 (UHD 770 專屬)】4K 60FPS (Intel QSV HEVC 10-bit, 100Mbps)",
                "resolution": "3840x2160",
                "fps": 60,
                "vcodec": "hevc_qsv",
                "pix_fmt": "p010le",
                "bitrate": "100M",
                "maxrate": "120M",
                "bufsize": "200M",
                "tag": "UHD 770 雙引擎全速狂飆 (YT 自動給予 VP9/AV1 高位元率)",
                "extra_args": ["-load_plugin", "hevc_hw"],
            })

        # 4K NVENC
        if has_nvenc_hevc:
            profiles.append({
                "id": "4k_nvenc_hevc",
                "name": "【4K 極速旗艦 (NVIDIA)】4K 60FPS (NVENC HEVC 10-bit, 100Mbps)",
                "resolution": "3840x2160",
                "fps": 60,
                "vcodec": "hevc_nvenc",
                "pix_fmt": "p010le",
                "bitrate": "100M",
                "maxrate": "120M",
                "bufsize": "200M",
                "tag": "NVIDIA 硬體加速極速輸出",
                "extra_args": ["-preset", "p6", "-tune", "hq"],
            })

        return profiles
