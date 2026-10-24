"""
批次佇列管理核心模組 (Batch Queue Manager)
負責多個相簿資料夾的批次排程轉檔、工作清單管理、
狀態持久化儲存 (重啟自動還原)、優先順序調整、暫停/繼續以及自動關機控制。
"""

import json
import os
import time
import uuid
from typing import Callable, Dict, List, Optional


class BatchTask:
    """單一批次轉檔任務模型"""

    def __init__(
        self,
        name: str,
        source_dir: str,
        output_dir: str,
        profile_id: str,
        profile_name: str,
        config_dict: dict,
        task_id: Optional[str] = None,
        enabled: bool = True,
        status: str = "waiting",
        progress_percent: int = 0,
        status_message: str = "等待中",
        total_items: int = 0,
        output_video_path: str = "",
        output_chapter_path: str = "",
        created_at: Optional[float] = None,
    ):
        self.task_id = task_id or str(uuid.uuid4())[:8]
        self.name = name
        self.source_dir = os.path.normpath(source_dir)
        self.output_dir = os.path.normpath(output_dir)
        self.profile_id = profile_id
        self.profile_name = profile_name
        self.config_dict = config_dict
        self.enabled = enabled
        self.status = status  # waiting, running, paused, completed, cancelled, failed
        self.progress_percent = progress_percent
        self.status_message = status_message
        self.total_items = total_items
        self.output_video_path = output_video_path
        self.output_chapter_path = output_chapter_path
        self.created_at = created_at or time.time()

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "name": self.name,
            "source_dir": self.source_dir,
            "output_dir": self.output_dir,
            "profile_id": self.profile_id,
            "profile_name": self.profile_name,
            "config_dict": self.config_dict,
            "enabled": self.enabled,
            "status": self.status,
            "progress_percent": self.progress_percent,
            "status_message": self.status_message,
            "total_items": self.total_items,
            "output_video_path": self.output_video_path,
            "output_chapter_path": self.output_chapter_path,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BatchTask":
        return cls(
            name=data.get("name", "未命名任務"),
            source_dir=data.get("source_dir", ""),
            output_dir=data.get("output_dir", ""),
            profile_id=data.get("profile_id", ""),
            profile_name=data.get("profile_name", ""),
            config_dict=data.get("config_dict", {}),
            task_id=data.get("task_id"),
            enabled=data.get("enabled", True),
            status=data.get("status", "waiting"),
            progress_percent=data.get("progress_percent", 0),
            status_message=data.get("status_message", "等待中"),
            total_items=data.get("total_items", 0),
            output_video_path=data.get("output_video_path", ""),
            output_chapter_path=data.get("output_chapter_path", ""),
            created_at=data.get("created_at"),
        )


class QueueManager:
    """佇列排程管理器"""

    def __init__(self, storage_path: Optional[str] = None):
        if storage_path:
            self.storage_path = storage_path
        else:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            self.storage_path = os.path.join(base_dir, "queue_tasks.json")

        self.tasks: List[BatchTask] = []
        self.current_task_id: Optional[str] = None
        self.is_queue_running: bool = False
        self.auto_shutdown: bool = False
        self.load_from_storage()

    def add_task(self, task: BatchTask) -> bool:
        """加入新任務至佇列末尾"""
        self.tasks.append(task)
        self.save_to_storage()
        return True

    def remove_task(self, task_id: str) -> bool:
        """自佇列中移除指定任務"""
        for i, t in enumerate(self.tasks):
            if t.task_id == task_id:
                if t.status == "running":
                    return False  # 正在運行的任務需先暫停/停止
                self.tasks.pop(i)
                self.save_to_storage()
                return True
        return False

    def move_up(self, task_id: str) -> bool:
        """將任務往上移動（提高優先權）"""
        idx = next((i for i, t in enumerate(self.tasks) if t.task_id == task_id), -1)
        if idx > 0:
            self.tasks[idx - 1], self.tasks[idx] = self.tasks[idx], self.tasks[idx - 1]
            self.save_to_storage()
            return True
        return False

    def move_down(self, task_id: str) -> bool:
        """將任務往下移動（降低優先權）"""
        idx = next((i for i, t in enumerate(self.tasks) if t.task_id == task_id), -1)
        if idx >= 0 and idx < len(self.tasks) - 1:
            self.tasks[idx + 1], self.tasks[idx] = self.tasks[idx], self.tasks[idx + 1]
            self.save_to_storage()
            return True
        return False

    def toggle_enabled(self, task_id: str, enabled: bool):
        """切換任務是否啟用"""
        task = self.get_task(task_id)
        if task:
            task.enabled = enabled
            self.save_to_storage()

    def get_task(self, task_id: str) -> Optional[BatchTask]:
        return next((t for t in self.tasks if t.task_id == task_id), None)

    def get_next_runnable_task(self) -> Optional[BatchTask]:
        """尋找下一個已啟用且待執行的任務"""
        for t in self.tasks:
            if t.enabled and t.status in ["waiting", "paused"]:
                return t
        return None

    def mark_task_status(
        self,
        task_id: str,
        status: str,
        message: str = "",
        progress: Optional[int] = None,
    ):
        task = self.get_task(task_id)
        if task:
            task.status = status
            if message:
                task.status_message = message
            if progress is not None:
                task.progress_percent = progress
            self.save_to_storage()

    def clear_completed(self) -> int:
        """清除所有已完成的任務"""
        before_count = len(self.tasks)
        self.tasks = [t for t in self.tasks if t.status != "completed"]
        removed = before_count - len(self.tasks)
        if removed > 0:
            self.save_to_storage()
        return removed

    def reset_stopped_tasks(self):
        """將因軟體關閉而處於 running 的任務恢復為 paused 或 waiting，便於重啟後斷點接續"""
        changed = False
        for t in self.tasks:
            if t.status == "running":
                t.status = "paused"
                t.status_message = "已暫停（可隨時斷點接續）"
                changed = True
        if changed:
            self.save_to_storage()

    def save_to_storage(self):
        """儲存佇列至 JSON 檔案"""
        try:
            data = {
                "auto_shutdown": self.auto_shutdown,
                "tasks": [t.to_dict() for t in self.tasks],
            }
            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def load_from_storage(self):
        """自 JSON 檔案載入佇列"""
        if not os.path.exists(self.storage_path):
            return
        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.auto_shutdown = data.get("auto_shutdown", False)
            self.tasks = [BatchTask.from_dict(d) for d in data.get("tasks", [])]
            self.reset_stopped_tasks()
        except Exception:
            self.tasks = []
