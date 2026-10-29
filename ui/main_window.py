"""
主視窗介面模組
提供樹狀目錄瀏覽、起點節點選擇、8K/4K 最高規格參數設定、
YouTube 12 小時 / 256GB 限制智慧自動分段保護、
即時進度監控、YouTube 章節生成控制、
以及全新的【多相簿批次佇列排程管理員】與【斷點續傳接續保護】。
"""

import os
import subprocess
import time
from typing import Optional, List, Tuple
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QSizePolicy,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.encoder_detector import (
    HardwareDetector,
    find_ffmpeg,
    get_system_memory_info,
    calculate_safe_concurrency,
    get_output_spec_tag,
)
from core.ffmpeg_engine import (
    RenderConfig,
    VideoRenderEngine,
    PHOTO_BITRATE_RATIO,
    VIDEO_BITRATE_RATIO,
    AUDIO_BITRATE_KBPS,
)
from core.scanner import AlbumScanner, DirectoryTreeNode
from core.queue_manager import QueueManager, BatchTask


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
        self.setWindowTitle("相簿轉 8K/4K YouTube 影片合成工具（支援批次佇列與斷點續傳）")
        self.resize(1260, 850)

        self.root_node: Optional[DirectoryTreeNode] = None
        self.selected_start_node: Optional[DirectoryTreeNode] = None
        self.hardware_detector = HardwareDetector()
        self.profiles = self.hardware_detector.get_recommended_profiles()
        self.mem_info = get_system_memory_info()
        self.total_ram_gb = self.mem_info.get("total_gb", 16.0)
        self.worker: Optional[RenderWorker] = None
        self.last_output_dir = ""

        # 批次佇列排程管理器
        self.queue_manager = QueueManager()
        self.is_single_mode = False

        self._init_ui()
        self._check_environment()
        self._update_stats_estimate()
        self._refresh_queue_table()

    def _init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(8)

        # 主要頁籤 (TabWidget)
        self.tab_widget = QTabWidget(self)
        main_layout.addWidget(self.tab_widget)

        # Tab 1: 【相簿起點與規格設定】
        self.tab_single = QWidget()
        self._setup_single_render_tab(self.tab_single)
        self.tab_widget.addTab(self.tab_single, "📂 相簿瀏覽與設定")

        # Tab 2: 【批次佇列排程管理員】
        self.tab_queue = QWidget()
        self._setup_queue_tab(self.tab_queue)
        self.tab_widget.addTab(self.tab_queue, f"📋 批次排程佇列 ({len(self.queue_manager.tasks)})")

    def _setup_single_render_tab(self, parent: QWidget):
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # 頂部：根目錄選擇列
        top_bar = QHBoxLayout()
        self.btn_select_root = QPushButton("📂 選擇相簿根目錄", parent)
        self.btn_select_root.clicked.connect(self._on_select_root_dir)
        self.lbl_root_path = QLabel("尚未選擇目錄（請點選左側按鈕瀏覽）", parent)
        self.lbl_root_path.setStyleSheet("color: #a0a0ab; font-size: 13px;")
        top_bar.addWidget(self.btn_select_root)
        top_bar.addWidget(self.lbl_root_path, stretch=1)
        layout.addLayout(top_bar)

        # 中間主分割視窗 (左: 樹狀目錄與起點選擇, 右: 規格設定面板)
        self.splitter = QSplitter(Qt.Orientation.Horizontal, parent)

        # 左側面版：樹狀結構
        self.left_widget = QWidget(self.splitter)
        left_layout = QVBoxLayout(self.left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)

        lbl_tree_guide = QLabel("【相簿目錄樹】請點選任意資料夾作為「合成起點」：", self.left_widget)
        lbl_tree_guide.setStyleSheet("font-weight: bold; color: #00d2ff;")
        left_layout.addWidget(lbl_tree_guide)

        self.tree_widget = QTreeWidget(self.left_widget)
        self.tree_widget.setHeaderLabels(["資料夾名稱", "相片數", "影片數", "容量"])
        self.tree_widget.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree_widget.itemClicked.connect(self._on_tree_item_clicked)
        left_layout.addWidget(self.tree_widget)

        # 起點統計資訊卡
        self.group_stats = QGroupBox("📌 目前選定的合成起點資訊", self.left_widget)
        stats_layout = QVBoxLayout(self.group_stats)
        self.lbl_stat_target = QLabel("起點目標：尚未選取", self.group_stats)
        self.lbl_stat_counts = QLabel("包含媒體：相片 0 張 / 影片 0 支", self.group_stats)
        self.lbl_stat_est_duration = QLabel("預估總時長：0 秒", self.group_stats)
        self.lbl_stat_est_size = QLabel("預估總容量：0 GB", self.group_stats)
        self.lbl_stat_split_info = QLabel("分段狀態：-", self.group_stats)
        self.lbl_stat_target.setStyleSheet("font-weight: bold; color: #ffffff;")
        stats_layout.addWidget(self.lbl_stat_target)
        stats_layout.addWidget(self.lbl_stat_counts)
        stats_layout.addWidget(self.lbl_stat_est_duration)
        stats_layout.addWidget(self.lbl_stat_est_size)
        stats_layout.addWidget(self.lbl_stat_split_info)
        left_layout.addWidget(self.group_stats)

        self.splitter.addWidget(self.left_widget)

        # 右側面板：平滑滾動區域 (自適應彈性滾動，防止小螢幕擠壓)
        self.right_scroll = QScrollArea(self.splitter)
        self.right_scroll.setWidgetResizable(True)
        self.right_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        self.right_widget = QWidget(self.right_scroll)
        self.right_widget.setMinimumWidth(460)
        right_layout = QVBoxLayout(self.right_widget)
        right_layout.setContentsMargins(8, 0, 12, 0)
        right_layout.setSpacing(10)

        # ⚡ 硬體加速支援儀表板群組
        group_hw = QGroupBox("⚡ 本電腦實體硬體加速支援儀表板（動態實測）", self.right_widget)
        hw_layout = QVBoxLayout(group_hw)
        hw_layout.setSpacing(4)

        hw_summary = self.hardware_detector.get_hardware_status_summary()

        qsv = hw_summary["qsv"]
        lbl_qsv = QLabel(f"{'🟢' if qsv['light'] == 'green' else '⚪'} <b>{qsv['label']}</b>：{qsv['desc']}", group_hw)
        lbl_qsv.setStyleSheet("color: #dcdce0; font-size: 12px;")
        hw_layout.addWidget(lbl_qsv)

        nv = hw_summary["nvenc"]
        lbl_nv = QLabel(f"{'🟢' if nv['light'] == 'green' else '⚪'} <b>{nv['label']}</b>：{nv['desc']}", group_hw)
        lbl_nv.setStyleSheet("color: #dcdce0; font-size: 12px;")
        hw_layout.addWidget(lbl_nv)

        amf = hw_summary["amf"]
        lbl_amf = QLabel(f"{'🟢' if amf['light'] == 'green' else '⚪'} <b>{amf['label']}</b>：{amf['desc']}", group_hw)
        lbl_amf.setStyleSheet("color: #dcdce0; font-size: 12px;")
        hw_layout.addWidget(lbl_amf)

        cpu = hw_summary["cpu"]
        lbl_cpu = QLabel(f"🟢 <b>{cpu['label']}</b>：{cpu['desc']}", group_hw)
        lbl_cpu.setStyleSheet("color: #dcdce0; font-size: 12px;")
        hw_layout.addWidget(lbl_cpu)

        self.lbl_active_hw_status = QLabel("🎯 目前選取設定：偵測中...", group_hw)
        self.lbl_active_hw_status.setStyleSheet(
            "color: #00f2fe; font-weight: bold; font-size: 13px; margin-top: 4px; padding-top: 4px; border-top: 1px dashed #3d3d4a;"
        )
        hw_layout.addWidget(self.lbl_active_hw_status)
        right_layout.addWidget(group_hw)

        # 輸出畫質規格群組
        group_specs = QGroupBox("🚀 輸出畫質與規格設定（YouTube 最高箱子概念 · 8K優先）", self.right_widget)
        specs_layout = QVBoxLayout(group_specs)
        specs_layout.setSpacing(10)

        # 🌟 快速選擇 K 數優先選擇區 (上下分行，杜絕左右橫向過寬擠壓)
        lbl_k = QLabel("🎯 目標畫質等級（K 數優先）：", group_specs)
        lbl_k.setStyleSheet("font-weight: bold; color: #00d2ff; font-size: 13px;")
        specs_layout.addWidget(lbl_k)

        row_k_btns = QHBoxLayout()
        row_k_btns.setSpacing(8)
        self.btn_preset_8k = QPushButton("🌟 8K 超高畫質 (7680x4320 首選)", group_specs)
        self.btn_preset_8k.setCheckable(True)
        self.btn_preset_8k.setChecked(True)
        self.btn_preset_8k.setMinimumHeight(36)
        self.btn_preset_8k.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_preset_8k.setStyleSheet("""
            QPushButton {
                background-color: #2b2b36; border: 1px solid #4a4a5a; border-radius: 6px; color: #ffffff; padding: 6px 10px; font-weight: bold; font-size: 13px;
            }
            QPushButton:hover {
                border-color: #00d2ff; background-color: #353545;
            }
            QPushButton:checked {
                background-color: #0078d4; border: 2px solid #00f2fe; color: #ffffff;
            }
        """)

        self.btn_preset_4k = QPushButton("⚡ 4K 高畫質 (3840x2160 極速)", group_specs)
        self.btn_preset_4k.setCheckable(True)
        self.btn_preset_4k.setMinimumHeight(36)
        self.btn_preset_4k.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_preset_4k.setStyleSheet("""
            QPushButton {
                background-color: #2b2b36; border: 1px solid #4a4a5a; border-radius: 6px; color: #ffffff; padding: 6px 10px; font-weight: bold; font-size: 13px;
            }
            QPushButton:hover {
                border-color: #00d2ff; background-color: #353545;
            }
            QPushButton:checked {
                background-color: #0078d4; border: 2px solid #00f2fe; color: #ffffff;
            }
        """)

        self.btn_preset_8k.clicked.connect(self._on_select_8k_preset)
        self.btn_preset_4k.clicked.connect(self._on_select_4k_preset)
        row_k_btns.addWidget(self.btn_preset_8k, stretch=1)
        row_k_btns.addWidget(self.btn_preset_4k, stretch=1)
        specs_layout.addLayout(row_k_btns)

        lbl_prof = QLabel("⚙️ 詳細編碼核心設定檔（支援自動平滑降級，遇限制不中斷）：", group_specs)
        lbl_prof.setStyleSheet("color: #dcdce0; font-size: 12px; margin-top: 2px;")
        self.combo_profile = QComboBox(group_specs)
        self.combo_profile.setMinimumHeight(36)
        self.combo_profile.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.combo_profile.setMaxVisibleItems(10)

        for idx, prof in enumerate(self.profiles):
            self.combo_profile.addItem(prof["name"], prof["id"])
            self.combo_profile.setItemData(idx, prof.get("tag", ""), Qt.ItemDataRole.ToolTipRole)

        self.combo_profile.currentIndexChanged.connect(self._on_profile_combo_changed)
        specs_layout.addWidget(lbl_prof)
        specs_layout.addWidget(self.combo_profile)

        # 照片秒數
        row_dur = QHBoxLayout()
        lbl_img_dur = QLabel("照片停留秒數：", group_specs)
        self.spin_duration = QSpinBox(group_specs)
        self.spin_duration.setRange(1, 30)
        self.spin_duration.setValue(3)
        self.spin_duration.setSuffix(" 秒")
        self.spin_duration.valueChanged.connect(self._update_stats_estimate)
        row_dur.addWidget(lbl_img_dur)
        row_dur.addWidget(self.spin_duration)
        specs_layout.addLayout(row_dur)

        # 直橫構圖填補模式
        row_fill = QHBoxLayout()
        lbl_fill = QLabel("直橫照片/影片填補方式：", group_specs)
        self.combo_fill = QComboBox(group_specs)
        self.combo_fill.addItem("純黑邊留白（極速推薦，最少失真，忠於原圖）", "black")
        self.combo_fill.addItem("智慧毛玻璃模糊背景（計算量大，消耗算力）", "blur")
        row_fill.addWidget(lbl_fill)
        row_fill.addWidget(self.combo_fill)
        specs_layout.addLayout(row_fill)

        # ⚡ 多工平行處理加速設定 (垂直或簡潔分行，杜絕擠壓)
        cpu_count = os.cpu_count() or 4
        lbl_concur = QLabel(f"⚡ 平行處理加速（CPU {cpu_count} 核心 / 實體 RAM {self.total_ram_gb}GB）：", group_specs)
        lbl_concur.setStyleSheet("color: #dcdce0; font-size: 12px; margin-top: 2px;")
        specs_layout.addWidget(lbl_concur)

        self.combo_concurrency = QComboBox(group_specs)
        self.combo_concurrency.setMinimumHeight(32)
        self.combo_concurrency.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.combo_concurrency.addItem("🛡️ 智慧記憶體防護推薦（自動調節，零 SWAP，保護 SSD）", -1)
        self.combo_concurrency.addItem("4 緒 (8K 極安全模式，RAM 佔用約 7GB，保護 SSD 零換頁)", 4)
        self.combo_concurrency.addItem("6 緒 (8K 均衡極速，RAM 佔用約 11GB，32G 筆電推薦)", 6)
        self.combo_concurrency.addItem("8 緒 (4K/8K 雙引擎推薦，RAM 佔用約 14GB)", 8)
        if cpu_count >= 12:
            self.combo_concurrency.addItem("12 緒平行加速 (4K 狂飆 / 8K 建議 32G 以上記憶體)", 12)
        if cpu_count >= 16:
            self.combo_concurrency.addItem("16 緒極速狂飆 (需 64G 以上記憶體)", 16)
        if cpu_count >= 24:
            self.combo_concurrency.addItem("24 緒極限全開 (需 64G~128G 記憶體防止 SSD SWAP)", 24)
        self.combo_concurrency.addItem(f"⚡ 核心強制全開 ({cpu_count} 緒全速開火 - 注意：8K 需大記憶體)", cpu_count)
        self.combo_concurrency.addItem("1 緒 (單工除錯模式)", 1)
        self.combo_concurrency.currentIndexChanged.connect(self._update_stats_estimate)

        specs_layout.addWidget(self.combo_concurrency)

        # 💾 記憶體與 SSD 安全評估狀態顯示
        self.lbl_memory_safeguard = QLabel("💾 記憶體與 SSD 安全評估：計算中...", group_specs)
        self.lbl_memory_safeguard.setWordWrap(True)
        specs_layout.addWidget(self.lbl_memory_safeguard)

        # YouTube 限制自動分段保護群組
        group_split = QGroupBox("🛡️ YouTube 限制自動分段保護（防 12 小時 / 256GB 超標）", self.right_widget)
        split_layout = QVBoxLayout(group_split)
        self.chk_auto_split = QCheckBox("啟用 YouTube 官方限制自動分段（若超標自動切為 Part 1, Part 2...）", group_split)
        self.chk_auto_split.setChecked(True)
        self.chk_auto_split.stateChanged.connect(self._update_stats_estimate)
        split_layout.addWidget(self.chk_auto_split)

        row_limits = QHBoxLayout()
        lbl_max_dur = QLabel("單部安全時長上限：", group_split)
        self.combo_max_dur = QComboBox(group_split)
        self.combo_max_dur.addItem("11 小時 40 分 (YT 12h 安全閾值)", 42000.0)
        self.combo_max_dur.addItem("8 小時", 28800.0)
        self.combo_max_dur.addItem("4 小時", 14400.0)
        self.combo_max_dur.addItem("2 小時", 7200.0)
        self.combo_max_dur.currentIndexChanged.connect(self._update_stats_estimate)

        lbl_max_size = QLabel("單部安全容量上限：", group_split)
        self.combo_max_size = QComboBox(group_split)
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
        group_output = QGroupBox("💾 輸出檔案設定（可自訂儲存位置，避免唯讀網路資料夾）", self.right_widget)
        out_layout = QVBoxLayout(group_output)

        row_out_mode = QHBoxLayout()
        self.chk_custom_out = QCheckBox("自訂輸出資料夾（若來源為唯讀 NAS 或網路磁碟，請務必勾選並選擇本機目錄）", group_output)
        self.chk_custom_out.setChecked(False)
        self.chk_custom_out.stateChanged.connect(self._on_custom_out_toggled)
        row_out_mode.addWidget(self.chk_custom_out)
        out_layout.addLayout(row_out_mode)

        row_custom_path = QHBoxLayout()
        self.txt_custom_out_dir = QLineEdit(group_output)
        self.txt_custom_out_dir.setPlaceholderText("請點選右側按鈕選擇輸出目錄...")
        self.txt_custom_out_dir.setEnabled(False)
        self.txt_custom_out_dir.textChanged.connect(self._update_stats_estimate)

        self.btn_browse_out = QPushButton("📁 瀏覽...", group_output)
        self.btn_browse_out.setEnabled(False)
        self.btn_browse_out.clicked.connect(self._on_browse_output_dir)

        row_custom_path.addWidget(self.txt_custom_out_dir, stretch=1)
        row_custom_path.addWidget(self.btn_browse_out)
        out_layout.addLayout(row_custom_path)

        self.lbl_output_filename = QLabel("預定輸出影片：(請先選取起點資料夾)", group_output)
        self.lbl_output_chapter = QLabel("預定章節檔案：(自動生成同名 Chapters.txt)", group_output)
        self.lbl_output_filename.setStyleSheet("color: #dcdce0;")
        self.lbl_output_chapter.setStyleSheet("color: #dcdce0;")
        out_layout.addWidget(self.lbl_output_filename)
        out_layout.addWidget(self.lbl_output_chapter)
        right_layout.addWidget(group_output)

        # 系統日誌
        group_log = QGroupBox("📋 處理日誌（內建斷點續傳進度追蹤）", self.right_widget)
        log_layout = QVBoxLayout(group_log)
        self.txt_log = QTextEdit(group_log)
        self.txt_log.setReadOnly(True)
        self.txt_log.setMinimumHeight(140)
        log_layout.addWidget(self.txt_log)
        right_layout.addWidget(group_log)

        self.right_scroll.setWidget(self.right_widget)
        self.splitter.addWidget(self.right_scroll)
        self.splitter.setSizes([380, 820])
        layout.addWidget(self.splitter, stretch=1)

        # 底部按鈕操作列
        bottom_box = QVBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.lbl_progress_status = QLabel("就緒")
        self.lbl_progress_status.setStyleSheet("color: #a0a0ab;")
        bottom_box.addWidget(self.lbl_progress_status)
        bottom_box.addWidget(self.progress_bar)

        btn_box = QHBoxLayout()

        # 核心按鈕 1：加入批次佇列
        self.btn_add_to_queue = QPushButton("➕ 加入批次佇列 (Queue)")
        self.btn_add_to_queue.setStyleSheet("background-color: #2e6040; border-color: #00ff88; font-weight: bold; font-size: 13px;")
        self.btn_add_to_queue.setEnabled(False)
        self.btn_add_to_queue.clicked.connect(self._on_add_to_queue)

        # 核心按鈕 2：立即單部合成
        self.btn_start = QPushButton("🚀 立即單部合成")
        self.btn_start.setObjectName("btn_primary")
        self.btn_start.setEnabled(False)
        self.btn_start.clicked.connect(self._on_start_render)

        # 控制按鈕
        self.btn_cancel = QPushButton("⏹ 停止")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self._on_cancel_render)

        self.btn_open_folder = QPushButton("📁 開啟輸出資料夾")
        self.btn_open_folder.setEnabled(False)
        self.btn_open_folder.clicked.connect(self._on_open_folder)

        btn_box.addWidget(self.btn_add_to_queue, stretch=2)
        btn_box.addWidget(self.btn_start, stretch=2)
        btn_box.addWidget(self.btn_cancel, stretch=1)
        btn_box.addWidget(self.btn_open_folder, stretch=1)
        bottom_box.addLayout(btn_box)

        layout.addLayout(bottom_box)

    def _setup_queue_tab(self, parent: QWidget):
        """建置批次佇列排程管理員面板"""
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # 頂部工具按鈕列
        top_bar = QHBoxLayout()

        self.btn_queue_start = QPushButton("▶ 啟動佇列批次合成")
        self.btn_queue_start.setObjectName("btn_primary")
        self.btn_queue_start.clicked.connect(self._on_queue_start)

        self.btn_queue_pause = QPushButton("⏸ 暫停佇列（保留斷點）")
        self.btn_queue_pause.setEnabled(False)
        self.btn_queue_pause.clicked.connect(self._on_queue_pause)

        self.btn_queue_stop = QPushButton("⏹ 停止當前任務")
        self.btn_queue_stop.setEnabled(False)
        self.btn_queue_stop.clicked.connect(self._on_queue_stop)

        self.btn_queue_up = QPushButton("⬆ 上移")
        self.btn_queue_up.clicked.connect(self._on_queue_move_up)

        self.btn_queue_down = QPushButton("⬇ 下移")
        self.btn_queue_down.clicked.connect(self._on_queue_move_down)

        self.btn_queue_remove = QPushButton("🗑 移除任務")
        self.btn_queue_remove.clicked.connect(self._on_queue_remove_task)

        self.btn_queue_clear_done = QPushButton("🧹 清除已完成")
        self.btn_queue_clear_done.clicked.connect(self._on_queue_clear_done)

        self.btn_queue_clean_cache = QPushButton("🗄 一鍵清理暫存快取")
        self.btn_queue_clean_cache.clicked.connect(self._on_clean_disk_cache)

        top_bar.addWidget(self.btn_queue_start)
        top_bar.addWidget(self.btn_queue_pause)
        top_bar.addWidget(self.btn_queue_stop)
        top_bar.addSpacing(10)
        top_bar.addWidget(self.btn_queue_up)
        top_bar.addWidget(self.btn_queue_down)
        top_bar.addWidget(self.btn_queue_remove)
        top_bar.addSpacing(10)
        top_bar.addWidget(self.btn_queue_clear_done)
        top_bar.addWidget(self.btn_queue_clean_cache)
        top_bar.addStretch()

        layout.addLayout(top_bar)

        # 佇列清單表格
        self.queue_table = QTableWidget()
        self.queue_table.setColumnCount(8)
        self.queue_table.setHorizontalHeaderLabels([
            "啟用", "順序", "相簿任務名稱", "輸出畫質規格", "項數", "進度", "狀態說明", "輸出目標路徑"
        ])
        self.queue_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.queue_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.queue_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        self.queue_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        self.queue_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.queue_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Interactive)
        self.queue_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.Interactive)
        self.queue_table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeMode.Stretch)
        self.queue_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.queue_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.queue_table.itemChanged.connect(self._on_queue_table_item_changed)
        layout.addWidget(self.queue_table, stretch=2)

        # 底部狀態與總體控制
        bottom_frame = QFrame()
        bottom_layout = QVBoxLayout(bottom_frame)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(6)

        status_row = QHBoxLayout()
        self.lbl_queue_summary = QLabel("佇列狀態：目前共 0 個任務（待執行 0 個）")
        self.lbl_queue_summary.setStyleSheet("font-weight: bold; color: #00d2ff; font-size: 13px;")

        self.chk_auto_shutdown = QCheckBox("🌙 全部佇列任務完成後，自動將電腦關機（附 60 秒倒數防呆）")
        self.chk_auto_shutdown.setStyleSheet("color: #ffaa55; font-weight: bold;")
        self.chk_auto_shutdown.setChecked(self.queue_manager.auto_shutdown)
        self.chk_auto_shutdown.stateChanged.connect(self._on_auto_shutdown_toggled)

        status_row.addWidget(self.lbl_queue_summary)
        status_row.addStretch()
        status_row.addWidget(self.chk_auto_shutdown)
        bottom_layout.addLayout(status_row)

        self.queue_total_progress = QProgressBar()
        self.queue_total_progress.setValue(0)
        bottom_layout.addWidget(self.queue_total_progress)

        # 佇列即時日誌
        self.txt_queue_log = QTextEdit()
        self.txt_queue_log.setReadOnly(True)
        self.txt_queue_log.setMaximumHeight(140)
        bottom_layout.addWidget(self.txt_queue_log)

        layout.addWidget(bottom_frame)

    def _on_auto_shutdown_toggled(self, state):
        self.queue_manager.auto_shutdown = self.chk_auto_shutdown.isChecked()
        self.queue_manager.save_to_storage()

    def _on_add_to_queue(self):
        """將目前單一設定加入批次佇列"""
        if not self.selected_start_node:
            QMessageBox.warning(self, "未選擇起點", "請先在左側相簿目錄樹中點選一個起點資料夾！")
            return

        node = self.selected_start_node
        sorted_media = AlbumScanner.get_sorted_media_from_node(node)
        if not sorted_media:
            QMessageBox.warning(self, "無媒體項目", "所選目錄內沒有照片或影片！")
            return

        out_dir = self._get_effective_output_dir()
        if not out_dir or not self._is_dir_writable(out_dir):
            QMessageBox.critical(self, "權限不足", f"指定的輸出目錄無法寫入：\n{out_dir}\n請選擇本機有效資料夾！")
            return

        current_prof_id = self.combo_profile.currentData()
        prof = next((p for p in self.profiles if p["id"] == current_prof_id), self.profiles[0])
        target_name = node.name.replace(" ", "_")
        spec_tag = get_output_spec_tag(prof)
        out_video = os.path.join(out_dir, f"{target_name}_{spec_tag}.mp4")
        out_chap = os.path.join(out_dir, f"{target_name}_{spec_tag}_Chapters.txt")

        # 收集配置參數
        raw_concur = int(self.combo_concurrency.currentData())
        is_8k = "8k" in prof["id"].lower() or "8k" in prof.get("resolution", "").lower()
        effective_concur = raw_concur if raw_concur > 0 else calculate_safe_concurrency(self.total_ram_gb, is_8k, os.cpu_count() or 4)

        config_dict = {
            "resolution": prof["resolution"],
            "fps": prof["fps"],
            "vcodec": prof["vcodec"],
            "bitrate": prof["bitrate"],
            "maxrate": prof["maxrate"],
            "bufsize": prof["bufsize"],
            "image_duration": float(self.spin_duration.value()),
            "fill_mode": self.combo_fill.currentData(),
            "enable_auto_split": self.chk_auto_split.isChecked(),
            "max_duration_seconds": float(self.combo_max_dur.currentData()),
            "max_size_gb": float(self.combo_max_size.currentData()),
            "concurrency": effective_concur,
        }

        task = BatchTask(
            name=node.name,
            source_dir=node.dir_path,
            output_dir=out_dir,
            profile_id=prof["id"],
            profile_name=prof["name"],
            config_dict=config_dict,
            total_items=len(sorted_media),
            output_video_path=out_video,
            output_chapter_path=out_chap,
        )

        self.queue_manager.add_task(task)
        self._refresh_queue_table()

        self._log(f"✓【佇列】已成功將相簿『{node.name}』加入批次排程佇列（共 {len(sorted_media)} 項，目標：{spec_tag}）")
        self.txt_queue_log.append(f"[新增] 任務『{node.name}』已排入佇列末尾。")

        # 更新 Tab 標籤提示
        self.tab_widget.setTabText(1, f"📋 批次排程佇列 ({len(self.queue_manager.tasks)})")

        reply = QMessageBox.information(
            self,
            "已加入佇列",
            f"已成功將『{node.name}』排入批次工作清單！\n\n"
            f"目標規格：{prof['name']}\n"
            f"媒體數量：{len(sorted_media)} 個檔案\n"
            f"輸出位置：{out_video}\n\n"
            f"是否立刻切換到【批次排程佇列】面板檢視？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.tab_widget.setCurrentIndex(1)

    def _refresh_queue_table(self):
        """重新整理批次佇列表格顯示"""
        self.queue_table.blockSignals(True)
        self.queue_table.setRowCount(len(self.queue_manager.tasks))

        waiting_count = 0
        completed_count = 0

        for row, task in enumerate(self.queue_manager.tasks):
            # 0. 啟用勾選框
            chk_item = QTableWidgetItem()
            chk_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            chk_item.setCheckState(Qt.CheckState.Checked if task.enabled else Qt.CheckState.Unchecked)
            chk_item.setData(Qt.ItemDataRole.UserRole, task.task_id)
            self.queue_table.setItem(row, 0, chk_item)

            # 1. 序號
            item_order = QTableWidgetItem(f"#{row + 1:02d}")
            item_order.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item_order.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.queue_table.setItem(row, 1, item_order)

            # 2. 任務名稱
            item_name = QTableWidgetItem(task.name)
            item_name.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.queue_table.setItem(row, 2, item_name)

            # 3. 畫質規格
            item_prof = QTableWidgetItem(task.profile_name)
            item_prof.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.queue_table.setItem(row, 3, item_prof)

            # 4. 項數
            item_cnt = QTableWidgetItem(f"{task.total_items} 個")
            item_cnt.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item_cnt.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.queue_table.setItem(row, 4, item_cnt)

            # 5. 進度
            item_prog = QTableWidgetItem(f"{task.progress_percent}%")
            item_prog.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item_prog.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.queue_table.setItem(row, 5, item_prog)

            # 6. 狀態說明
            status_map = {
                "waiting": ("⚪ 等待中", "#a0a0ab"),
                "running": ("🟢 處理中...", "#00ff88"),
                "paused": ("🟡 已暫停 (斷點已保留)", "#ffbb33"),
                "completed": ("✓ 已完成", "#55ccff"),
                "cancelled": ("⏹ 已停止", "#ff5555"),
                "failed": ("❌ 失敗", "#ff4444"),
            }
            s_text, s_color = status_map.get(task.status, (task.status, "#ffffff"))
            item_status = QTableWidgetItem(f"{s_text} - {task.status_message}")
            item_status.setForeground(Qt.GlobalColor.white)
            item_status.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.queue_table.setItem(row, 6, item_status)

            # 7. 輸出路徑
            item_out = QTableWidgetItem(task.output_video_path)
            item_out.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.queue_table.setItem(row, 7, item_out)

            if task.status in ["waiting", "paused"]:
                waiting_count += 1
            elif task.status == "completed":
                completed_count += 1

        self.queue_table.blockSignals(False)

        # 更新統計列
        total_tasks = len(self.queue_manager.tasks)
        self.lbl_queue_summary.setText(
            f"佇列狀態：共 {total_tasks} 個任務｜待處理：{waiting_count} 個｜已完成：{completed_count} 個"
        )
        overall_pct = int((completed_count / total_tasks * 100)) if total_tasks > 0 else 0
        self.queue_total_progress.setValue(overall_pct)
        self.tab_widget.setTabText(1, f"📋 批次排程佇列 ({total_tasks})")

    def _on_queue_table_item_changed(self, item: QTableWidgetItem):
        if item.column() == 0:
            task_id = item.data(Qt.ItemDataRole.UserRole)
            is_checked = item.checkState() == Qt.CheckState.Checked
            self.queue_manager.toggle_enabled(task_id, is_checked)
            self._refresh_queue_table()

    def _on_queue_move_up(self):
        selected = self.queue_table.currentRow()
        if selected > 0:
            task = self.queue_manager.tasks[selected]
            self.queue_manager.move_up(task.task_id)
            self._refresh_queue_table()
            self.queue_table.selectRow(selected - 1)

    def _on_queue_move_down(self):
        selected = self.queue_table.currentRow()
        if 0 <= selected < len(self.queue_manager.tasks) - 1:
            task = self.queue_manager.tasks[selected]
            self.queue_manager.move_down(task.task_id)
            self._refresh_queue_table()
            self.queue_table.selectRow(selected + 1)

    def _on_queue_remove_task(self):
        selected = self.queue_table.currentRow()
        if 0 <= selected < len(self.queue_manager.tasks):
            task = self.queue_manager.tasks[selected]
            if task.status == "running":
                QMessageBox.warning(self, "無法移除", "正在處理中的任務無法直接刪除，請先按『停止當前任務』！")
                return
            reply = QMessageBox.question(
                self, "確認移除", f"確定要從排程佇列中移除『{task.name}』嗎？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.queue_manager.remove_task(task.task_id)
                self._refresh_queue_table()

    def _on_queue_clear_done(self):
        removed = self.queue_manager.clear_completed()
        self._refresh_queue_table()
        self.txt_queue_log.append(f"[清理] 已自佇列中移除 {removed} 個已完成之任務。")

    def _on_clean_disk_cache(self):
        """一鍵掃描並清除輸出目錄下的暫存快取目錄"""
        out_dir = self._get_effective_output_dir()
        if not out_dir or not os.path.exists(out_dir):
            out_dir = QFileDialog.getExistingDirectory(self, "請選擇欲清理快取的目標資料夾")
            if not out_dir:
                return

        count, freed_mb = VideoRenderEngine.clean_cache_directories(out_dir)
        size_str = f"{freed_mb:.1f} MB" if freed_mb < 1024 else f"{freed_mb / 1024:.2f} GB"
        QMessageBox.information(
            self,
            "快取清理完成",
            f"已成功掃描並清理資料夾：\n{out_dir}\n\n"
            f"共刪除 {count} 個殘留暫存快取目錄！\n"
            f"已釋放出約 {size_str} 的硬碟空間！"
        )
        self.txt_queue_log.append(f"🧹【清理完成】已在 {out_dir} 清理 {count} 個快取目錄，釋放 {size_str} 空間。")

    # ================= 批次佇列驅動引擎 =================

    def _on_queue_start(self):
        """啟動批次佇列排程"""
        self.queue_manager.is_queue_running = True
        self.is_single_mode = False
        self.btn_queue_start.setEnabled(False)
        self.btn_queue_pause.setEnabled(True)
        self.btn_queue_stop.setEnabled(True)
        self.btn_start.setEnabled(False)
        self.btn_cancel.setEnabled(True)

        self.txt_queue_log.append("🚀【佇列啟動】批次轉檔引擎已啟動，開始循序處理佇列任務...")
        self._process_next_queue_task()

    def _process_next_queue_task(self):
        """處理佇列中的下一個任務"""
        if not self.queue_manager.is_queue_running:
            return

        task = self.queue_manager.get_next_runnable_task()
        if not task:
            # 佇列全部完成
            self.queue_manager.is_queue_running = False
            self.btn_queue_start.setEnabled(True)
            self.btn_queue_pause.setEnabled(False)
            self.btn_queue_stop.setEnabled(False)
            self.btn_start.setEnabled(True)
            self.btn_cancel.setEnabled(False)
            self._refresh_queue_table()

            self.txt_queue_log.append("\n🎉【全部完成】批次排程佇列中所有已啟用任務已全數成功產出完畢！")

            if self.chk_auto_shutdown.isChecked():
                self._trigger_auto_shutdown()
            else:
                QMessageBox.information(self, "佇列完成", "🎉 批次佇列中所有已啟用的影片任務已全部合成完畢！")
            return

        # 開始執行當前任務
        self.queue_manager.current_task_id = task.task_id
        self.queue_manager.mark_task_status(task.task_id, "running", "正在分析與渲染中...")
        self._refresh_queue_table()

        self.txt_queue_log.append(f"\n==================================================")
        self.txt_queue_log.append(f"▶ 開始處理佇列任務：『{task.name}』")
        self.txt_queue_log.append(f"  來源相簿：{task.source_dir}")
        self.txt_queue_log.append(f"  目標規格：{task.profile_name}")
        self.txt_queue_log.append(f"  輸出影片：{task.output_video_path}")
        self.txt_queue_log.append(f"==================================================")

        # 掃描媒體項目
        root = AlbumScanner.scan_directory_tree(task.source_dir)
        if not root:
            self.queue_manager.mark_task_status(task.task_id, "failed", "無法讀取來源目錄")
            self._refresh_queue_table()
            self._process_next_queue_task()
            return

        sorted_media = AlbumScanner.get_sorted_media_from_node(root)
        if not sorted_media:
            self.queue_manager.mark_task_status(task.task_id, "failed", "來源目錄無媒體檔案")
            self._refresh_queue_table()
            self._process_next_queue_task()
            return

        cfg_d = task.config_dict
        config = RenderConfig(
            resolution=cfg_d.get("resolution", "7680x4320"),
            fps=cfg_d.get("fps", 60),
            vcodec=cfg_d.get("vcodec", "hevc_qsv"),
            bitrate=cfg_d.get("bitrate", "240M"),
            maxrate=cfg_d.get("maxrate", "260M"),
            bufsize=cfg_d.get("bufsize", "480M"),
            image_duration=cfg_d.get("image_duration", 3.0),
            fill_mode=cfg_d.get("fill_mode", "black"),
            audio_bitrate="512k",
            audio_samplerate=48000,
            enable_auto_split=cfg_d.get("enable_auto_split", True),
            max_duration_seconds=cfg_d.get("max_duration_seconds", 42000.0),
            max_size_gb=cfg_d.get("max_size_gb", 240.0),
            concurrency=cfg_d.get("concurrency", 4),
        )

        engine = VideoRenderEngine(config)
        self.worker = RenderWorker(
            engine, sorted_media, task.output_video_path, task.output_chapter_path, task.name
        )

        def _on_queue_worker_progress(current, total, msg):
            pct = int((current / total) * 100) if total > 0 else 0
            task.progress_percent = pct
            task.status_message = msg
            self.progress_bar.setValue(pct)
            self.lbl_progress_status.setText(f"【{task.name}】{msg}")
            # 更新表格單一列進度
            for r in range(self.queue_table.rowCount()):
                chk = self.queue_table.item(r, 0)
                if chk and chk.data(Qt.ItemDataRole.UserRole) == task.task_id:
                    self.queue_table.item(r, 5).setText(f"{pct}%")
                    self.queue_table.item(r, 6).setText(f"🟢 處理中 - {msg}")
                    break

        self.worker.progress_signal.connect(_on_queue_worker_progress)
        self.worker.log_signal.connect(lambda m: self.txt_queue_log.append(m))
        self.worker.finished_signal.connect(self._on_queue_task_finished)
        self.worker.start()

    def _on_queue_task_finished(self, success: bool, message: str):
        task_id = self.queue_manager.current_task_id
        task = self.queue_manager.get_task(task_id) if task_id else None

        if not task:
            return

        is_user_cancelled = self.worker and self.worker.engine._is_cancelled

        if success:
            task.status = "completed"
            task.progress_percent = 100
            task.status_message = "已完成產出"
            self.txt_queue_log.append(f"✓【完成】任務『{task.name}』已成功產出完畢！")
        elif is_user_cancelled:
            task.status = "paused"
            task.status_message = "已暫停（斷點已保留）"
            self.txt_queue_log.append(f"⏸【暫停】任務『{task.name}』已中斷暫停，進度快取已安全保留，下次啟動可無縫接續！")
        else:
            task.status = "failed"
            task.status_message = f"失敗：{message}"
            self.txt_queue_log.append(f"❌【失敗】任務『{task.name}』處理異常：{message}")

        self.queue_manager.save_to_storage()
        self._refresh_queue_table()

        # 若使用者暫停了佇列，不再往下執行
        if is_user_cancelled or not self.queue_manager.is_queue_running:
            self.btn_queue_start.setEnabled(True)
            self.btn_queue_pause.setEnabled(False)
            self.btn_queue_stop.setEnabled(False)
            self.btn_start.setEnabled(True)
            self.btn_cancel.setEnabled(False)
            return

        # 繼續下一個佇列任務
        QTimer.singleShot(1000, self._process_next_queue_task)

    def _on_queue_pause(self):
        """暫停批次佇列"""
        self.queue_manager.is_queue_running = False
        self.btn_queue_pause.setEnabled(False)
        self.txt_queue_log.append("⏸【佇列暫停】正在暫停當前任務並保留快取進度...")
        if self.worker and self.worker.isRunning():
            self.worker.stop()

    def _on_queue_stop(self):
        """停止當前佇列任務"""
        self.queue_manager.is_queue_running = False
        self.btn_queue_stop.setEnabled(False)
        self.txt_queue_log.append("⏹【停止】正在停止當前工作...")
        if self.worker and self.worker.isRunning():
            self.worker.stop()

    def _trigger_auto_shutdown(self):
        """觸發 Windows 60 秒安全自動關機（附帶取消對話框）"""
        self.txt_queue_log.append("🌙【自動關機】佇列任務全數完成！系統即將在 60 秒後自動關機...")
        if os.name == "nt":
            subprocess.run(["shutdown", "-s", "-t", "60", "-c", "PhotoToVideo 批次排程已全數完成！電腦將在 60 秒後自動關機，如欲取消請按取消關機按鈕。"])
            reply = QMessageBox.warning(
                self,
                "電腦即將關機",
                "🌙 所有批次佇列任務已全數完成！\n\n系統已啟動 60 秒自動關機倒數。\n若您現在仍在使用電腦，請點選下方按鈕取消關機！",
                QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Ok,
                QMessageBox.StandardButton.Cancel,
            )
            if reply == QMessageBox.StandardButton.Cancel:
                subprocess.run(["shutdown", "-a"])
                self.txt_queue_log.append("✓【取消關機】使用者已手動取消自動關機排程！")

    # ================= 單一模式邏輯 (向下相容) =================

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
            hw_summary = self.hardware_detector.get_hardware_status_summary()
            self._log("--------------------------------------------------")
            self._log("【本電腦實體硬體加速探測結果（動態實測）】")
            for k, info in hw_summary.items():
                mark = "[支援 🟢]" if info["light"] == "green" else "[無硬體 ⚪]"
                self._log(f"  {mark} {info['label']} -> {info['desc']}")
            self._log("--------------------------------------------------")
            self._log("已自動為您預選本電腦真正支援的最佳最高畫質設定檔！\n")

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
        self.btn_add_to_queue.setEnabled(True)
        self._update_stats_estimate()

    def _on_select_8k_preset(self):
        """一鍵選定 8K 超高畫質首選設定檔"""
        self.btn_preset_8k.setChecked(True)
        self.btn_preset_4k.setChecked(False)
        for idx, prof in enumerate(self.profiles):
            if "8k" in prof["id"].lower() or "8k" in prof.get("resolution", "").lower():
                self.combo_profile.setCurrentIndex(idx)
                break

    def _on_select_4k_preset(self):
        """一鍵選定 4K 高畫質設定檔"""
        self.btn_preset_4k.setChecked(True)
        self.btn_preset_8k.setChecked(False)
        for idx, prof in enumerate(self.profiles):
            if "4k" in prof["id"].lower() or "4k" in prof.get("resolution", "").lower():
                self.combo_profile.setCurrentIndex(idx)
                break

    def _on_profile_combo_changed(self):
        """當使用者微調下拉選單時，同步更新 K 數切換鈕與狀態評估"""
        current_prof_id = self.combo_profile.currentData()
        prof = next((p for p in self.profiles if p["id"] == current_prof_id), self.profiles[0])
        is_8k = "8k" in prof["id"].lower() or "8k" in prof.get("resolution", "").lower()
        self.btn_preset_8k.setChecked(is_8k)
        self.btn_preset_4k.setChecked(not is_8k)
        self._update_stats_estimate()

    def _update_stats_estimate(self):
        current_prof_id = self.combo_profile.currentData()
        prof = next((p for p in self.profiles if p["id"] == current_prof_id), self.profiles[0])
        hw_type = prof.get("hw_type", "硬體加速")
        is_cpu = "CPU" in hw_type
        if is_cpu:
            self.lbl_active_hw_status.setText(f"🎯 目前選取：🟡【{hw_type} 軟體運算（視覺無損 · 100% 穩定相容）】")
            self.lbl_active_hw_status.setStyleSheet(
                "color: #ffd166; font-weight: bold; font-size: 13px; margin-top: 4px; padding-top: 4px; border-top: 1px dashed #3d3d4a;"
            )
        else:
            self.lbl_active_hw_status.setText(f"🎯 目前選取：🟢【{hw_type} 硬體極速加速（遇顯存限制自動切換同畫質軟解，絕不中斷）】")
            self.lbl_active_hw_status.setStyleSheet(
                "color: #06d6a0; font-weight: bold; font-size: 13px; margin-top: 4px; padding-top: 4px; border-top: 1px dashed #3d3d4a;"
            )

        self._update_memory_safeguard_status()

        if not self.selected_start_node:
            return

        node = self.selected_start_node
        img_count = node.total_images_count()
        vid_count = node.total_videos_count()
        img_sec = self.spin_duration.value()

        all_media = node.collect_all_media()
        img_sec_total = img_count * img_sec
        # 統計影片時長（若 MediaItem 有解析則精準累加，否則預設 10 秒/支）
        vid_sec_total = sum(
            m.duration if (m.is_video and m.duration > 0) else (10.0 if m.is_video else 0.0)
            for m in all_media
        )
        est_sec = img_sec_total + vid_sec_total

        h = int(est_sec // 3600)
        m = int((est_sec % 3600) // 60)
        s = int(est_sec % 60)
        duration_str = f"{h} 小時 {m} 分 {s} 秒" if h > 0 else f"{m} 分 {s} 秒"

        bitrate_str = prof.get("bitrate", "240M")
        bitrate_num = int(bitrate_str.replace("M", "").replace("k", ""))
        gb_per_sec = (bitrate_num / (8 * 1024)) if "M" in bitrate_str else (bitrate_num / (8 * 1024 * 1024))
        audio_gb_per_sec = (AUDIO_BITRATE_KBPS / (8 * 1024 * 1024))

        # 智慧混合精準容量估算模型：靜態相片約 52%，動態影片約 92%
        est_img_gb = img_sec_total * (gb_per_sec * PHOTO_BITRATE_RATIO + audio_gb_per_sec)
        est_vid_gb = vid_sec_total * (gb_per_sec * VIDEO_BITRATE_RATIO + audio_gb_per_sec)
        est_actual_gb = est_img_gb + est_vid_gb
        est_theoretical_max_gb = est_sec * (gb_per_sec + audio_gb_per_sec)

        is_auto_split = self.chk_auto_split.isChecked()
        max_dur = self.combo_max_dur.currentData()
        max_size = self.combo_max_size.currentData()

        # 分段估算以「真實精準預估容量」與「總時長」兩者綜合評定，絕不提前過早切檔
        est_parts_by_dur = int(est_sec // max_dur) + (1 if est_sec % max_dur > 0 else 0)
        est_parts_by_size = int(est_actual_gb // max_size) + (1 if est_actual_gb % max_size > 0 else 0)
        estimated_parts = max(est_parts_by_dur, est_parts_by_size, 1)

        self.lbl_stat_target.setText(f"起點目標：【{node.name}】（包含其所有子資料夾）")
        self.lbl_stat_counts.setText(f"包含媒體：相片 {img_count} 張 / 影片 {vid_count} 支 (共 {img_count + vid_count} 個項目)")
        self.lbl_stat_est_duration.setText(f"預估總時長：約 {duration_str}")
        self.lbl_stat_est_size.setText(
            f"預估輸出容量：約 {est_actual_gb:.1f} GB (相片約 {est_img_gb:.1f} GB、影片約 {est_vid_gb:.1f} GB · 理論上限 {est_theoretical_max_gb:.1f} GB)"
        )

        if is_auto_split and estimated_parts > 1:
            split_reasons = []
            if est_parts_by_dur > 1:
                split_reasons.append(f"總時長超過 {max_dur/3600:.1f} 小時")
            if est_parts_by_size > 1:
                split_reasons.append(f"預估容量超過 {max_size:.0f} GB")
            reason_str = " 與 ".join(split_reasons) if split_reasons else "達到 YouTube 安全上限"
            self.lbl_stat_split_info.setText(
                f"分段狀態：⚠️ 偵測到超標（{reason_str}）！系統將自動切分為 {estimated_parts} 個 Parts 備份"
            )
            self.lbl_stat_split_info.setStyleSheet("color: #ffd166; font-weight: bold;")
        else:
            self.lbl_stat_split_info.setText("分段狀態：✓ 安全範圍內，將合併為單一 8K/4K 頂級備份影片")
            self.lbl_stat_split_info.setStyleSheet("color: #06d6a0;")

        out_dir = self._get_effective_output_dir()
        target_name = node.name.replace(" ", "_")
        spec_tag = get_output_spec_tag(prof)
        if out_dir:
            self.lbl_output_filename.setText(f"預定輸出影片：{os.path.join(out_dir, f'{target_name}_{spec_tag}.mp4')}")
            self.lbl_output_chapter.setText(f"預定章節檔案：{os.path.join(out_dir, f'{target_name}_{spec_tag}_Chapters.txt')}")
        else:
            self.lbl_output_filename.setText("預定輸出影片：(請指定輸出目錄)")
            self.lbl_output_chapter.setText("預定章節檔案：(請指定輸出目錄)")

    def _update_memory_safeguard_status(self):
        current_prof_id = self.combo_profile.currentData()
        prof = next((p for p in self.profiles if p["id"] == current_prof_id), self.profiles[0])
        is_8k = "8k" in prof["id"].lower() or "8k" in prof.get("resolution", "").lower()
        res_name = "8K" if is_8k else "4K"

        raw_concur = int(self.combo_concurrency.currentData())
        cpu_count = os.cpu_count() or 4
        if raw_concur <= 0:
            eff_concur = calculate_safe_concurrency(self.total_ram_gb, is_8k, cpu_count)
            is_auto = True
        else:
            eff_concur = raw_concur
            is_auto = False

        per_proc_ram = 1.8 if is_8k else 0.4
        sys_reserved = 6.0
        est_peak_ram = eff_concur * per_proc_ram + sys_reserved
        ram_percent = min(100.0, (est_peak_ram / max(self.total_ram_gb, 1.0)) * 100.0)

        if est_peak_ram <= self.total_ram_gb * 0.85:
            self.lbl_memory_safeguard.setText(
                f"🟢 <b>記憶體安全（SSD 極致保護）</b>：{'[智慧推薦] ' if is_auto else ''}當前配置 {eff_concur} 緒平行處理\n"
                f"   目標：{res_name} 模式｜預估尖峰 RAM 佔用：約 {est_peak_ram:.1f} GB / 實體 {self.total_ram_gb:.1f} GB ({ram_percent:.0f}%)\n"
                f"   實體 RAM 空間充裕，完全不會觸發 SSD SWAP 換頁，極限保護硬碟壽命！"
            )
            self.lbl_memory_safeguard.setStyleSheet(
                "color: #a0f0a0; font-size: 12px; background: rgba(0, 255, 128, 0.08); padding: 6px; border-radius: 4px; border: 1px solid rgba(0, 255, 128, 0.2);"
            )
        elif est_peak_ram <= self.total_ram_gb * 0.95:
            self.lbl_memory_safeguard.setText(
                f"🟠 <b>記憶體警戒（接近上限）</b>：當前配置 {eff_concur} 緒\n"
                f"   目標：{res_name} 模式｜預估尖峰 RAM 佔用：約 {est_peak_ram:.1f} GB / 實體 {self.total_ram_gb:.1f} GB ({ram_percent:.0f}%)\n"
                f"   可能偶發觸發 Windows 虛擬記憶體交換。建議降低至 4~6 緒以徹底保護 SSD！"
            )
            self.lbl_memory_safeguard.setStyleSheet(
                "color: #ffa500; font-size: 12px; background: rgba(255, 165, 0, 0.08); padding: 6px; border-radius: 4px; border: 1px solid rgba(255, 165, 0, 0.2);"
            )
        else:
            self.lbl_memory_safeguard.setText(
                f"🔴 <b>記憶體超標危險（極度傷 SSD）</b>：當前配置 {eff_concur} 緒\n"
                f"   目標：{res_name} 模式｜預估尖峰 RAM 佔用：約 {est_peak_ram:.1f} GB / 實體 {self.total_ram_gb:.1f} GB ({ram_percent:.0f}%)\n"
                f"   實體 RAM 將被吃滿並強制在 SSD 上大量 SWAP 換頁磨損壽命！強烈建議切換為『智慧記憶體防護推薦』！"
            )
            self.lbl_memory_safeguard.setStyleSheet(
                "color: #ff6b6b; font-size: 12px; font-weight: bold; background: rgba(255, 80, 80, 0.12); padding: 6px; border-radius: 4px; border: 1px solid rgba(255, 80, 80, 0.3);"
            )

    def _on_start_render(self):
        """立即單部合成"""
        self.is_single_mode = True
        self._update_memory_safeguard_status()

        if not self.selected_start_node:
            return

        node = self.selected_start_node
        sorted_media = AlbumScanner.get_sorted_media_from_node(node)
        if not sorted_media:
            QMessageBox.warning(self, "無媒體項目", "所選起點目錄內沒有可處理的照片或影片！")
            return

        out_dir = self._get_effective_output_dir()
        if not out_dir or not self._is_dir_writable(out_dir):
            QMessageBox.critical(self, "目錄權限不足", f"指定的輸出目錄無法寫入：\n{out_dir}\n請選擇本機有效資料夾！")
            return

        current_prof_id = self.combo_profile.currentData()
        prof = next((p for p in self.profiles if p["id"] == current_prof_id), self.profiles[0])
        raw_concur = int(self.combo_concurrency.currentData())
        is_8k = "8k" in prof["id"].lower() or "8k" in prof.get("resolution", "").lower()
        effective_concur = raw_concur if raw_concur > 0 else calculate_safe_concurrency(self.total_ram_gb, is_8k, os.cpu_count() or 4)

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
            concurrency=effective_concur,
        )

        self.last_output_dir = out_dir
        target_name = node.name.replace(" ", "_")
        spec_tag = get_output_spec_tag(prof)
        out_video = os.path.join(out_dir, f"{target_name}_{spec_tag}.mp4")
        out_chap = os.path.join(out_dir, f"{target_name}_{spec_tag}_Chapters.txt")

        self.btn_start.setEnabled(False)
        self.btn_add_to_queue.setEnabled(False)
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
        self.btn_add_to_queue.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.btn_open_folder.setEnabled(True)
        self.btn_select_root.setEnabled(True)

        is_user_cancelled = self.worker and self.worker.engine._is_cancelled

        if success:
            self.progress_bar.setValue(100)
            self.lbl_progress_status.setText("完成！備份影片已全部合成。")
            QMessageBox.information(
                self,
                "備份完成",
                f"備份影片與對應的 YouTube 章節檔案已產生完畢！\n\n路徑：\n{self.last_output_dir}",
            )
        elif is_user_cancelled:
            self.progress_bar.setValue(0)
            self.lbl_progress_status.setText("合成程序已手動中止，已完成之進度快取已安全保留。")
            self._log("✓【暫停/中止】所有背景程序已秒級退出！進度快取安全保留，下次啟動可無縫接續！")
            QMessageBox.information(
                self,
                "任務已中止",
                "合成程序已成功中止！\n所有已完成的進度快取已安全保留於磁碟，下次可秒級斷點接續。",
            )
        else:
            self.lbl_progress_status.setText("處理失敗或異常中斷。")
            QMessageBox.critical(self, "錯誤", f"處理失敗：\n{message}")

    def _on_cancel_render(self):
        if self.worker and self.worker.isRunning():
            self.btn_cancel.setEnabled(False)
            self.lbl_progress_status.setText("正在強制中止所有渲染工作並保留進度快取...")
            self._log("【中止】正在關閉背景程序，並安全保留斷點快取...")
            self.worker.stop()

    def _on_open_folder(self):
        if self.last_output_dir and os.path.exists(self.last_output_dir):
            if os.name == "nt":
                os.startfile(self.last_output_dir)
            else:
                subprocess.run(["xdg-open", self.last_output_dir])
