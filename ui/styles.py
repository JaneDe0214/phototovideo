"""
現代化 Fluent / Dark 主題樣式表
"""

DARK_THEME = """
QMainWindow, QDialog {
    background-color: #1e1e24;
    color: #f0f0f2;
    font-family: "Segoe UI", "Microsoft JhengHei", sans-serif;
    font-size: 13px;
}

QGroupBox {
    border: 1px solid #3d3d4a;
    border-radius: 8px;
    margin-top: 14px;
    padding-top: 14px;
    font-weight: bold;
    color: #00d2ff;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 8px;
}

QLabel {
    color: #dcdce0;
}

QPushButton {
    background-color: #2b2b36;
    border: 1px solid #4a4a5a;
    border-radius: 6px;
    color: #ffffff;
    padding: 8px 16px;
    font-weight: 500;
}

QPushButton:hover {
    background-color: #383848;
    border-color: #00d2ff;
}

QPushButton:pressed {
    background-color: #1a1a22;
}

QPushButton#btn_primary {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0078d4, stop:1 #00b4d8);
    border: none;
    font-size: 14px;
    font-weight: bold;
    padding: 10px 20px;
    border-radius: 6px;
}

QPushButton#btn_primary:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1084e3, stop:1 #20c4e8);
}

QPushButton#btn_primary:disabled {
    background-color: #3a3a44;
    color: #7a7a84;
}

QTreeWidget {
    background-color: #141418;
    border: 1px solid #33333f;
    border-radius: 6px;
    color: #f0f0f2;
    alternate-background-color: #1a1a20;
    padding: 4px;
}

QTreeWidget::item {
    padding: 6px;
    border-radius: 4px;
}

QTreeWidget::item:hover {
    background-color: #262632;
}

QTreeWidget::item:selected {
    background-color: #0078d4;
    color: #ffffff;
}

QHeaderView::section {
    background-color: #22222c;
    color: #a0a0ab;
    padding: 6px;
    border: none;
    border-bottom: 1px solid #33333f;
    font-weight: bold;
}

QComboBox {
    background-color: #2b2b36;
    border: 1px solid #4a4a5a;
    border-radius: 6px;
    color: #ffffff;
    padding: 6px 12px;
}

QComboBox:hover {
    border-color: #00d2ff;
}

QComboBox QAbstractItemView {
    background-color: #22222c;
    border: 1px solid #4a4a5a;
    selection-background-color: #0078d4;
    color: #ffffff;
}

QSpinBox, QDoubleSpinBox, QLineEdit {
    background-color: #141418;
    border: 1px solid #4a4a5a;
    border-radius: 6px;
    color: #ffffff;
    padding: 6px;
}

QSpinBox:hover, QDoubleSpinBox:hover, QLineEdit:hover {
    border-color: #00d2ff;
}

QProgressBar {
    background-color: #141418;
    border: 1px solid #33333f;
    border-radius: 6px;
    text-align: center;
    color: #ffffff;
    font-weight: bold;
    height: 22px;
}

QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0078d4, stop:1 #00f2fe);
    border-radius: 5px;
}

QTextEdit {
    background-color: #141418;
    border: 1px solid #33333f;
    border-radius: 6px;
    color: #a0f0a0;
    font-family: "Consolas", "Courier New", monospace;
    font-size: 12px;
    padding: 8px;
}

QScrollBar:vertical {
    border: none;
    background: #1e1e24;
    width: 8px;
    border-radius: 4px;
}

QScrollBar::handle:vertical {
    background: #4a4a5a;
    border-radius: 4px;
}

QScrollBar::handle:vertical:hover {
    background: #6a6a7a;
}
"""
