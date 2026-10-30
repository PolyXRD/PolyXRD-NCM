"""物相判定结果对话框（T6.3c）。

判定门**不通过**时弹出，把结论、逐条理由与量化明细摆给用户看 —— 这正是
需求里"不是的话停止后续操作，弹出对话框提示"的落点。

**关键分支**：判定门不通过但 `kind == "ncm"`（如 LiCoO₂ —— 结构类型是层状
R-3m，只是晶胞不属于 NCM 族）时，对话框额外给一个「仍按 NCM 精修」的出口：
是否继续由用户决定，程序不替用户拍板。反过来 `kind` 属于前驱体
（precursor_hydroxide / precursor_carbonate）时**不提供**该出口 —— 那不是
NCM，正极流程本来就不该往下走。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QTextBrowser,
    QVBoxLayout,
)

from ncm.core.identify import IdentifyResult
from ncm.i18n import tr

#: 可提供「仍按 NCM 精修」出口的 kind
CONTINUABLE_KINDS = ("ncm",)


class IdentifyDialog(QDialog):
    """判定结果对话框。"""

    def __init__(self, result: IdentifyResult, parent=None) -> None:
        super().__init__(parent)
        self.result = result
        self.continue_anyway = False
        self.setWindowTitle(self._title())
        self.setMinimumWidth(460)
        root = QVBoxLayout(self)
        head = QLabel(self)
        head.setWordWrap(True)
        head.setStyleSheet("font-size:13px; font-weight:600;")
        head.setText(self._headline())
        root.addWidget(head)
        self.browser = QTextBrowser(self)
        self.browser.setOpenExternalLinks(False)
        root.addWidget(self.browser)
        box = QDialogButtonBox(self)
        self.btn_ok = box.addButton(tr("dlg.close"), QDialogButtonBox.AcceptRole)
        self.btn_continue = None
        if self._can_continue():
            self.btn_continue = box.addButton(
                tr("dlg.identify.continue_ncm"), QDialogButtonBox.AcceptRole)
        box.rejected.connect(self.reject)
        self.btn_ok.clicked.connect(self.accept)
        if self.btn_continue is not None:
            self.btn_continue.clicked.connect(self._accept_continue)
        root.addWidget(box)
        self.retranslate()

    # ------------------------------------------------------------------ #
    # 判定
    # ------------------------------------------------------------------ #
    def _can_continue(self) -> bool:
        """是否提供「仍按 NCM 精修」的出口。"""
        return (not self.result.ok) and self.result.kind in CONTINUABLE_KINDS

    def _title(self) -> str:
        return tr("dlg.identify.title")

    def _headline(self) -> str:
        if self.result.ok:
            return tr("dlg.identify.pass")
        return tr("dlg.identify.fail", kind=self.result.kind)

    # ------------------------------------------------------------------ #
    # 正文
    # ------------------------------------------------------------------ #
    def _body(self) -> str:
        lines = []
        for r in self.result.reasons:
            lines.append(f"· {r}")
        metrics = self.result.metrics or {}
        if metrics:
            lines.append("")
            lines.append(tr("dlg.identify.metrics"))
            for k, v in metrics.items():
                lines.append(f"  {k}: {v}")
        return "\n".join(lines)

    def retranslate(self) -> None:
        """语言切换后刷新正文。"""
        self.setWindowTitle(self._title())
        self.browser.setPlainText(self._body())

    def toPlainText(self) -> str:
        """供冒烟测试断言关键内容。"""
        return self.browser.toPlainText()

    # ------------------------------------------------------------------ #
    # 槽
    # ------------------------------------------------------------------ #
    def _accept_continue(self) -> None:
        """用户选择「仍按 NCM 精修」。"""
        self.continue_anyway = True
        self.accept()
