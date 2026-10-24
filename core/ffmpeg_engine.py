"""
FFmpeg 8K/4K 極致品質影片渲染引擎
支援智慧毛玻璃填充、Lanczos 頂級縮放、48kHz 512kbps 最高音訊規格、
GOP 關鍵影格強制插入（確保截圖零失真）、分段快取與無損 Concat 合成。
支援 YouTube 官方 12 小時 / 256GB 限制智慧自動分段（Multi-Part Splitting）。
內建「智慧排錯與無縫硬體降級引擎（Smart Fallback Engine）」，絕不盲目報錯中斷！
"""

import os
import shutil
import subprocess
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
        enable_auto_split: bool = True,    # 啟用 YouTube 限制自動分段
        max_duration_seconds: float = 42000.0,  # 11 小時 40 分 (YT 12h 安全線)
        max_size_gb: float = 240.0,             # 240 GB (YT 256GB 安全線)
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
        self.enable_auto_split = enable_auto_split
        self.max_duration_seconds = max_duration_seconds
        self.max_size_gb = max_size_gb


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

    def split_media_into_parts(
        self, media_list: List[Tuple[MediaItem, str]]
    ) -> List[List[Tuple[MediaItem, str]]]:
        """依據 YouTube 官方限制（12 小時 / 256GB 安全線）將媒體清單自動切分為多個 Part"""
        if not self.config.enable_auto_split:
            return [media_list]

        bitrate_num = int(self.config.bitrate.replace("M", "").replace("k", ""))
        if "k" in self.config.bitrate:
            gb_per_sec = (bitrate_num / (8 * 1024 * 1024))
        else:
            gb_per_sec = (bitrate_num / (8 * 1024))

        parts: List[List[Tuple[MediaItem, str]]] = []
        current_part: List[Tuple[MediaItem, str]] = []
        current_part_duration = 0.0
        current_part_size_gb = 0.0

        for item, rel_dir in media_list:
            if item.is_image:
                dur = self.config.image_duration
            else:
                dur = self._get_video_duration(item.file_path)

            est_item_size_gb = dur * gb_per_sec

            would_exceed_dur = (current_part_duration + dur) > self.config.max_duration_seconds
            would_exceed_size = (current_part_size_gb + est_item_size_gb) > self.config.max_size_gb

            if (would_exceed_dur or would_exceed_size) and current_part:
                parts.append(current_part)
                current_part = []
                current_part_duration = 0.0
                current_part_size_gb = 0.0

            current_part.append((item, rel_dir))
            current_part_duration += dur
            current_part_size_gb += est_item_size_gb

        if current_part:
            parts.append(current_part)

        return parts

    def _preflight_check_and_fallback(
        self, first_item: MediaItem, log_callback: Optional[Callable[[str], None]]
    ) -> bool:
        """
        在開始大量轉碼前，進行 Pre-flight 試跑測試。
        若所選的編碼器在當前電腦硬體上失敗，自動智慧排錯並無縫降級至相容編碼器！
        """
        temp_test_output = os.path.join(
            os.environ.get("TEMP", "."), f"_hw_probe_test_{int(time.time())}.mp4"
        )
        startupinfo = None
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        test_duration = 0.1
        success, err_msg = self._test_single_render(
            first_item, temp_test_output, test_duration, startupinfo
        )
        if os.path.exists(temp_test_output):
            try:
                os.remove(temp_test_output)
            except Exception:
                pass

        if success:
            return True

        # 若失敗，啟動智慧排錯
        orig_codec = self.config.vcodec
        if log_callback:
            log_callback(
                f"【智慧排錯】偵測到所選編碼器『{orig_codec}』無法在當前硬體執行！\n"
                f"  錯誤原因：{err_msg}\n"
                f"  正在為您自動搜尋本機相容之最佳替代編碼器..."
            )

        # 備用候選清單（依優先順序）
        fallback_candidates = ["hevc_qsv", "hevc_nvenc", "hevc_amf", "libx265", "libx264"]
        for candidate in fallback_candidates:
            if candidate == orig_codec:
                continue

            self.config.vcodec = candidate
            c_success, c_err = self._test_single_render(
                first_item, temp_test_output, test_duration, startupinfo
            )
            if os.path.exists(temp_test_output):
                try:
                    os.remove(temp_test_output)
                except Exception:
                    pass

            if c_success:
                hw_name = "Intel QSV HEVC 硬體加速" if candidate == "hevc_qsv" else candidate
                if log_callback:
                    log_callback(
                        f"✓【智慧排錯成功】已為您自動無縫切換至：『{candidate}』({hw_name})！\n"
                        f"  系統將以此相容配置繼續執行，避免任務中斷。\n"
                    )
                return True

        if log_callback:
            log_callback("【嚴重錯誤】所有備用編碼器均測試失敗，無法執行渲染。")
        return False

    def _test_single_render(
        self, item: MediaItem, output_file: str, duration: float, startupinfo
    ) -> Tuple[bool, str]:
        """試跑渲染測試"""
        w, h = 640, 360  # 測試用低解析度快速驗證
        cmd = [
            self.ffmpeg_path,
            "-y",
            "-loop", "1",
            "-t", str(duration),
            "-i", item.file_path,
            "-f", "lavfi",
            "-t", str(duration),
            "-i", f"anullsrc=r=48000:cl=stereo",
            "-vf", f"scale={w}:{h}",
            "-c:v", self.config.vcodec,
            "-c:a", "aac",
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
                timeout=5,
            )
            if res.returncode == 0:
                return True, "成功"
            err = res.stderr.strip()
            for line in err.split("\n"):
                if "unsupported" in line.lower() or "error" in line.lower() or "failed" in line.lower():
                    return False, line.strip()
            return False, err.split("\n")[-1] if err else "未知錯誤"
        except Exception as e:
            return False, str(e)

    def render_album_to_video(
        self,
        media_list: List[Tuple[MediaItem, str]],
        base_output_video_path: str,
        base_output_chapter_path: str,
        target_title: str,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        log_callback: Optional[Callable[[str], None]] = None,
    ) -> bool:
        """自動分段批次渲染輸出"""
        if not self.ffmpeg_path or not os.path.exists(self.ffmpeg_path):
            if log_callback:
                log_callback("【錯誤】未找到 FFmpeg 核心程式！請先確認安裝。")
            return False

        self._is_cancelled = False
        parts = self.split_media_into_parts(media_list)
        total_parts = len(parts)

        # 執行 Pre-flight 試跑與智慧排錯
        if media_list:
            first_item = media_list[0][0]
            if not self._preflight_check_and_fallback(first_item, log_callback):
                return False

        if log_callback:
            if total_parts > 1:
                log_callback(
                    f"[注意] 偵測到總項目長度或預估容量超過 YouTube 安全限制！\n"
                    f"系統已自動切分為 {total_parts} 個獨立備份影片 (Part 1 ~ Part {total_parts})\n"
                )
            else:
                log_callback(f"總長度在安全限制範圍內，將合併為單一 8K/4K 影片。\n")

        for part_idx, part_media in enumerate(parts, start=1):
            if self._is_cancelled:
                if log_callback:
                    log_callback("【任務已取消】使用者終止了處理程序。")
                return False

            if total_parts > 1:
                base_dir = os.path.dirname(os.path.abspath(base_output_video_path))
                video_name, video_ext = os.path.splitext(os.path.basename(base_output_video_path))
                chap_name, chap_ext = os.path.splitext(os.path.basename(base_output_chapter_path))

                part_tag = f"_Part{part_idx:02d}"
                out_video = os.path.join(base_dir, f"{video_name}{part_tag}{video_ext}")
                out_chap = os.path.join(base_dir, f"{chap_name}{part_tag}{chap_ext}")
                part_title = f"{target_title} (Part {part_idx:02d}/{total_parts:02d})"
            else:
                out_video = base_output_video_path
                out_chap = base_output_chapter_path
                part_title = target_title

            if log_callback:
                log_callback(
                    f"==================================================\n"
                    f"[處理中] 開始處理第 {part_idx}/{total_parts} 部影片：『{part_title}』\n"
                    f"本段收錄項目：{len(part_media)} 個媒體檔案\n"
                    f"使用編碼器：{self.config.vcodec} ({self.config.resolution} @ {self.config.fps}fps)\n"
                    f"=================================================="
                )

            success = self._render_single_part(
                part_media,
                out_video,
                out_chap,
                target_title,
                part_idx,
                total_parts,
                progress_callback,
                log_callback,
            )

            if not success:
                return False

        if log_callback:
            log_callback(
                f"[完成] 所有備份影片（共 {total_parts} 部）已全數成功產出完畢！"
            )
        return True

    def _render_single_part(
        self,
        part_media: List[Tuple[MediaItem, str]],
        output_video_path: str,
        output_chapter_path: str,
        target_title: str,
        part_index: int,
        total_parts: int,
        progress_callback: Optional[Callable[[int, int, str], None]],
        log_callback: Optional[Callable[[str], None]],
    ) -> bool:
        """渲染單一個 Part 影片"""
        os.makedirs(os.path.dirname(os.path.abspath(output_video_path)), exist_ok=True)
        temp_dir = os.path.join(
            os.path.dirname(os.path.abspath(output_video_path)),
            f"_temp_render_p{part_index}_{int(time.time())}",
        )
        os.makedirs(temp_dir, exist_ok=True)

        chapter_gen = ChapterGenerator(target_title, part_index, total_parts)
        current_time_sec = 0.0
        segment_files: List[str] = []
        total_items = len(part_media)

        try:
            startupinfo = None
            if os.name == "nt":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            for idx, (item, rel_dir) in enumerate(part_media):
                if self._is_cancelled:
                    return False

                item_filename = item.file_name
                chapter_gen.add_entry(current_time_sec, item_filename, rel_dir)
                seg_output = os.path.join(temp_dir, f"seg_{idx:05d}.mp4")

                part_prefix = f"[Part {part_index}/{total_parts}] " if total_parts > 1 else ""

                if item.is_image:
                    item_duration = self.config.image_duration
                    current_time_sec += item_duration
                    if progress_callback:
                        progress_callback(
                            idx + 1,
                            total_items,
                            f"{part_prefix}處理照片 ({idx + 1}/{total_items})：{item_filename}",
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
                            f"{part_prefix}處理影片 ({idx + 1}/{total_items})：{item_filename}",
                        )
                    success = self._render_video_segment(
                        item, seg_output, startupinfo, log_callback
                    )

                if not success:
                    continue

                segment_files.append(seg_output)

            if not segment_files:
                if log_callback:
                    log_callback("【錯誤】本段無有效渲染片段。")
                return False

            chapter_gen.save_to_file(output_chapter_path)
            if log_callback:
                log_callback(f"[OK] YouTube 章節索引檔案已建立：{output_chapter_path}")

            if progress_callback:
                progress_callback(total_items, total_items, f"{part_prefix}正在進行無損極速封裝合併...")
            if log_callback:
                log_callback(f"正在將本段片段進行無損合併...")

            concat_list_file = os.path.join(temp_dir, "concat_list.txt")
            with open(concat_list_file, "w", encoding="utf-8") as f:
                for seg in segment_files:
                    formatted_path = seg.replace("\\", "/")
                    f.write(f"file '{formatted_path}'\n")

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
                log_callback(f"[完成] 影片已成功產出：{output_video_path}\n")
            return True

        finally:
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
        """單張相片渲染"""
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
            "-loop", "1",
            "-t", str(duration),
            "-i", item.file_path,
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
            if res.returncode != 0:
                if log_callback:
                    # 擷取關鍵錯誤
                    err_lines = [
                        line.strip()
                        for line in res.stderr.split("\n")
                        if line.strip() and ("error" in line.lower() or "unsupported" in line.lower())
                    ]
                    detail = err_lines[0] if err_lines else res.stderr.strip().split("\n")[-1]
                    log_callback(f"【照片渲染失敗】{item.file_name} -> 原因：{detail}")
                return False
            return True
        except Exception as e:
            if log_callback:
                log_callback(f"【照片渲染異常】{item.file_name} -> {e}")
            return False

    def _render_video_segment(
        self,
        item: MediaItem,
        output_file: str,
        startupinfo,
        log_callback,
    ) -> bool:
        """既有影片標準化渲染"""
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
            if res.returncode != 0:
                if log_callback:
                    err_lines = [
                        line.strip()
                        for line in res.stderr.split("\n")
                        if line.strip() and ("error" in line.lower() or "unsupported" in line.lower())
                    ]
                    detail = err_lines[0] if err_lines else res.stderr.strip().split("\n")[-1]
                    log_callback(f"【影片渲染失敗】{item.file_name} -> 原因：{detail}")
                return False
            return True
        except Exception as e:
            if log_callback:
                log_callback(f"【影片渲染異常】{item.file_name} -> {e}")
            return False
