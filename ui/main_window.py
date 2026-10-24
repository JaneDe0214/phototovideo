"""
主視窗介面模組
提供樹狀目錄瀏覽、起點節點選擇、8K/4K 最高規格參數設定、
YouTube 12 小時 / 256GB 限制智慧自動分段保護、
即時進度監控與 YouTube 章節生成控制。
"""

import os
import subprocess
from typing import Optional
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.encoder_detector import HardwareDetector, find_ffmpeg
from core.ffmpeg_engine import RenderConfig, VideoRenderEngine
from core.scanner import AlbumScanner, DirectoryTreeNode


class RenderWorker(QThread):
    """背景渲染執行緒，防止 UI 凍結"""

    progress_signal = pyqtSignal(int, int, str)
    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(bool, str)

    def __init__(
        self,
        engine: VideoRenderEngine,
        media_list,
        output_video_path: str,
        output_chapter_path: str,
        target_title: str,
    ):
        super().__init__()
        self.engine = engine
        self.media_list = media_list
        self.output_video_path = output_video_path
        self.output_chapter_path = output_chapter_path
        self.target_title = target_title

    def run(self):
        def on_progress(current, total, msg):
            self.progress_signal.emit(current, total, msg)

        def on_log(msg):
            self.log_signal.emit(msg)

        success = self.engine.render_album_to_video(
            self.media_list,
            self.output_video_path,
            self.output_chapter_path,
            self.target_title,
            progress_callback=on_progress,
            log_callback=on_log,
        )

        msg = self.output_video_path if success else "渲染過程中斷或失敗"
        self.finished_signal.emit(success, msg)

    def stop(self):
        self.engine.cancel()


class MainWindow(QMainWindow):
    """應用程式主視窗"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("相簿轉 8K/4K YouTube 極致備份影片合成工具")
        self.resize(1200, 800)

        self.root_node: Optional[DirectoryTreeNode] = None
        self.selected_start_node: Optional[DirectoryTreeNode] = None
        self.hardware_detector = HardwareDetector()
        self.profiles = self.hardware_detector.get_recommended_profiles()
        self.worker: Optional[RenderWorker] = None
        self.last_output_dir = ""

        self._init_ui()
        self._check_environment()

    def _init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(10)

        # 頂部：根目錄選擇列
        top_bar = QHBoxLayout()
        self.btn_select_root = QPushButton("📂 選擇相簿根目錄")
        self.btn_select_root.clicked.connect(self._on_select_root_dir)
        self.lbl_root_path = QLabel("尚未選擇目錄（請點選左側按鈕瀏覽）")
        self.lbl_root_path.setStyleSheet("color: #a0a0ab; font-size: 13px;")
        top_bar.addWidget(self.btn_select_root)
        top_bar.addWidget(self.lbl_root_path, stretch=1)
        main_layout.addLayout(top_bar)

        # 中間主分割視窗 (左: 樹狀目錄與起點選擇, 右: 規格設定面板)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # 左側面版：樹狀結構
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)

        lbl_tree_guide = QLabel("【相簿目錄樹】請點選任意資料夾作為「合成起點」：")
        lbl_tree_guide.setStyleSheet("font-weight: bold; color: #00d2ff;")
        left_layout.addWidget(lbl_tree_guide)

        self.tree_widget = QTreeWidget()
        self.tree_widget.setHeaderLabels(["資料夾名稱", "相片數", "影片數", "容量"])
        self.tree_widget.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree_widget.itemClicked.connect(self._on_tree_item_clicked)
        left_layout.addWidget(self.tree_widget)

        # 起點統計資訊卡
        self.group_stats = QGroupBox("📌 目前選定的合成起點資訊")
        stats_layout = QVBoxLayout(self.group_stats)
        self.lbl_stat_target = QLabel("起點目標：尚未選取")
        self.lbl_stat_counts = QLabel("包含媒體：相片 0 張 / 影片 0 支")
        self.lbl_stat_est_duration = QLabel("預估總時長：0 秒")
        self.lbl_stat_est_size = QLabel("預估總容量：0 GB")
        self.lbl_stat_split_info = QLabel("分段狀態：-")
        self.lbl_stat_target.setStyleSheet("font-weight: bold; color: #ffffff;")
        stats_layout.addWidget(self.lbl_stat_target)
        stats_layout.addWidget(self.lbl_stat_counts)
        stats_layout.addWidget(self.lbl_stat_est_duration)
        stats_layout.addWidget(self.lbl_stat_est_size)
        stats_layout.addWidget(self.lbl_stat_split_info)
        left_layout.addWidget(self.group_stats)

        splitter.addWidget(left_widget)

        # 右側面板：最高規格與渲染選項
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)

        # 輸出畫質規格群組
        group_specs = QGroupBox("🚀 輸出畫質與規格設定（YouTube 最高箱子概念）")
        specs_layout = QVBoxLayout(group_specs)
        specs_layout.setSpacing(8)

        lbl_prof = QLabel("畫質設定檔（預設推薦最高流量與硬體加速）：")
        self.combo_profile = QComboBox()
        for prof in self.profiles:
            self.combo_profile.addItem(f"{prof['name']} - {prof['tag']}", prof["id"])
        self.combo_profile.currentIndexChanged.connect(self._update_stats_estimate)
        specs_layout.addWidget(lbl_prof)
        specs_layout.addWidget(self.combo_profile)

        # 照片秒數
        row_dur = QHBoxLayout()
        lbl_img_dur = QLabel("照片停留秒數：")
        self.spin_duration = QSpinBox()
        self.spin_duration.setRange(1, 30)
        self.spin_duration.setValue(3)
        self.spin_duration.setSuffix(" 秒")
        self.spin_duration.valueChanged.connect(self._update_stats_estimate)
        row_dur.addWidget(lbl_img_dur)
        row_dur.addWidget(self.spin_duration)
        specs_layout.addLayout(row_dur)

        # 直橫構圖填補模式
        row_fill = QHBoxLayout()
        lbl_fill = QLabel("直橫照片/影片填補方式：")
        self.combo_fill = QComboBox()
        self.combo_fill.addItem("智慧毛玻璃模糊背景（推薦，無變形）", "blur")
        self.combo_fill.addItem("純黑邊留白 (Letterbox)", "black")
        row_fill.addWidget(lbl_fill)
        row_fill.addWidget(self.combo_fill)
        specs_layout.addLayout(row_fill)

        # 音訊設定說明
        lbl_audio_info = QLabel("🎵 音訊規格：AAC 512 kbps @ 48,000 Hz（YouTube 立體聲最高極限）")
        lbl_audio_info.setStyleSheet("color: #70d6ff; font-size: 12px;")
        specs_layout.addWidget(lbl_audio_info)

        # 截圖最少失真保證說明
        lbl_lossless_info = QLabel("✨ 截圖無失真保證：Lanczos 頂級銳利縮放 ＋ 強制插入 IDR 關鍵幀")
        lbl_lossless_info.setStyleSheet("color: #a0f0a0; font-size: 12px;")
        specs_layout.addWidget(lbl_lossless_info)

        right_layout.addWidget(group_specs)

        # YouTube 限制自動分段保護群組
        group_split = QGroupBox("🛡️ YouTube 限制自動分段保護（防 12 小時 / 256GB 超標）")
        split_layout = QVBoxLayout(group_split)
        self.chk_auto_split = QCheckBox("啟用 YouTube 官方限制自動分段（若超標自動切為 Part 1, Part 2...）")
        self.chk_auto_split.setChecked(True)
        self.chk_auto_split.stateChanged.connect(self._update_stats_estimate)
        split_layout.addWidget(self.chk_auto_split)

        row_limits = QHBoxLayout()
        lbl_max_dur = QLabel("單部安全時長上限：")
        self.combo_max_dur = QComboBox()
        self.combo_max_dur.addItem("11 小時 40 分 (YT 12h 安全閾值)", 42000.0)
        self.combo_max_dur.addItem("8 小時", 28800.0)
        self.combo_max_dur.addItem("4 小時", 14400.0)
        self.combo_max_dur.addItem("2 小時", 7200.0)
        self.combo_max_dur.currentIndexChanged.connect(self._update_stats_estimate)

        lbl_max_size = QLabel("單部安全容量上限：")
        self.combo_max_size = QComboBox()
        self.combo_max_size.addItem("240 GB (YT 256GB 安全閾值)", 240.0)
        self.combo_max_size.addItem("180 GB", 180.0)
        self.combo_max_size.addItem("100 GB", 100.0)
        self.combo_max_size.addItem("50 GB", 50.0)
        self.combo_max_size.currentIndexChanged.connect(self._update_stats_estimate)

        row_limits.addWidget(lbl_max_dur)
        row_limits.addWidget(self.combo_max_dur)
        row_limits.addWidget(lbl_max_size)
        row_limits.addWidget(self.combo_max_size)
        split_layout.addLayout(row_limits)
        right_layout.addWidget(group_split)

        # 輸出設定群組
        group_output = QGroupBox("💾 輸出檔案設定（可自訂儲存位置，避免唯讀網路資料夾）")
        out_layout = QVBoxLayout(group_output)

        # 輸出路徑選擇模式
        row_out_mode = QHBoxLayout()
        self.chk_custom_out = QCheckBox("自訂輸出資料夾（若來源為唯讀 NAS 或網路磁碟，請務必勾選並選擇本機目錄）")
        self.chk_custom_out.setChecked(False)
        self.chk_custom_out.stateChanged.connect(self._on_custom_out_toggled)
        row_out_mode.addWidget(self.chk_custom_out)
        out_layout.addLayout(row_out_mode)

        row_custom_path = QHBoxLayout()
        self.txt_custom_out_dir = QLineEdit()
        self.txt_custom_out_dir.setPlaceholderText("請點選右側按鈕選擇輸出目錄...")
        self.txt_custom_out_dir.setEnabled(False)
        self.txt_custom_out_dir.textChanged.connect(self._update_stats_estimate)

        self.btn_browse_out = QPushButton("📁 瀏覽...")
        self.btn_browse_out.setEnabled(False)
        self.btn_browse_out.clicked.connect(self._on_browse_output_dir)

        row_custom_path.addWidget(self.txt_custom_out_dir, stretch=1)
        row_custom_path.addWidget(self.btn_browse_out)
        out_layout.addLayout(row_custom_path)

        self.lbl_output_filename = QLabel("預定輸出影片：(請先選取起點資料夾)")
        self.lbl_output_chapter = QLabel("預定章節檔案：(自動生成同名 Chapters.txt)")
        self.lbl_output_filename.setStyleSheet("color: #dcdce0;")
        self.lbl_output_chapter.setStyleSheet("color: #dcdce0;")
        out_layout.addWidget(self.lbl_output_filename)
        out_layout.addWidget(self.lbl_output_chapter)
        right_layout.addWidget(group_output)

        # 系統日誌
        group_log = QGroupBox("📋 處理日誌")
        log_layout = QVBoxLayout(group_log)
        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        log_layout.addWidget(self.txt_log)
        right_layout.addWidget(group_log, stretch=1)

        splitter.addWidget(right_widget)
        splitter.setSizes([480, 720])
        main_layout.addWidget(splitter, stretch=1)

        # 底部：進度條與控制按鈕
        bottom_box = QVBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.lbl_progress_status = QLabel("就緒")
        self.lbl_progress_status.setStyleSheet("color: #a0a0ab;")
        bottom_box.addWidget(self.lbl_progress_status)
        bottom_box.addWidget(self.progress_bar)

        btn_box = QHBoxLayout()
        self.btn_start = QPushButton("🚀 開始合成單一極致備份影片")
        self.btn_start.setObjectName("btn_primary")
        self.btn_start.setEnabled(False)
        self.btn_start.clicked.connect(self._on_start_render)

        self.btn_cancel = QPushButton("⏹ 停止")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self._on_cancel_render)

        self.btn_open_folder = QPushButton("📁 開啟輸出資料夾")
        self.btn_open_folder.setEnabled(False)
        self.btn_open_folder.clicked.connect(self._on_open_folder)

        btn_box.addWidget(self.btn_start, stretch=2)
        btn_box.addWidget(self.btn_cancel, stretch=1)
        btn_box.addWidget(self.btn_open_folder, stretch=1)
        bottom_box.addLayout(btn_box)

        main_layout.addLayout(bottom_box)

    def _on_custom_out_toggled(self, state):
        is_custom = self.chk_custom_out.isChecked()
        self.txt_custom_out_dir.setEnabled(is_custom)
        self.btn_browse_out.setEnabled(is_custom)
        self._update_stats_estimate()

    def _on_browse_output_dir(self):
        folder = QFileDialog.getExistingDirectory(self, "選擇輸出儲存資料夾（建議選擇本機硬碟）")
        if folder:
            self.txt_custom_out_dir.setText(os.path.normpath(folder))
            self._update_stats_estimate()

    def _get_effective_output_dir(self) -> str:
        if self.chk_custom_out.isChecked() and self.txt_custom_out_dir.text().strip():
            return os.path.normpath(self.txt_custom_out_dir.text().strip())
        if self.selected_start_node:
            return self.selected_start_node.dir_path
        return ""

    def _is_dir_writable(self, dir_path: str) -> bool:
        if not dir_path:
            return False
        import time
        try:
            os.makedirs(dir_path, exist_ok=True)
            test_file = os.path.join(dir_path, f".write_test_{int(time.time())}.tmp")
            with open(test_file, "w", encoding="utf-8") as f:
                f.write("test_permission")
            if os.path.exists(test_file):
                os.remove(test_file)
            return True
        except Exception:
            return False

    def _check_environment(self):
        ffmpeg_bin, _ = find_ffmpeg()
        if not ffmpeg_bin:
            self._log("【警訊】系統尚未找到 FFmpeg 可執行檔，請確認安裝。")
        else:
            self._log(f"[就緒] FFmpeg 核心版本已載入 ({ffmpeg_bin})")
            if self.hardware_detector.available_encoders:
                encoders_str = ", ".join(self.hardware_detector.available_encoders)
                self._log(f"[就緒] 偵測到支援的硬體/軟體編碼器：{encoders_str}")

    def _log(self, text: str):
        self.txt_log.append(text)

    def _on_select_root_dir(self):
        folder = QFileDialog.getExistingDirectory(self, "選擇旅遊或相簿根目錄")
        if not folder:
            return

        self.lbl_root_path.setText(folder)
        self._log(f"正在掃描根目錄結構：{folder} ...")
        self.root_node = AlbumScanner.scan_directory_tree(folder)
        if not self.root_node:
            QMessageBox.warning(self, "掃描失敗", "無法讀取該目錄或目錄不存在！")
            return

        self._populate_tree(self.root_node)
        self._log("[完成] 目錄掃描完畢！請在左側樹狀清單中點選欲打包為「單一影片」的起點資料夾。")

    def _populate_tree(self, root_node: DirectoryTreeNode):
        self.tree_widget.clear()

        def _add_item(node: DirectoryTreeNode, parent_item=None):
            img_c = node.total_images_count()
            vid_c = node.total_videos_count()
            size_mb = node.total_size_bytes() / (1024 * 1024)

            size_str = f"{size_mb:.1f} MB" if size_mb < 1024 else f"{size_mb / 1024:.2f} GB"
            item = QTreeWidgetItem([node.name, f"{img_c} 張", f"{vid_c} 支", size_str])
            item.setData(0, Qt.ItemDataRole.UserRole, node)

            if parent_item is None:
                self.tree_widget.addTopLevelItem(item)
            else:
                parent_item.addChild(item)

            for child in node.children:
                _add_item(child, item)

        _add_item(root_node)
        self.tree_widget.expandToDepth(1)

    def _on_tree_item_clicked(self, item: QTreeWidgetItem, column: int):
        node: DirectoryTreeNode = item.data(0, Qt.ItemDataRole.UserRole)
        if not node:
            return

        self.selected_start_node = node
        self.btn_start.setEnabled(True)
        self._update_stats_estimate()

    def _update_stats_estimate(self):
        if not self.selected_start_node:
            return

        node = self.selected_start_node
        img_count = node.total_images_count()
        vid_count = node.total_videos_count()
        img_sec = self.spin_duration.value()

        # 預估時間（秒）
        est_sec = (img_count * img_sec) + (vid_count * 10)
        h = int(est_sec // 3600)
        m = int((est_sec % 3600) // 60)
        s = int(est_sec % 60)
        duration_str = f"{h} 小時 {m} 分 {s} 秒" if h > 0 else f"{m} 分 {s} 秒"

        # 預估大小
        current_prof_id = self.combo_profile.currentData()
        prof = next((p for p in self.profiles if p["id"] == current_prof_id), self.profiles[0])
        bitrate_str = prof.get("bitrate", "240M")
        bitrate_num = int(bitrate_str.replace("M", "").replace("k", ""))
        gb_per_sec = (bitrate_num / (8 * 1024)) if "M" in bitrate_str else (bitrate_num / (8 * 1024 * 1024))
        est_gb = est_sec * gb_per_sec

        # 計算分段狀態
        is_auto_split = self.chk_auto_split.isChecked()
        max_dur = self.combo_max_dur.currentData()
        max_size = self.combo_max_size.currentData()

        est_parts_by_dur = int(est_sec // max_dur) + (1 if est_sec % max_dur > 0 else 0)
        est_parts_by_size = int(est_gb // max_size) + (1 if est_gb % max_size > 0 else 0)
        estimated_parts = max(est_parts_by_dur, est_parts_by_size, 1)

        self.lbl_stat_target.setText(f"起點目標：【{node.name}】（包含其所有子資料夾）")
        self.lbl_stat_counts.setText(f"包含媒體：相片 {img_count} 張 / 影片 {vid_count} 支")
        self.lbl_stat_est_duration.setText(f"預估總時長：約 {duration_str}")
        self.lbl_stat_est_size.setText(f"預估總容量：約 {est_gb:.1f} GB")

        target_name = node.name.replace(" ", "_")
        res_tag = "8K" if "8k" in prof["id"] else "4K"
        out_dir = self._get_effective_output_dir()
        dir_display = f"\n儲存目錄：{out_dir}" if out_dir else ""

        if estimated_parts > 1 and is_auto_split:
            self.lbl_stat_split_info.setText(
                f"🛡️ 分段保護啟動：超過 YT 限制，自動切分為 {estimated_parts} 部影片 (Part 1 ~ {estimated_parts})"
            )
            self.lbl_stat_split_info.setStyleSheet("color: #ffa500; font-weight: bold;")
            self.lbl_output_filename.setText(f"預定輸出影片：{target_name}_Part01_{res_tag}_極致備份.mp4 等 {estimated_parts} 個檔案{dir_display}")
            self.lbl_output_chapter.setText(f"預定章節檔案：{target_name}_Part01_{res_tag}_Chapters.txt 等 {estimated_parts} 個檔案")
        else:
            self.lbl_stat_split_info.setText("安全：總長度與容量在 YouTube 限制內，合成單一完整影片")
            self.lbl_stat_split_info.setStyleSheet("color: #a0f0a0;")
            self.lbl_output_filename.setText(f"預定輸出影片：{target_name}_{res_tag}_極致備份.mp4{dir_display}")
            self.lbl_output_chapter.setText(f"預定章節檔案：{target_name}_{res_tag}_Chapters.txt")

    def _on_start_render(self):
        if not self.selected_start_node:
            return

        node = self.selected_start_node
        sorted_media = AlbumScanner.get_sorted_media_from_node(node)
        if not sorted_media:
            QMessageBox.warning(self, "無媒體項目", "所選起點目錄內沒有可處理的照片或影片！")
            return

        out_dir = self._get_effective_output_dir()
        if not out_dir:
            QMessageBox.warning(self, "未指定輸出目錄", "請先選取起點資料夾或自訂輸出資料夾！")
            return

        # 唯讀網路資料夾防呆檢查
        if not self._is_dir_writable(out_dir):
            QMessageBox.critical(
                self,
                "輸出目錄無寫入權限",
                f"所指定的輸出資料夾無法寫入檔案：\n{out_dir}\n\n"
                f"原因可能是此目錄為唯讀網路磁碟機 (NAS / SMB 共享) 或使用者權限不足。\n"
                f"請勾選『自訂輸出資料夾』並選擇可寫入的本機磁碟（例如 D:\\ 或 C:\\Users...）！"
            )
            self._log(f"【錯誤】輸出目錄無寫入權限，處理中止：{out_dir}")
            return

        current_prof_id = self.combo_profile.currentData()
        prof = next((p for p in self.profiles if p["id"] == current_prof_id), self.profiles[0])

        config = RenderConfig(
            resolution=prof["resolution"],
            fps=prof["fps"],
            vcodec=prof["vcodec"],
            bitrate=prof["bitrate"],
            maxrate=prof["maxrate"],
            bufsize=prof["bufsize"],
            image_duration=float(self.spin_duration.value()),
            fill_mode=self.combo_fill.currentData(),
            audio_bitrate="512k",
            audio_samplerate=48000,
            enable_auto_split=self.chk_auto_split.isChecked(),
            max_duration_seconds=float(self.combo_max_dur.currentData()),
            max_size_gb=float(self.combo_max_size.currentData()),
        )

        self.last_output_dir = out_dir
        target_name = node.name.replace(" ", "_")
        res_tag = "8K" if "8k" in prof["id"] else "4K"
        out_video = os.path.join(out_dir, f"{target_name}_{res_tag}_極致備份.mp4")
        out_chap = os.path.join(out_dir, f"{target_name}_{res_tag}_Chapters.txt")

        self.btn_start.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.btn_open_folder.setEnabled(False)
        self.btn_select_root.setEnabled(False)
        self.progress_bar.setValue(0)

        engine = VideoRenderEngine(config)
        self.worker = RenderWorker(
            engine, sorted_media, out_video, out_chap, node.name
        )
        self.worker.progress_signal.connect(self._on_render_progress)
        self.worker.log_signal.connect(self._log)
        self.worker.finished_signal.connect(self._on_render_finished)
        self.worker.start()

    def _on_render_progress(self, current: int, total: int, msg: str):
        percent = int((current / total) * 100) if total > 0 else 0
        self.progress_bar.setValue(percent)
        self.lbl_progress_status.setText(f"{msg} ({percent}%)")

    def _on_render_finished(self, success: bool, message: str):
        self.btn_start.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.btn_open_folder.setEnabled(True)
        self.btn_select_root.setEnabled(True)

        if success:
            self.progress_bar.setValue(100)
            self.lbl_progress_status.setText("完成！備份影片已全部合成。")
            QMessageBox.information(
                self,
                "備份完成",
                f"備份影片與對應的 YouTube 章節檔案已產生完畢！\n\n路徑：\n{self.last_output_dir}",
            )
        else:
            self.lbl_progress_status.setText("處理失敗或已終止。")
            QMessageBox.critical(self, "錯誤", f"處理失敗：\n{message}")

    def _on_cancel_render(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self._log("正在終止合成程序，請稍候...")

    def _on_open_folder(self):
        if self.last_output_dir and os.path.exists(self.last_output_dir):
            if os.name == "nt":
                os.startfile(self.last_output_dir)
            else:
                subprocess.run(["xdg-open", self.last_output_dir])
