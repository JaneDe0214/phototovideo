try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except Exception:
    pass

"""
媒體檔案掃描與 EXIF 時間排序模組
支援目錄樹狀結構解析、以任意起點彙整媒體、時間嚴格排序
"""

import os
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from PIL import Image
from PIL.ExifTags import TAGS


# 支援的相片副檔名
SUPPORTED_IMAGE_EXTS = {
    ".jpg", ".jpeg", ".png", ".heic", ".webp", ".bmp", ".tif", ".tiff"
}

# 支援的影片副檔名
SUPPORTED_VIDEO_EXTS = {
    ".mp4", ".mov", ".m4v", ".mkv", ".avi", ".wmv", ".webm"
}


class MediaItem:
    """單一相片或影片媒體物件"""

    def __init__(self, file_path: str):
        self.file_path = os.path.normpath(file_path)
        self.file_name = os.path.basename(self.file_path)
        self.extension = os.path.splitext(self.file_name)[1].lower()
        self.is_video = self.extension in SUPPORTED_VIDEO_EXTS
        self.is_image = self.extension in SUPPORTED_IMAGE_EXTS
        self.file_size = 0
        self.capture_time: Optional[datetime] = None
        self.duration: float = 0.0  # 影片秒數，相片則由設定決定
        self.width: int = 0
        self.height: int = 0

        self._parse_metadata()

    def _parse_metadata(self):
        try:
            stat = os.stat(self.file_path)
            self.file_size = stat.st_size
            default_time = datetime.fromtimestamp(stat.st_mtime)
        except Exception:
            default_time = datetime.now()

        if self.is_image:
            self._parse_image_exif(default_time)
        elif self.is_video:
            # 影片時間預設先取修改時間，若有需要可由 ffprobe 深度解析
            self.capture_time = default_time
            # 預估影片長度暫定 10 秒，會在深度分析時由 ffprobe 精準更新
            self.duration = 10.0
        else:
            self.capture_time = default_time

    def _parse_image_exif(self, default_time: datetime):
        self.capture_time = default_time
        try:
            with Image.open(self.file_path) as img:
                self.width, self.height = img.size
                exif = img.getexif()
                if exif:
                    # 搜尋 DateTimeOriginal (36867) 或 DateTime (306)
                    for tag_id, value in exif.items():
                        tag_name = TAGS.get(tag_id, tag_id)
                        if tag_name in ("DateTimeOriginal", "DateTimeDigitized", "DateTime"):
                            if isinstance(value, str):
                                try:
                                    # 格式通常為 "YYYY:MM:DD HH:MM:SS"
                                    self.capture_time = datetime.strptime(
                                        value.strip(), "%Y:%m:%d %H:%M:%S"
                                    )
                                    return
                                except ValueError:
                                    pass
        except Exception:
            self.capture_time = default_time


class DirectoryTreeNode:
    """目錄樹狀結構節點"""

    def __init__(self, dir_path: str, relative_path: str = ""):
        self.dir_path = os.path.normpath(dir_path)
        self.name = os.path.basename(self.dir_path)
        self.relative_path = relative_path
        self.children: List["DirectoryTreeNode"] = []
        self.media_items: List[MediaItem] = []

    def add_child(self, child: "DirectoryTreeNode"):
        self.children.append(child)

    def total_images_count(self) -> int:
        """統計該節點及其所有子節點的照片總數"""
        count = sum(1 for m in self.media_items if m.is_image)
        for child in self.children:
            count += child.total_images_count()
        return count

    def total_videos_count(self) -> int:
        """統計該節點及其所有子節點的影片總數"""
        count = sum(1 for m in self.media_items if m.is_video)
        for child in self.children:
            count += child.total_videos_count()
        return count

    def total_size_bytes(self) -> int:
        """統計該節點及其所有子節點的總容量"""
        size = sum(m.file_size for m in self.media_items)
        for child in self.children:
            size += child.total_size_bytes()
        return size

    def collect_all_media(self) -> List[MediaItem]:
        """遞迴收集該節點及其所有子節點的媒體項目"""
        items = list(self.media_items)
        for child in self.children:
            items.extend(child.collect_all_media())
        return items


class AlbumScanner:
    """相簿掃描器"""

    @staticmethod
    def scan_directory_tree(root_dir: str) -> Optional[DirectoryTreeNode]:
        root_dir = os.path.normpath(root_dir)
        if not os.path.exists(root_dir) or not os.path.isdir(root_dir):
            return None

        def _build_node(current_path: str, rel_path: str) -> DirectoryTreeNode:
            node = DirectoryTreeNode(current_path, rel_path)
            try:
                entries = sorted(os.scandir(current_path), key=lambda e: e.name.lower())
            except Exception:
                return node

            sub_dirs = []
            files = []
            for entry in entries:
                if entry.is_dir(follow_symlinks=False):
                    sub_dirs.append(entry)
                elif entry.is_file(follow_symlinks=False):
                    files.append(entry)

            # 收集此目錄的媒體
            for f in files:
                ext = os.path.splitext(f.name)[1].lower()
                if ext in SUPPORTED_IMAGE_EXTS or ext in SUPPORTED_VIDEO_EXTS:
                    node.media_items.append(MediaItem(f.path))

            # 遞迴建立子目錄節點
            for d in sub_dirs:
                child_rel = os.path.join(rel_path, d.name) if rel_path else d.name
                child_node = _build_node(d.path, child_rel)
                node.add_child(child_node)

            return node

        return _build_node(root_dir, "")

    @staticmethod
    def get_sorted_media_from_node(
        node: DirectoryTreeNode,
    ) -> List[Tuple[MediaItem, str]]:
        """
        以選定節點為起點，取得旗下所有媒體檔案，並依照拍攝時間嚴格排序。
        傳回 List[(MediaItem, 所屬子目錄相對路徑)]
        """
        results: List[Tuple[MediaItem, str]] = []

        def _traverse(n: DirectoryTreeNode):
            for item in n.media_items:
                results.append((item, n.relative_path or n.name))
            for c in n.children:
                _traverse(c)

        _traverse(node)

        # 依照拍攝時間排序（若時間相同則依檔名排序）
        results.sort(
            key=lambda x: (
                x[0].capture_time or datetime.min,
                x[0].file_name.lower(),
            )
        )
        return results
