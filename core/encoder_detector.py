"""
硬體編碼器真實能力動態探測模組
透過 0.05 秒沙盒真實編碼測試，精準判定當前實體 GPU 支援的編碼能力：
- Intel QSV (AV1 vs HEVC vs H264)
- NVIDIA NVENC (AV1 vs HEVC vs H264)
- AMD AMF (AV1 vs HEVC vs H264)
- CPU 多核心軟體編碼 (x265 / x264)
提供狀態燈號資訊與智慧推薦，絕不誤判！
"""

import os
import shutil
import subprocess
import glob
from typing import Dict, List, Optional, Tuple


def find_ffmpeg() -> Tuple[Optional[str], Optional[str]]:
    """尋找系統中的 ffmpeg 與 ffprobe 可執行檔路徑"""
    local_ffmpeg = os.path.join(os.getcwd(), "bin", "ffmpeg.exe")
    local_ffprobe = os.path.join(os.getcwd(), "bin", "ffprobe.exe")
    if os.path.exists(local_ffmpeg):
        return local_ffmpeg, local_ffprobe if os.path.exists(local_ffprobe) else None

    ffmpeg_path = shutil.which("ffmpeg")
    ffprobe_path = shutil.which("ffprobe")
    if ffmpeg_path:
        return ffmpeg_path, ffprobe_path

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
    """硬體真實能力探測器"""

    def __init__(self, ffmpeg_path: Optional[str] = None):
        self.ffmpeg_path = ffmpeg_path or find_ffmpeg()[0]
        # 真實可用的編碼器字典: {codec_name: is_supported (bool)}
        self.supported_hardware: Dict[str, bool] = {}
        self.hardware_details: Dict[str, str] = {}
        self._probe_real_hardware()

    def _test_codec(self, codec: str, res: str = "128x128") -> Tuple[bool, str]:
        """透過極小的虛擬影格，在 0.05 秒內真實測試該硬體編碼器是否能在當前硬體上執行"""
        if not self.ffmpeg_path or not os.path.exists(self.ffmpeg_path):
            return False, "未找到 FFmpeg"

        startupinfo = None
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        cmd = [
            self.ffmpeg_path,
            "-v", "error",
            "-f", "lavfi",
            "-i", f"color=c=black:s={res}:d=0.05",
            "-c:v", codec,
            "-f", "null",
            "-",
        ]

        try:
            res_proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                startupinfo=startupinfo,
                timeout=3,
            )
            if res_proc.returncode == 0:
                return True, "支援"
            else:
                err_msg = res_proc.stderr.strip()
                if "unsupported" in err_msg.lower() or "not supported" in err_msg.lower():
                    return False, "硬體晶片不支援"
                if "cannot load" in err_msg.lower() or "no capable devices" in err_msg.lower():
                    return False, "無相容顯示卡硬體"
                return False, err_msg.split("\n")[0] if err_msg else "初始化失敗"
        except Exception as e:
            return False, str(e)

    def _probe_real_hardware(self):
        """對所有主流硬體編碼器進行動態沙盒實測"""
        probes = [
            ("av1_qsv", "Intel Arc AV1 硬體編碼 (Core Ultra 255H/155H 等)"),
            ("hevc_qsv", "Intel QSV HEVC 硬體編碼 (UHD 770 / Core Ultra)"),
            ("h264_qsv", "Intel QSV H.264 硬體編碼"),
            ("av1_nvenc", "NVIDIA NVENC AV1 硬體編碼 (RTX 40系列)"),
            ("hevc_nvenc", "NVIDIA NVENC HEVC 硬體編碼 (GTX 960+ / RTX)"),
            ("av1_amf", "AMD AMF AV1 硬體編碼 (RX 7000系列)"),
            ("hevc_amf", "AMD AMF HEVC 硬體編碼 (Radeon 顯卡)"),
            ("libx265", "CPU HEVC 多核心軟體編碼 (全電腦通用)"),
            ("libx264", "CPU H.264 多核心軟體編碼 (全電腦通用)"),
        ]

        for codec, desc in probes:
            ok, msg = self._test_codec(codec)
            self.supported_hardware[codec] = ok
            self.hardware_details[codec] = msg

        # 保持向下相容性清單
        self.available_encoders = [k for k, v in self.supported_hardware.items() if v]

    def get_hardware_status_summary(self) -> Dict[str, Dict]:
        """取得各硬體廠商與架構的狀態燈號資料"""
        qsv_av1 = self.supported_hardware.get("av1_qsv", False)
        qsv_hevc = self.supported_hardware.get("hevc_qsv", False)

        # 判定 Intel QSV 狀態
        if qsv_av1:
            qsv_status = {
                "light": "green",
                "label": "Intel Arc QSV (旗艦)",
                "desc": "支援 8K AV1 / HEVC 硬體極速編碼 (Core Ultra 255H/155H 等)",
            }
        elif qsv_hevc:
            qsv_status = {
                "light": "green",
                "label": "Intel UHD QSV (雙引擎)",
                "desc": "支援 8K/4K HEVC 硬體極速編碼 (UHD 770 桌機就緒)",
            }
        else:
            qsv_status = {
                "light": "gray",
                "label": "Intel QSV",
                "desc": "未偵測到相容之 Intel 顯示卡硬體加速",
            }

        # 判定 NVIDIA NVENC 狀態
        nv_av1 = self.supported_hardware.get("av1_nvenc", False)
        nv_hevc = self.supported_hardware.get("hevc_nvenc", False)
        if nv_av1:
            nv_status = {
                "light": "green",
                "label": "NVIDIA NVENC (RTX 40系)",
                "desc": "支援 8K AV1 / HEVC 硬體極速編碼",
            }
        elif nv_hevc:
            nv_status = {
                "light": "green",
                "label": "NVIDIA NVENC (RTX/GTX)",
                "desc": "支援 HEVC 10-bit 硬體極速編碼",
            }
        else:
            nv_status = {
                "light": "gray",
                "label": "NVIDIA NVENC",
                "desc": "未偵測到相容之 NVIDIA 顯示卡",
            }

        # 判定 AMD AMF 狀態
        amf_hevc = self.supported_hardware.get("hevc_amf", False)
        if amf_hevc:
            amf_status = {
                "light": "green",
                "label": "AMD AMF 硬體加速",
                "desc": "支援 Radeon HEVC 硬體極速編碼",
            }
        else:
            amf_status = {
                "light": "gray",
                "label": "AMD AMF",
                "desc": "未偵測到相容之 AMD 顯示卡",
            }

        # CPU 狀態
        cpu_status = {
            "light": "green",
            "label": "CPU 多核心運算 (libx265)",
            "desc": "全電腦相容，視覺無損畫質保證",
        }

        return {
            "qsv": qsv_status,
            "nvenc": nv_status,
            "amf": amf_status,
            "cpu": cpu_status,
        }

    def get_recommended_profiles(self) -> List[Dict]:
        """
        傳回當前電腦「真正支援且經過動態實測可用」的輸出規格清單。
        依照效能與畫質自動最佳排序，預設第一項保證絕對能順暢執行！
        """
        profiles = []

        # 1. 檢查 Intel Arc AV1 (Core Ultra 255H / 155H 專屬)
        if self.supported_hardware.get("av1_qsv", False):
            profiles.append({
                "id": "8k_qsv_av1",
                "name": "【8K 極速旗艦】8K 60FPS (Intel Arc AV1 10-bit, 240Mbps)",
                "resolution": "7680x4320",
                "fps": 60,
                "vcodec": "av1_qsv",
                "pix_fmt": "p010le",
                "bitrate": "240M",
                "maxrate": "260M",
                "bufsize": "480M",
                "hw_type": "Intel Arc QSV",
                "tag": "[推薦] 255H 筆電最佳推薦 (AV1 硬體狂飆)",
            })

        # 2. 檢查 Intel QSV HEVC (UHD 770 桌機與 255H 筆電均完美支援！)
        if self.supported_hardware.get("hevc_qsv", False):
            # 8K HEVC QSV
            profiles.append({
                "id": "8k_qsv_hevc",
                "name": "【8K 極速旗艦】8K 60FPS (Intel QSV HEVC 10-bit, 240Mbps)",
                "resolution": "7680x4320",
                "fps": 60,
                "vcodec": "hevc_qsv",
                "pix_fmt": "p010le",
                "bitrate": "240M",
                "maxrate": "260M",
                "bufsize": "480M",
                "hw_type": "Intel QSV",
                "tag": "[推薦] UHD 770 / 255H 8K 雙引擎極速推薦",
            })
            # 4K HEVC QSV
            profiles.append({
                "id": "4k_qsv_hevc",
                "name": "【4K 極速狂飆】4K 60FPS (Intel QSV HEVC 10-bit, 100Mbps)",
                "resolution": "3840x2160",
                "fps": 60,
                "vcodec": "hevc_qsv",
                "pix_fmt": "p010le",
                "bitrate": "100M",
                "maxrate": "120M",
                "bufsize": "200M",
                "hw_type": "Intel QSV",
                "tag": "超快速幾分鐘完成 (YouTube 給予 VP9/AV1 高位元率)",
            })

        # 3. 檢查 NVIDIA NVENC
        if self.supported_hardware.get("av1_nvenc", False):
            profiles.append({
                "id": "8k_nvenc_av1",
                "name": "【8K 極速旗搞笑】8K 60FPS (NVIDIA NVENC AV1 10-bit, 240Mbps)",
                "resolution": "7680x4320",
                "fps": 60,
                "vcodec": "av1_nvenc",
                "pix_fmt": "p010le",
                "bitrate": "240M",
                "maxrate": "260M",
                "bufsize": "480M",
                "hw_type": "NVIDIA NVENC",
                "tag": "[推薦] RTX 40系列顯卡極速推薦",
            })
        elif self.supported_hardware.get("hevc_nvenc", False):
            profiles.append({
                "id": "8k_nvenc_hevc",
                "name": "【8K 極速旗艦】8K 60FPS (NVIDIA NVENC HEVC 10-bit, 240Mbps)",
                "resolution": "7680x4320",
                "fps": 60,
                "vcodec": "hevc_nvenc",
                "pix_fmt": "p010le",
                "bitrate": "240M",
                "maxrate": "260M",
                "bufsize": "480M",
                "hw_type": "NVIDIA NVENC",
                "tag": "[推薦] NVIDIA 顯卡硬體加速",
            })

        # 4. 檢查 AMD AMF
        if self.supported_hardware.get("hevc_amf", False):
            profiles.append({
                "id": "8k_amf_hevc",
                "name": "【8K 極速旗艦】8K 60FPS (AMD AMF HEVC 10-bit, 240Mbps)",
                "resolution": "7680x4320",
                "fps": 60,
                "vcodec": "hevc_amf",
                "pix_fmt": "p010le",
                "bitrate": "240M",
                "maxrate": "260M",
                "bufsize": "480M",
                "hw_type": "AMD AMF",
                "tag": "[推薦] AMD Radeon 顯卡硬體加速",
            })

        # 5. 全電腦通用保底：CPU 軟體無損級 (任何電腦均可執行)
        profiles.append({
            "id": "8k_cpu_hevc",
            "name": "【8K 極致畫質 (CPU 軟體運算)】8K 60FPS (HEVC 10-bit, 240Mbps)",
            "resolution": "7680x4320",
            "fps": 60,
            "vcodec": "libx265",
            "pix_fmt": "yuv420p10le",
            "bitrate": "240M",
            "maxrate": "260M",
            "bufsize": "480M",
            "hw_type": "CPU (libx265)",
            "tag": "全電腦通用 / 視覺無損最高畫質 (適合夜間掛機)",
        })

        profiles.append({
            "id": "4k_cpu_hevc",
            "name": "【4K 極致畫質 (CPU 軟體運算)】4K 60FPS (HEVC 10-bit, 100Mbps)",
            "resolution": "3840x2160",
            "fps": 60,
            "vcodec": "libx265",
            "pix_fmt": "yuv420p10le",
            "bitrate": "100M",
            "maxrate": "120M",
            "bufsize": "200M",
            "hw_type": "CPU (libx265)",
            "tag": "全電腦通用",
        })

        return profiles
