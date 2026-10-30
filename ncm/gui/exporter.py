"""导出控制器（T7.1d · 新建，非 vendor）。

把**当前精修结果**导出成文件：PNG / SVG / CSV / TXT / HTML。

**为什么是控制器而不是主窗口的方法**
------------------------------------
导出要处理三件事：选路径、跑核心层导出、把结果反馈给用户（成功提示 /
失败弹窗）。这些是「界面胶水」，但主窗口已经接近行数上限（规则 2），
且导出逻辑要能脱离主窗口单测 —— 故独立成类，主窗口只留一行委托。

**依赖方向**
------------
导出只调 `ncm.core.export`（核心层，规则 1 不依赖 GUI），不反向依赖
主窗口控件；主窗口通过 `install()` 拿到自己那一批导出动作。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QFileDialog

from ncm.i18n import tr

#: 各导出格式的默认扩展名（决定文件对话框的过滤器）
DEFAULT_SUFFIX = {
    "png": ".png",
    "svg": ".svg",
    "csv": ".csv",
    "txt": ".txt",
    "html": ".html",
}

#: 各类导出的默认文件名（不含扩展名）
_STEM = {
    "png": "refinement", "svg": "refinement", "csv": "points",
    "txt": "card", "html": "report",
}


class Exporter:
    """导出控制器（挂在主窗口上，主窗口只发信号）。"""

    def __init__(self, window, *, result_provider, card_provider) -> None:
        """window : QMainWindow（用于对话框的 parent）

        result_provider : callable() -> 管线结果 | None
        card_provider  : callable() -> 结果卡 dict | None
        """
        self.window = window
        self._result_provider = result_provider
        self._card_provider = card_provider

    # ------------------------------------------------------------------ #
    # 入口
    # ------------------------------------------------------------------ #
    def export_png(self) -> None:
        self._export_figure("png")

    def export_svg(self) -> None:
        self._export_figure("svg")

    def export_csv(self) -> None:
        """导出逐点数据（2θ / 实测 / 计算 / 差值 / 背景）。"""
        from ncm.core.export import export_points_csv

        res = self._result_provider()
        if res is None:
            self._warn_no_result()
            return
        path = self._ask_save("csv")
        if not path:
            return
        sr = res.stage1
        export_points_csv(sr.pattern.two_theta, sr.pattern.intensity,
                          sr.result.ycalc, path,
                          background=self._background(res))
        self._done(path)

    def export_txt(self) -> None:
        """导出结果卡纯文本（口径与邮件摘要一致）。"""
        from ncm.core.export import export_card_text

        card = self._card_provider()
        if card is None:
            self._warn_no_result()
            return
        path = self._ask_save("txt")
        if not path:
            return
        export_card_text(card, path)
        self._done(path)

    def export_html(self) -> None:
        """导出 HTML 报告（自包含：内嵌 SVG 图）。"""
        from ncm.core.export import export_html_report, figure_svg_text

        card = self._card_provider()
        res = self._result_provider()
        if card is None or res is None:
            self._warn_no_result()
            return
        path = self._ask_save("html")
        if not path:
            return
        sr = res.stage1
        svg = figure_svg_text(sr.pattern.two_theta, sr.pattern.intensity,
                              sr.result.ycalc, background=self._background(res),
                              title=sr.structure.name)
        export_html_report(card, path, figure_svg=svg)
        self._done(path)

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #
    def _export_figure(self, kind: str) -> None:
        """导出 PNG / SVG（同一个绘图入口，只差扩展名）。"""
        from ncm.core.export import export_figure

        res = self._result_provider()
        if res is None:
            self._warn_no_result()
            return
        path = self._ask_save(kind)
        if not path:
            return
        sr = res.stage1
        export_figure(sr.pattern.two_theta, sr.pattern.intensity,
                      sr.result.ycalc, path,
                      background=self._background(res),
                      title=sr.structure.name, rwp=res.rwp)
        self._done(path)

    def _background(self, res):
        """取背景曲线（没有则 None）。"""
        from ncm.core.solve import background_curve

        try:
            return background_curve(res.stage1)
        except Exception:  # noqa: BLE001 —— 背景取不到不该中断导出
            return None

    def _ask_save(self, kind: str) -> str:
        """弹保存对话框；用户取消返回空串。"""
        suffix = DEFAULT_SUFFIX[kind]
        path, _ = QFileDialog.getSaveFileName(
            self.window, tr("menu.file.export_" + kind), _stem(kind) + suffix,
            tr("filter.export"))
        if path and not path.lower().endswith(suffix):
            path += suffix
        return path

    def _warn_no_result(self) -> None:
        """没有精修结果时给出提示。"""
        from ncm.gui import dialogs

        dialogs.show_message(self.window, tr("msg.no_result_to_export"))

    def _done(self, path) -> None:
        """导出成功提示。"""
        self.window.statusBar().showMessage(
            tr("status.exported", path=str(path)))


def _stem(kind: str) -> str:
    """默认文件名（可被用户在对话框里改）。"""
    return _STEM.get(kind, "export")
