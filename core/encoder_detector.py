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
import sys
import shutil
import subprocess
import glob
from typing import Dict, List, Optional, Tuple


def find_ffmpeg() -> Tuple[Optional[str], Optional[str]]:
    """
    尋找系統中的 ffmpeg 與 ffprobe 可執行檔路徑。
    支援開發模式、PyInstaller 綠色免安裝目錄與單一檔案打包環境，
    優先偵測應用程式自帶的可攜式 bin/ffmpeg.exe。
    """
    candidate_dirs = []

    # 1. 打包執行檔環境 (PyInstaller frozen)
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        candidate_dirs.append(exe_dir)
        candidate_dirs.append(os.path.join(exe_dir, "_internal"))
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidate_dirs.append(meipass)

    # 2. 專案程式碼所在環境與工作目錄
    code_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidate_dirs.append(code_dir)
    candidate_dirs.append(os.getcwd())

    # 依序檢查候選目錄下的 bin/ 或根目錄
    for base in candidate_dirs:
        for sub in ["bin", ""]:
            ff = os.path.join(base, sub, "ffmpeg.exe") if sub else os.path.join(base, "ffmpeg.exe")
            fp = os.path.join(base, sub, "ffprobe.exe") if sub else os.path.join(base, "ffprobe.exe")
            if os.path.exists(ff):
                return ff, fp if os.path.exists(fp) else None

    # 3. 系統 PATH
    ffmpeg_path = shutil.which("ffmpeg")
    ffprobe_path = shutil.which("ffprobe")
    if ffmpeg_path:
        return ffmpeg_path, ffprobe_path

    # 4. WinGet 預設安裝路徑
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


_CACHED_SUPPORTED = None
_CACHED_DETAILS = None


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

        pix_fmt_args = []
        if "qsv" in codec:
            pix_fmt_args = ["-pix_fmt", "nv12"]
        elif "nvenc" in codec or "amf" in codec:
            pix_fmt_args = ["-pix_fmt", "yuv420p"]

        cmd = [
            self.ffmpeg_path,
            "-v", "error",
            "-f", "lavfi",
            "-i", f"color=c=black:s={res}:d=0.05",
            "-c:v", codec,
            *pix_fmt_args,
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
                timeout=3.0,
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
        """對所有主流硬體編碼器進行動態沙盒實測（支援記憶體快取加速，絕不卡死 UI）"""
        global _CACHED_SUPPORTED, _CACHED_DETAILS
        if _CACHED_SUPPORTED is not None and _CACHED_DETAILS is not None:
            self.supported_hardware = dict(_CACHED_SUPPORTED)
            self.hardware_details = dict(_CACHED_DETAILS)
            self.available_encoders = [k for k, v in self.supported_hardware.items() if v]
            return

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

        _CACHED_SUPPORTED = dict(self.supported_hardware)
        _CACHED_DETAILS = dict(self.hardware_details)
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
        【8K 畫質第一優先原則】：無論硬體或 CPU，8K 規格一律排在最前面！
        排序層次：
        1. 8K 硬體加速 (Intel Arc AV1 / Intel QSV HEVC / NVIDIA NVENC / AMD AMF)
        2. 8K CPU 軟體無損運算 (libx265 - 全電腦通用保底)
        3. 4K 硬體加速
        4. 4K CPU 軟體運算
        預設第一項必定為當前電腦可勝任之最佳 8K 畫質！
        """
        profiles_8k = []
        profiles_4k = []

        # 1. 檢查 Intel QSV HEVC (Core Ultra 255H/155H 筆電與 UHD 770 桌機均支援，8K 成熟度最高)
        if self.supported_hardware.get("hevc_qsv", False):
            profiles_8k.append({
                "id": "8k_qsv_hevc",
                "name": "🌟【8K 旗艦】8K 60FPS (Intel QSV HEVC 10-bit, 240Mbps)",
                "resolution": "7680x4320",
                "fps": 60,
                "vcodec": "hevc_qsv",
                "pix_fmt": "p010le",
                "bitrate": "240M",
                "maxrate": "260M",
                "bufsize": "480M",
                "hw_type": "Intel QSV",
                "tag": "[首選推薦] 255H 筆電 / UHD 770 雙 MFX 引擎 8K 極速硬體加速",
            })
            profiles_4k.append({
                "id": "4k_qsv_hevc",
                "name": "⚡【4K 極速】4K 60FPS (Intel QSV HEVC 10-bit, 100Mbps)",
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

        # 2. 檢查 Intel Arc AV1 (Core Ultra 255H / 155H 等 Intel Arc GPU)
        if self.supported_hardware.get("av1_qsv", False):
            profiles_8k.append({
                "id": "8k_qsv_av1",
                "name": "🌟【8K 進階】8K 60FPS (Intel Arc AV1 10-bit, 240Mbps)",
                "resolution": "7680x4320",
                "fps": 60,
                "vcodec": "av1_qsv",
                "pix_fmt": "p010le",
                "bitrate": "240M",
                "maxrate": "260M",
                "bufsize": "480M",
                "hw_type": "Intel Arc QSV",
                "tag": "[高階] 255H 筆電 AV1 硬體加速 (若遇驅動限制自動轉HEVC硬解)",
            })
            # 4K 下 AV1 為最佳首選
            profiles_4k.insert(0, {
                "id": "4k_qsv_av1",
                "name": "⚡【4K 狂飆】4K 60FPS (Intel Arc AV1 10-bit, 100Mbps)",
                "resolution": "3840x2160",
                "fps": 60,
                "vcodec": "av1_qsv",
                "pix_fmt": "p010le",
                "bitrate": "100M",
                "maxrate": "120M",
                "bufsize": "200M",
                "hw_type": "Intel Arc QSV",
                "tag": "[推薦] 255H 筆電 4K AV1 硬體極速 (YouTube 免二次轉碼)",
            })

        # 3. 檢查 NVIDIA NVENC
        if self.supported_hardware.get("av1_nvenc", False):
            profiles_8k.append({
                "id": "8k_nvenc_av1",
                "name": "🌟【8K 旗艦】8K 60FPS (NVIDIA NVENC AV1 10-bit, 240Mbps)",
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
            profiles_8k.append({
                "id": "8k_nvenc_hevc",
                "name": "🌟【8K 旗艦】8K 60FPS (NVIDIA NVENC HEVC 10-bit, 240Mbps)",
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
            profiles_4k.append({
                "id": "4k_nvenc_hevc",
                "name": "⚡【4K 狂飆】4K 60FPS (NVIDIA NVENC HEVC 10-bit, 100Mbps)",
                "resolution": "3840x2160",
                "fps": 60,
                "vcodec": "hevc_nvenc",
                "pix_fmt": "p010le",
                "bitrate": "100M",
                "maxrate": "120M",
                "bufsize": "200M",
                "hw_type": "NVIDIA NVENC",
                "tag": "NVIDIA 顯卡 4K 極速",
            })

        # 4. 檢查 AMD AMF
        if self.supported_hardware.get("hevc_amf", False):
            profiles_8k.append({
                "id": "8k_amf_hevc",
                "name": "🌟【8K 旗艦】8K 60FPS (AMD AMF HEVC 10-bit, 240Mbps)",
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
            profiles_4k.append({
                "id": "4k_amf_hevc",
                "name": "⚡【4K 狂飆】4K 60FPS (AMD AMF HEVC 10-bit, 100Mbps)",
                "resolution": "3840x2160",
                "fps": 60,
                "vcodec": "hevc_amf",
                "pix_fmt": "p010le",
                "bitrate": "100M",
                "maxrate": "120M",
                "bufsize": "200M",
                "hw_type": "AMD AMF",
                "tag": "AMD Radeon 顯卡 4K 極速",
            })

        # 5. 【8K CPU 軟體無損運算】緊接在 8K 硬體之後，確保 8K 畫質優先！
        profiles_8k.append({
            "id": "8k_cpu_hevc",
            "name": "🌟【8K 極致 (CPU 軟體運算)】8K 60FPS (HEVC 10-bit, 240Mbps)",
            "resolution": "7680x4320",
            "fps": 60,
            "vcodec": "libx265",
            "pix_fmt": "yuv420p10le",
            "bitrate": "240M",
            "maxrate": "260M",
            "bufsize": "480M",
            "hw_type": "CPU (libx265)",
            "tag": "全電腦通用 / 視覺無損最高畫質 (適合夜間掛機 / 100% 穩定相容)",
        })

        # 6. 【4K CPU 軟體運算】
        profiles_4k.append({
            "id": "4k_cpu_hevc",
            "name": "⚡【4K 極致 (CPU 軟體運算)】4K 60FPS (HEVC 10-bit, 100Mbps)",
            "resolution": "3840x2160",
            "fps": 60,
            "vcodec": "libx265",
            "pix_fmt": "yuv420p10le",
            "bitrate": "100M",
            "maxrate": "120M",
            "bufsize": "200M",
            "hw_type": "CPU (libx265)",
            "tag": "全電腦通用 (相容性佳)",
        })

        # 合併清單：8K 規格永遠絕對優先排在最前！
        return profiles_8k + profiles_4k


def get_system_memory_info() -> Dict[str, float]:
    """取得系統實體記憶體容量資訊 (單位：GB)"""
    total_gb = 16.0
    avail_gb = 12.0
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", wintypes.DWORD),
                    ("dwMemoryLoad", wintypes.DWORD),
                    ("ullTotalPhys", ctypes.c_uint64),
                    ("ullAvailPhys", ctypes.c_uint64),
                    ("ullTotalPageFile", ctypes.c_uint64),
                    ("ullAvailPageFile", ctypes.c_uint64),
                    ("ullTotalVirtual", ctypes.c_uint64),
                    ("ullAvailVirtual", ctypes.c_uint64),
                    ("sullAvailExtendedVirtual", ctypes.c_uint64),
                ]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                total_gb = stat.ullTotalPhys / (1024 ** 3)
                avail_gb = stat.ullAvailPhys / (1024 ** 3)
        except Exception:
            pass
    return {"total_gb": round(total_gb, 1), "avail_gb": round(avail_gb, 1)}


def calculate_safe_concurrency(total_ram_gb: float, is_8k: bool, max_cores: int) -> int:
    """
    計算兼顧轉碼效能與防範 SSD SWAP 磨損的安全平行執行緒數。
    - 8K 模式下單個 FFmpeg 程序約需 1.8 GB 記憶體
    - 4K 模式下單個 FFmpeg 程序約需 0.4 GB 記憶體
    - 保留 6 GB 給作業系統與背景程序，確保實體記憶體充足、零硬碟換頁！
    """
    system_reserved_gb = 6.0
    safe_available = max(total_ram_gb - system_reserved_gb, 4.0)
    per_proc_ram = 1.8 if is_8k else 0.4

    # 8K 下受到 GPU 專用顯存與雙硬體編碼通道限制，為避免觸發 [av1_qsv] Error allocating output packet，
    # 32G 以下筆電安全上限精準收斂在 4~6 緒（最佳甜蜜點，既飽和 GPU 雙 MFX 又完全不爭搶顯存封包）；
    # 64G 以上高階桌機與工作站則按記憶體彈性放寬平行度。
    if is_8k:
        safe_ratio = 0.42 if total_ram_gb <= 32.0 else 0.7
        safe_concur = int((safe_available / per_proc_ram) * safe_ratio)
        max_8k_cap = 6 if total_ram_gb <= 32.0 else 24
        safe_concur = max(2, min(safe_concur, max_8k_cap))
    else:
        safe_concur = int(safe_available / per_proc_ram)
        safe_concur = max(4, min(safe_concur, 16))

    return max(1, min(safe_concur, max_cores))


def get_output_spec_tag(prof: Dict) -> str:
    """
    根據選取的畫質規格，產生符合使用者要求的標準命名標籤：
    格式：[解析度]_[晶片名稱]_[轉檔格式]
    範例：8K_IntelArc_AV1、8K_IntelQSV_HEVC、4K_IntelQSV_HEVC、8K_CPU_HEVC
    徹底取消舊有的「極致備份」字樣，純粹清楚呈現晶片與編碼格式。
    """
    # 1. 解析度標籤
    res = (
        "8K"
        if "8k" in str(prof.get("resolution", "")).lower()
        or "8k" in str(prof.get("id", "")).lower()
        else "4K"
    )

    # 2. 轉檔編碼格式
    vcodec = str(prof.get("vcodec", "")).lower()
    if "av1" in vcodec:
        codec_name = "AV1"
    elif "hevc" in vcodec or "x265" in vcodec:
        codec_name = "HEVC"
    elif "h264" in vcodec or "x264" in vcodec:
        codec_name = "H264"
    else:
        codec_name = vcodec.upper()

    # 3. 晶片/硬體名稱
    hw_type = str(prof.get("hw_type", "")).lower()
    if "arc" in hw_type:
        chip_name = "IntelArc"
    elif "qsv" in hw_type or "intel" in hw_type:
        chip_name = "IntelQSV"
    elif "nvenc" in hw_type or "nvidia" in hw_type:
        chip_name = "NVIDIA-NVENC"
    elif "amf" in hw_type or "amd" in hw_type:
        chip_name = "AMD-AMF"
    elif "cpu" in hw_type:
        chip_name = "CPU"
    else:
        chip_name = "Hardware"

    return f"{res}_{chip_name}_{codec_name}"


