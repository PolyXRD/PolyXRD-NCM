"""状态栏组件（T6.4e 抽取）。

从 `MainWindow` 抽出来的状态栏：语言 · 当前文件 · 判定状态 · 取消按钮。

抽出来的理由与 `menubar.py` 一样 —— 主窗口在 T6.3/T6.4 之后超了「单文件
≤ 400 行」的硬约束，而状态栏是**纯展示**单元，不含业务判断。

对外只暴露四个控件引用 + 一个 `retranslate()`，主窗口照旧把它们挂在
自身上（``win.lbl_file`` / ``win.btn_cancel`` …），既有测试契约不变。
"""
from __future__ import annotations

from PySide6.QtWidgets import QLabel, QPushButton

from ncm.i18n import current_language, tr


class StatusBar:
    """主窗口状态栏（语言 · 文件 · 判定状态 · 取消）。"""

    def __init__(self, window, *, on_cancel) -> None:
        """window : QMainWindow；on_cancel : 取消按钮的槽。"""
        self.window = window
        self.lbl_lang = QLabel(window)
        self.lbl_file = QLabel(window)
        self.lbl_identify = QLabel(window)
        for w in (self.lbl_lang, self.lbl_file, self.lbl_identify):
            window.statusBar().addWidget(w)
        self.btn_cancel = QPushButton(window)
        self.btn_cancel.clicked.connect(on_cancel)
        self.btn_cancel.setVisible(False)
        window.statusBar().addPermanentWidget(self.lbl_identify)
        window.statusBar().addPermanentWidget(self.btn_cancel)

    def retranslate(self) -> None:
        """语言切换后刷新文案。"""
        self.lbl_lang.setText(
            tr("status.lang", lang=tr(f"lang.{current_language()}")))
        self.lbl_file.setText(tr("status.ready"))
        self.lbl_identify.setText(tr("status.identify.pending"))
        self.btn_cancel.setText(tr("btn.cancel"))
