"""
YouTube 章節時間軸生成模組
自動產生符合 YouTube 官方規範的說明欄章節文字檔（Chapters.txt）
包含子目錄大章節標題、拍攝日期、時間與原始檔案名稱
支援多 Part 分段標記
"""

import os
from typing import List, Tuple
from core.scanner import MediaItem


def format_timestamp(seconds: float) -> str:
    """將秒數轉換為 YouTube 認可的 HH:MM:SS 或 MM:SS 格式"""
    total_sec = int(seconds)
    hours = total_sec // 3600
    minutes = (total_sec % 3600) // 60
    secs = total_sec % 60

    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    else:
        return f"{minutes:02d}:{secs:02d}"


class ChapterGenerator:
    """YouTube 章節生成器"""

    def __init__(self, target_title: str, part_index: int = 1, total_parts: int = 1):
        self.target_title = target_title
        self.part_index = part_index
        self.total_parts = total_parts
        # 儲存 (開始秒數, 章節標題, 所屬分類)
        self.entries: List[Tuple[float, str, str]] = []

    def add_entry(self, start_seconds: float, title: str, category: str = ""):
        self.entries.append((start_seconds, title, category))

    def generate_youtube_text(self) -> str:
        """
        生成可直接複製貼上至 YouTube 說明欄的文字內容
        """
        part_tag = f" [Part {self.part_index:02d}/{self.total_parts:02d}]" if self.total_parts > 1 else ""
        lines = [
            f"=== 8K 極致備份影片章節索引：{self.target_title}{part_tag} ===",
            "（複製以下內容貼至 YouTube 影片說明欄，即可自動啟用章節進度條）",
            "",
            "【時間軸目錄】",
        ]

        # YouTube 規範第一條時間戳記必須為 00:00
        if not self.entries or self.entries[0][0] > 0.0:
            lines.append("00:00 開始播放")

        current_category = None
        for start_sec, title, category in self.entries:
            ts_str = format_timestamp(start_sec)
            if category and category != current_category:
                current_category = category
                lines.append(f"\n--- 【{category}】 ---")

            lines.append(f"{ts_str} {title}")

        lines.append("\n==========================================")
        lines.append(f"總共收錄項目數：{len(self.entries)}")
        return "\n".join(lines)

    def save_to_file(self, output_path: str):
        """將章節文字寫入檔案（UTF-8 編碼）"""
        content = self.generate_youtube_text()
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)
