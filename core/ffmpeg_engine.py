"""
FFmpeg 8K/4K 極致品質影片渲染引擎
支援智慧毛玻璃填充、Lanczos 頂級縮放、48kHz 512kbps 最高音訊規格、
GOP 關鍵影格強制插入（確保截圖零失真）、分段快取與無損 Concat 合成。
"""

import os
import shutil
import subprocess
import tempfile
import time
from typing import Callable, Dict, List, Optional, Tuple
from core.chapter_generator import ChapterGenerator
from core.encoder_detector import find_ffmpeg
from core.scanner import MediaItem


class RenderConfig:
    """渲染輸出設定規格"""

    def __init__(
        self,
        resolution: str = "7680x4320",      # 8K UHD
        fps: int = 60,                     # 60 FPS 最高幀率
        vcodec: str = "hevc_qsv",          # 預設編碼器
        bitrate: str = "240M",             # 最高流量 240 Mbps
        maxrate: str = "260M",
        bufsize: str = "480M",
        image_duration: float = 3.0,       # 照片停留秒數
        fill_mode: str = "blur",           # 'blur' (毛玻璃) 或 'black' (黑邊)
        show_watermark: bool = True,       # 是否在角落顯示微小檔名與時間
        audio_bitrate: str = "512k",       # 最高規格 512 kbps 立體聲
        audio_samplerate: int = 48000,     # 48 kHz 高解析度取樣率
    ):
        self.resolution = resolution
        self.width, self.height = map(int, resolution.split("x"))
        self.fps = fps
        self.vcodec = vcodec
        self.bitrate = bitrate
        self.maxrate = maxrate
        self.bufsize = bufsize
        self.image_duration = image_duration
        self.fill_mode = fill_mode
        self.show_watermark = show_watermark
        self.audio_bitrate = audio_bitrate
        self.audio_samplerate = audio_samplerate


class VideoRenderEngine:
    """影片渲染引擎"""

    def __init__(self, config: RenderConfig, ffmpeg_path: Optional[str] = None):
        self.config = config
        self.ffmpeg_path, self.ffprobe_path = find_ffmpeg()
        if ffmpeg_path:
            self.ffmpeg_path = ffmpeg_path
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def _get_video_duration(self, video_path: str) -> float:
        """使用 ffprobe 取得影片的精準長度（秒）"""
        if not self.ffprobe_path or not os.path.exists(self.ffprobe_path):
            return 10.0

        try:
            startupinfo = None
            if os.name == "nt":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            cmd = [
                self.ffprobe_path,
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                video_path,
            ]
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                startupinfo=startupinfo,
                timeout=10,
            )
            return float(res.stdout.strip())
        except Exception:
            return 10.0

    def render_album_to_video(
        self,
        media_list: List[Tuple[MediaItem, str]],
        output_video_path: str,
        output_chapter_path: str,
        target_title: str,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        log_callback: Optional[Callable[[str], None]] = None,
    ) -> bool:
        """
        將已排序的媒體清單合成為單一最高規格 8K/4K 備份影片。
        採用分段標準化處理，確保高穩定度、不爆記憶體、無失真。
        """
        if not self.ffmpeg_path or not os.path.exists(self.ffmpeg_path):
            if log_callback:
                log_callback("【錯誤】未找到 FFmpeg 核心程式！請先確認安裝。")
            return False

        self._is_cancelled = False
        os.makedirs(os.path.dirname(os.path.abspath(output_video_path)), exist_ok=True)

        temp_dir = os.path.join(
            os.path.dirname(os.path.abspath(output_video_path)),
            f"_temp_render_{int(time.time())}",
        )
        os.makedirs(temp_dir, exist_ok=True)

        chapter_gen = ChapterGenerator(target_title)
        current_time_sec = 0.0
        segment_files: List[str] = []
        total_items = len(media_list)

        if log_callback:
            log_callback(
                f"開始處理備份任務：『{target_title}』，共 {total_items} 個項目\n"
                f"目標畫質規格：{self.config.resolution} @ {self.config.fps}fps, 流量 {self.config.bitrate}\n"
                f"音訊規格：AAC {self.config.audio_bitrate} @ {self.config.audio_samplerate}Hz\n"
            )

        try:
            startupinfo = None
            if os.name == "nt":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            for idx, (item, rel_dir) in enumerate(media_list):
                if self._is_cancelled:
                    if log_callback:
                        log_callback("【任務已取消】使用者終止了處理程序。")
                    return False

                item_filename = item.file_name
                # 更新章節時間
                chapter_gen.add_entry(current_time_sec, item_filename, rel_dir)

                # 準備分段輸出檔案路徑
                seg_output = os.path.join(temp_dir, f"seg_{idx:05d}.mp4")

                if item.is_image:
                    item_duration = self.config.image_duration
                    current_time_sec += item_duration
                    if progress_callback:
                        progress_callback(
                            idx + 1,
                            total_items,
                            f"處理照片 ({idx + 1}/{total_items})：{item_filename}",
                        )
                    success = self._render_image_segment(
                        item, seg_output, item_duration, startupinfo, log_callback
                    )
                else:
                    vid_dur = self._get_video_duration(item.file_path)
                    item_duration = max(vid_dur, 0.5)
                    current_time_sec += item_duration
                    if progress_callback:
                        progress_callback(
                            idx + 1,
                            total_items,
                            f"處理影片 ({idx + 1}/{total_items})：{item_filename}",
                        )
                    success = self._render_video_segment(
                        item, seg_output, startupinfo, log_callback
                    )

                if not success:
                    if log_callback:
                        log_callback(f"【警告】項目 {item_filename} 渲染失敗，將嘗試繼續。")
                    continue

                segment_files.append(seg_output)

            if not segment_files:
                if log_callback:
                    log_callback("【錯誤】無成功渲染的片段，無法產生最終影片。")
                return False

            # 產生 YouTube 章節檔案
            chapter_gen.save_to_file(output_chapter_path)
            if log_callback:
                log_callback(f"[OK] YouTube 章節索引檔案已建立：{output_chapter_path}")

            # 合併所有片段為單一巨大影片
            if progress_callback:
                progress_callback(total_items, total_items, "正在進行無損極速封裝合併...")
            if log_callback:
                log_callback("正在將所有標準化片段進行無損合併...")

            concat_list_file = os.path.join(temp_dir, "concat_list.txt")
            with open(concat_list_file, "w", encoding="utf-8") as f:
                for seg in segment_files:
                    # Windows 路徑格式處理
                    formatted_path = seg.replace("\\", "/")
                    f.write(f"file '{formatted_path}'\n")

            # 執行 Concat Demuxer（極速直接複製串接，不二次轉碼）
            concat_cmd = [
                self.ffmpeg_path,
                "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", concat_list_file,
                "-c", "copy",
                "-movflags", "+faststart",
                output_video_path,
            ]

            process = subprocess.run(
                concat_cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                startupinfo=startupinfo,
            )

            if process.returncode != 0:
                if log_callback:
                    log_callback(f"【合併錯誤】{process.stderr}")
                return False

            if log_callback:
                log_callback(f"[完成] 單一極致備份影片已成功建立：{output_video_path}")
            return True

        finally:
            # 清理暫存資料夾
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass

    def _render_image_segment(
        self,
        item: MediaItem,
        output_file: str,
        duration: float,
        startupinfo,
        log_callback,
    ) -> bool:
        """
        將單張相片渲染為標準規格的 8K/4K 60fps 獨立片段：
        - 採用 Lanczos 頂級縮放演算法
        - 智慧毛玻璃模糊背景
        - 自動注入 48kHz 512kbps 靜音軌
        - 強制插入 IDR 關鍵幀（截圖最少失真化）
        """
        w, h = self.config.width, self.config.height
        fps = self.config.fps

        # 毛玻璃背景濾鏡鏈
        if self.config.fill_mode == "blur":
            filter_complex = (
                f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase:flags=bicubic,"
                f"crop={w}:{h},boxblur=40:5[bg];"
                f"[0:v]scale={w}:{h}:force_original_aspect_ratio=decrease:flags=lanczos+accurate_rnd[fg];"
                f"[bg][fg]overlay=(W-w)/2:(H-h)/2[v]"
            )
        else:
            # 黑邊模式
            filter_complex = (
                f"[0:v]scale={w}:{h}:force_original_aspect_ratio=decrease:flags=lanczos+accurate_rnd,"
                f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black[v]"
            )

        cmd = [
            self.ffmpeg_path,
            "-y",
            "-loop", "1",
            "-t", str(duration),
            "-i", item.file_path,
            # 加入最高規格靜音軌
            "-f", "lavfi",
            "-t", str(duration),
            "-i", f"anullsrc=r={self.config.audio_samplerate}:cl=stereo",
            "-filter_complex", filter_complex,
            "-map", "[v]",
            "-map", "1:a",
            "-c:v", self.config.vcodec,
            "-b:v", self.config.bitrate,
            "-maxrate", self.config.maxrate,
            "-bufsize", self.config.bufsize,
            "-r", str(fps),
            # 強制關鍵影格間隔（GOP = 1 秒，確保精準截圖）
            "-g", str(fps),
            "-keyint_min", str(fps),
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", self.config.audio_bitrate,
            "-ar", str(self.config.audio_samplerate),
            "-t", str(duration),
            output_file,
        ]

        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                startupinfo=startupinfo,
            )
            return res.returncode == 0
        except Exception as e:
            if log_callback:
                log_callback(f"照片渲染異常：{e}")
            return False

    def _render_video_segment(
        self,
        item: MediaItem,
        output_file: str,
        startupinfo,
        log_callback,
    ) -> bool:
        """
        將一段既有影片標準化為相同的 8K/4K 60fps 格式，音訊標準化為 48kHz AAC
        """
        w, h = self.config.width, self.config.height
        fps = self.config.fps

        if self.config.fill_mode == "blur":
            filter_complex = (
                f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase:flags=bicubic,"
                f"crop={w}:{h},boxblur=40:5[bg];"
                f"[0:v]scale={w}:{h}:force_original_aspect_ratio=decrease:flags=lanczos+accurate_rnd[fg];"
                f"[bg][fg]overlay=(W-w)/2:(H-h)/2[v]"
            )
        else:
            filter_complex = (
                f"[0:v]scale={w}:{h}:force_original_aspect_ratio=decrease:flags=lanczos+accurate_rnd,"
                f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black[v]"
            )

        cmd = [
            self.ffmpeg_path,
            "-y",
            "-i", item.file_path,
            "-filter_complex", filter_complex,
            "-map", "[v]",
            "-map", "0:a?",
            "-c:v", self.config.vcodec,
            "-b:v", self.config.bitrate,
            "-maxrate", self.config.maxrate,
            "-bufsize", self.config.bufsize,
            "-r", str(fps),
            "-g", str(fps),
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", self.config.audio_bitrate,
            "-ar", str(self.config.audio_samplerate),
            output_file,
        ]

        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                startupinfo=startupinfo,
            )
            return res.returncode == 0
        except Exception as e:
            if log_callback:
                log_callback(f"影片渲染異常：{e}")
            return False
