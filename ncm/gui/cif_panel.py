"""右侧 CIF 面板（T6.2b 抽取 · T6.3 接线）。

从 `MainWindow` 里抽出来的独立面板：内置 CIF 列表 + 导入/判定/精修按钮。
抽出来有两个理由：

1. `MainWindow` 已接近 400 行的单文件上限；
2. 面板要用**信号**把「用户想干什么」告诉主窗口，而主窗口不该反过来
   在面板里找按钮 —— 信号的职责边界更干净。

内置 CIF 列表读 `ncm/data/cif/INDEX.json`（14 份：NCM 族 8 + 前驱体 4 +
对照 2），排序固定，便于复现。
"""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ncm.i18n import tr

#: 内置 CIF 索引（相对包根）
CIF_INDEX = Path(__file__).resolve().parents[1] / "data" / "cif" / "INDEX.json"


class CifPanel(QWidget):
    """CIF 结构面板。"""

    import_requested = Signal()
    identify_requested = Signal()
    refine_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        self.grp_cif = QGroupBox(self)
        inner = QVBoxLayout(self.grp_cif)
        self.cif_list = QListWidget(self.grp_cif)
        self.cif_list.setToolTip(self._tooltip())
        inner.addWidget(self.cif_list)
        self._fill()
        row = QHBoxLayout()
        self.btn_import_cif = QPushButton(self.grp_cif)
        self.btn_import_cif.clicked.connect(self.import_requested.emit)
        self.btn_identify = QPushButton(self.grp_cif)
        self.btn_identify.setEnabled(False)      # T6.3 接线
        self.btn_identify.clicked.connect(self.identify_requested.emit)
        self.btn_refine = QPushButton(self.grp_cif)
        self.btn_refine.setEnabled(False)        # T6.3 接线
        self.btn_refine.clicked.connect(self.refine_requested.emit)
        for w in (self.btn_import_cif, self.btn_identify, self.btn_refine):
            row.addWidget(w)
        inner.addLayout(row)
        root.addWidget(self.grp_cif)
        self.retranslate()

    # ------------------------------------------------------------------ #
    # 数据
    # ------------------------------------------------------------------ #
    def _fill(self) -> None:
        """按 INDEX.json 填内置 CIF 列表。"""
        try:
            data = json.loads(CIF_INDEX.read_text(encoding="utf-8"))
            entries = data.get("entries", [])
        except (OSError, ValueError):
            entries = []
        for e in entries:
            self.cif_list.addItem(str(e.get("name", "")))

    def current_name(self) -> str | None:
        """当前选中的 CIF 名（未选中返回 None）。"""
        item = self.cif_list.currentItem()
        return item.text() if item is not None else None

    def select(self, name: str) -> bool:
        """按名字选中（找不到返回 False）。"""
        for i in range(self.cif_list.count()):
            if self.cif_list.item(i).text() == name:
                self.cif_list.setCurrentRow(i)
                return True
        return False

    def set_buttons_enabled(self, *, identify: bool, refine: bool) -> None:
        """按流程状态启用/禁用判定与精修按钮。"""
        self.btn_identify.setEnabled(identify)
        self.btn_refine.setEnabled(refine)

    # ------------------------------------------------------------------ #
    # 多语言
    # ------------------------------------------------------------------ #
    def retranslate(self) -> None:
        """语言切换后刷新文案。"""
        self.grp_cif.setTitle(tr("panel.cif"))
        self.btn_import_cif.setText(tr("panel.cif.import"))
        self.btn_identify.setText(tr("panel.identify"))
        self.btn_refine.setText(tr("panel.refine"))

    @staticmethod
    def _tooltip() -> str:
        """列表的说明气泡。"""
        return ("内置 CIF 取自 Crystallography Open Database（COD 原始条目）；"
                "派生条目（NCM522/523/622 等）由 COD 1520789 骨架改占位生成。")
