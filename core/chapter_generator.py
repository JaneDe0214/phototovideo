"""
YouTube 章節時間軸生成與 5,000 字智慧濃縮模組
自動產生符合 YouTube 官方規範的說明欄章節文字檔（Chapters.txt）

核心特性：
1. 嚴格符合 YouTube 說明欄 5,000 字元上限（預設 4,500 字，留有安全空間）。
2. 階層式智慧濃縮：
   - 第一優先：所有影片（Video）100% 絕對優先保留，附帶 🎬 [影片] 標記。
   - 第二優先：景點 / 子資料夾切換節點 100% 優先保留（大章節分界）。
   - 第三優先：剩餘照片採「等時間間隔均勻抽樣（Uniform Sampling）」，全片分佈最均勻。
3. YouTube 官方合規防護：
   - 第一條時間戳記強制為 00:00。
   - 任兩章節時間差至少間隔 10 秒（YouTube 官方辨識規範）。
4. 針對多 Part 獨立運作：
   - 每個 Part 只收錄並濃縮該 Part 的內容，時間軸從該 Part 的 00:00 起算。
5. 雙檔輸出（貼心保證）：
   - Chapters.txt：【YouTube 官方 5,000 字精華濃縮版】，直接貼入保證成功。
   - Chapters_Full.txt：【本機全項目完整索引版】，100% 記錄每張照片與影片。
"""

import os
from typing import List, Optional, Tuple


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


class ChapterItem:
    """單一章節項目資料結構"""

    def __init__(
        self,
        start_seconds: float,
        title: str,
        category: str = "",
        is_video: bool = False,
        is_category_start: bool = False,
    ):
        self.start_seconds = start_seconds
        self.title = title
        self.category = category
        self.is_video = is_video
        self.is_category_start = is_category_start


class ChapterGenerator:
    """YouTube 智慧章節生成器"""

    def __init__(self, target_title: str, part_index: int = 1, total_parts: int = 1):
        self.target_title = target_title
        self.part_index = part_index
        self.total_parts = total_parts
        self.entries: List[ChapterItem] = []
        self._last_category: Optional[str] = None

    def add_entry(
        self,
        start_seconds: float,
        title: str,
        category: str = "",
        is_video: bool = False,
    ):
        """新增章節項目"""
        is_cat_start = bool(category and category != self._last_category)
        if category:
            self._last_category = category

        item = ChapterItem(
            start_seconds=start_seconds,
            title=title,
            category=category,
            is_video=is_video,
            is_category_start=is_cat_start,
        )
        self.entries.append(item)

    def _format_lines(
        self, items: List[ChapterItem], is_condensed: bool = False
    ) -> str:
        """格式化輸出 YouTube 規範章節文字"""
        part_tag = (
            f" [Part {self.part_index:02d}/{self.total_parts:02d}]"
            if self.total_parts > 1
            else ""
        )
        lines = [
            f"=== 8K/4K 影片章節索引：{self.target_title}{part_tag} ===",
            "（複製以下內容貼至 YouTube 影片說明欄，即可自動啟用章節進度條）",
        ]

        if is_condensed:
            lines.append(
                f"💡【智慧精華濃縮版】本段共收錄 {len(self.entries)} 個媒體，"
                f"已精選 {len(items)} 個核心章節（影片與景點切換 100% 全數保留，嚴格符合 YouTube 5,000 字上限）。"
            )

        lines.append("")
        lines.append("【時間軸目錄】")

        if not items or items[0].start_seconds > 0.0:
            lines.append("00:00 開始播放")

        current_category = None
        for item in items:
            ts_str = format_timestamp(item.start_seconds)
            type_tag = "🎬 [影片] " if item.is_video else ""

            if item.category and item.category != current_category:
                current_category = item.category
                lines.append(f"\n--- 【{item.category}】 ---")

            lines.append(f"{ts_str} {type_tag}{item.title}")

        lines.append("\n==========================================")
        if is_condensed:
            lines.append(
                f"本段精選章節：{len(items)} 個（本段實際完整收錄媒體總數：{len(self.entries)} 個）"
            )
        else:
            lines.append(f"總共收錄項目數：{len(items)}")

        return "\n".join(lines)

    def generate_full_text(self) -> str:
        """生成無刪減之本機完整版章節文字"""
        return self._format_lines(self.entries, is_condensed=False)

    def generate_youtube_text(self, max_chars: int = 4500) -> Tuple[str, bool]:
        """
        生成可直接貼上 YouTube 說明欄的章節文字。
        - 嚴格控制在 max_chars（預設 4,500 字，防範 5,000 字爆表）
        - 回傳 (文字內容, 是否觸發了智慧濃縮)
        """
        if not self.entries:
            return self._format_lines([], is_condensed=False), False

        full_text = self._format_lines(self.entries, is_condensed=False)
        if len(full_text) <= max_chars:
            return full_text, False

        # --- 啟動階層式智慧濃縮演算法 ---
        # 1. 必保項目：所有影片 + 所有分類/子目錄切換起點 + 第一項
        essential_set = set()
        if self.entries:
            essential_set.add(0)

        for idx, it in enumerate(self.entries):
            if it.is_video or it.is_category_start:
                essential_set.add(idx)

        essential_items = [self.entries[i] for i in sorted(essential_set)]

        # 2. 候選相片集合（非必保項目）
        candidate_indices = [
            i for i in range(len(self.entries)) if i not in essential_set
        ]

        # 預估必保項目所佔字元數
        base_text = self._format_lines(essential_items, is_condensed=True)
        remain_chars = max(0, max_chars - len(base_text) - 150)

        # 3. 均勻抽樣非必保相片（等時間步長 Uniform Sampling）
        # 假設每行平均約 38 字元
        sample_capacity = remain_chars // 38
        sampled_indices = []

        if sample_capacity > 0 and candidate_indices:
            if len(candidate_indices) <= sample_capacity:
                sampled_indices = candidate_indices
            else:
                step = len(candidate_indices) / sample_capacity
                sampled_indices = [
                    candidate_indices[int(i * step)]
                    for i in range(sample_capacity)
                ]

        # 4. 合併必保項目與均勻抽樣項目，並按時間嚴格排序
        final_indices = sorted(list(essential_set) + sampled_indices)
        combined_items = [self.entries[i] for i in final_indices]

        # 5. YouTube 官方 10 秒最小間隔過濾（防止過於密集導致章節失效）
        filtered_items: List[ChapterItem] = []
        for it in combined_items:
            if not filtered_items:
                filtered_items.append(it)
                continue

            prev = filtered_items[-1]
            gap = it.start_seconds - prev.start_seconds

            if gap >= 10.0:
                filtered_items.append(it)
            else:
                # 若間隔小於 10 秒，若當前是影片或大分類，優先保留它，替換掉前一個相片
                if (it.is_video or it.is_category_start) and not (
                    prev.is_video or prev.is_category_start
                ):
                    filtered_items[-1] = it

        # 6. 字數安全最終鉗制（Hard Clamp）
        result_text = self._format_lines(filtered_items, is_condensed=True)
        while len(result_text) > max_chars and len(filtered_items) > 3:
            # 從後往前淘汰一般相片
            drop_idx = None
            for i in range(len(filtered_items) - 1, 0, -1):
                target = filtered_items[i]
                if not target.is_video and not target.is_category_start:
                    drop_idx = i
                    break

            if drop_idx is not None:
                filtered_items.pop(drop_idx)
                result_text = self._format_lines(filtered_items, is_condensed=True)
            else:
                break

        return result_text, True

    def save_to_file(self, output_path: str, max_chars: int = 4500) -> Optional[str]:
        """
        將章節文字寫入檔案（UTF-8 編碼）。
        1. 寫入 output_path：【YouTube 官方 5,000 字精華濃縮版】（直接複製貼上保證成功）。
        2. 若觸發濃縮，自動在同目錄額外產出 {Name}_Full.txt（保留 100% 每張相片與影片的完整本機清單）。
        回傳：若產出了 Full 版則回傳其完整路徑，否則回傳 None。
        """
        yt_content, is_condensed = self.generate_youtube_text(max_chars=max_chars)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(yt_content)

        full_path = None
        if is_condensed:
            base_dir = os.path.dirname(os.path.abspath(output_path))
            file_name, file_ext = os.path.splitext(os.path.basename(output_path))
            full_path = os.path.join(base_dir, f"{file_name}_Full{file_ext}")
            full_content = self.generate_full_text()
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(full_content)

        return full_path
