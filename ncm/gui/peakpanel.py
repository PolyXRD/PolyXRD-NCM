"""寻峰结果面板（T6.2b）。

列出当前谱的实测峰：2θ、强度、相对强度。

**为什么没有 hkl 列（如实记录，避免后人重踩）**
----------------------------------------------
六方 R 晶系（NCM 的 R-3m）的指标约定有坑：

- 3-index 下的 R 中心化消光条件是 `2h+k+l ≡ 0 (mod 3)`。按此，(105)、(108)、
  (201) **都是禁戒的** —— 但它们恰恰是 NCM 文献里最常用的标注
  （48.7° = (105)、64.6° = (108)、77.1° = (201)）。
- 真正贡献这些峰的，是同一「密排族」里满足消光条件的成员
  （48.7° 对应 (015) / (1-15) 这类）。
- 换成国际标准的四指数 (hkil) 写法，禁戒条件又换一套，(104)/(012)/(101)
  反而变成禁戒的 —— 说明"哪个成员该被写出来"取决于所选记法与轴系约定，
  不是一条简单规则。
- vendor 的 `compute_peaks` 按 2θ 合并多重性，**不暴露逐 hkl 的结构因子**，
  无法从程序内部判定某个成员究竟是否消光。

结论：只有 2θ 是权威量。在没有把「六方 4-index 约化 + 消光条件 + 文献交叉
核对」做严谨之前，本面板**只给 2θ / 强度 / 相对强度**，不给可能贴错的指标。
（`ncm.core.peaks.reflections()` 里的 hkl 集合本身是正确的**密排族**成员，
只是尚未约化到可直接展示的记法；判定门只用它的 2θ，不受影响。）
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDockWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ncm.core.peaks import ObservedPeak
from ncm.i18n import tr


class PeakPanel(QWidget):
    """峰列表面板。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.table = QTableWidget(0, 3, self)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.verticalHeader().setVisible(False)
        root.addWidget(self.table)
        self.retranslate()

    # ------------------------------------------------------------------ #
    # 数据
    # ------------------------------------------------------------------ #
    def set_peaks(self, peaks: list[ObservedPeak]) -> None:
        """填入峰列表（按 2θ 升序）。"""
        self.table.setRowCount(0)
        if not peaks:
            self.retranslate()
            return
        order = sorted(peaks, key=lambda p: p.two_theta)
        imax = max((p.intensity for p in order), default=0.0) or 1.0
        for row, p in enumerate(order):
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(f"{p.two_theta:.4f}"))
            self.table.setItem(row, 1, QTableWidgetItem(f"{p.intensity:.1f}"))
            self.table.setItem(row, 2, QTableWidgetItem(f"{p.intensity / imax:.4f}"))
        self.retranslate()

    def to_csv(self) -> str:
        """导出当前表为 CSV 文本（含表头）。"""
        lines = [",".join(self._headers())]
        for row in range(self.table.rowCount()):
            lines.append(",".join(
                (self.table.item(row, c).text() if self.table.item(row, c)
                 else "") for c in range(self.table.columnCount())))
        return "\n".join(lines) + "\n"

    # ------------------------------------------------------------------ #
    # 多语言
    # ------------------------------------------------------------------ #
    def _headers(self) -> list[str]:
        return [tr("peak.col.two_theta"), tr("peak.col.intensity"),
                tr("peak.col.rel")]

    def retranslate(self) -> None:
        """语言切换后刷新表头。"""
        self.table.setHorizontalHeaderLabels(self._headers())


def build_peak_dock(window) -> tuple["PeakPanel", QDockWidget]:
    """在主窗口底部建一个可折叠的寻峰停靠窗（T6.4e 抽取）。

    返回 ``(panel, dock)``；停靠窗默认收起 —— 寻峰结果表条目多，
    展开会挤掉主视野。
    """
    panel = PeakPanel(window)
    dock = QDockWidget(window)
    dock.setObjectName("dockPeaks")
    dock.setWidget(panel)
    window.addDockWidget(Qt.BottomDockWidgetArea, dock)
    dock.setVisible(False)
    return panel, dock
