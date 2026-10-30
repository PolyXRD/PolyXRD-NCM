"""谱图处理工具条（T6.2a）。

工具条与「处理」菜单**共用同一批 QAction**（主窗口 `act_process`），
避免两处动作各写一遍、行为漂移。

**处理语义（重要）**
------------------
每个处理动作都作用在**原始谱**上，产生一份「显示用」的谱：

- 画布显示的是处理后的谱（给人看、给寻峰用）；
- **喂给精修的永远是原始谱** —— Rietveld 把背景当线性参数一起最小化，
  平滑会破坏残差的统计性质，去 Kα2 会丢掉双线信息
  （见 `ncm.core.preprocess.for_refinement`）。

因此工具条不做「链式叠加」，而是「单步替换」：点了「平滑」就只显示平滑谱，
想回到原图点「重置」。链式顺序约束（去Kα2 → 扣背景 → 平滑）由
`ncm.core.preprocess` 保证，判定门内部另有专用链
（`ncm.core.peaks.prepare`）。

参数用 `QInputDialog` 就地询问，不另建对话框类 —— 家族那种多步向导
（`kwizard.py`）是给"批量多参数"场景的，本工具条每步只有一个参数，
用输入框更直接。
"""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QInputDialog, QToolBar

from ncm.core.background import BG_MODES
from ncm.core.dtypes import Pattern
from ncm.core.peaks import ObservedPeak, find_peaks, prepare
from ncm.core.preprocess import smooth, strip_background, strip_ka2
from ncm.i18n import tr

#: 平滑窗口默认值（点）
DEFAULT_SMOOTH_WINDOW = 9
#: Kα2/Kα1 强度比默认值（Cu 靶理论值 ≈ 0.5）
DEFAULT_KA2_RATIO = 0.5
#: 寻峰相对强度阈值默认值
DEFAULT_PEAK_REL_MIN = 0.01


class ProcessToolbar(QToolBar):
    """处理工具条：只负责承载动作，逻辑在 :class:`ProcessController`。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("processToolbar")
        self.setMovable(False)
        self.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)

    def attach(self, actions: dict[str, QAction]) -> None:
        """把主窗口的处理动作挂上来（菜单与工具条同源）。"""
        for key in ("smooth", "background", "kalpha2", "peaks", "fit"):
            act = actions.get(key)
            if act is not None:
                self.addAction(act)
                self.addSeparator()


class ProcessController:
    """处理动作的编排者：作用于当前原始谱，结果写回画布与状态栏。"""

    def __init__(self, window) -> None:
        self.window = window
        self._processed: Pattern | None = None
        self._peaks: list[ObservedPeak] = []

    # ------------------------------------------------------------------ #
    # 状态
    # ------------------------------------------------------------------ #
    @property
    def processed(self) -> Pattern | None:
        """当前显示用的处理后谱（None = 显示原始谱）。"""
        return self._processed

    @property
    def peaks(self) -> list[ObservedPeak]:
        """最近一次寻峰的结果。"""
        return self._peaks

    def require_pattern(self) -> Pattern | None:
        """取原始谱；未导入时弹提示并返回 None。"""
        pat = getattr(self.window, "_pattern", None)
        if pat is None:
            self.window._msg_box(tr("msg.no_pattern"))
        return pat

    # ------------------------------------------------------------------ #
    # 动作
    # ------------------------------------------------------------------ #
    def apply_smooth(self) -> None:
        """SG 平滑（窗口点数，奇数）。"""
        pat = self.require_pattern()
        if pat is None:
            return
        n, ok = QInputDialog.getInt(
            self.window, tr("dlg.smooth.title"), tr("dlg.smooth.window"),
            DEFAULT_SMOOTH_WINDOW, 5, 101, 2)
        if not ok:
            return
        self._show(smooth(pat, window=n), "smooth", f"window={n}")

    def apply_background(self) -> None:
        """扣背景（模式可选 linear_edges / poly / chebyshev）。"""
        pat = self.require_pattern()
        if pat is None:
            return
        mode, ok = QInputDialog.getItem(
            self.window, tr("dlg.bg.title"), tr("dlg.bg.mode"),
            list(BG_MODES), 0, False)
        if not ok:
            return
        net, bg = strip_background(pat, mode=mode)
        self._show(net, "background", f"mode={mode}", background=bg)

    def apply_kalpha2(self) -> None:
        """Rachinger 去 Kα2。"""
        pat = self.require_pattern()
        if pat is None:
            return
        ratio, ok = QInputDialog.getDouble(
            self.window, tr("dlg.ka2.title"), tr("dlg.ka2.ratio"),
            DEFAULT_KA2_RATIO, 0.05, 1.0, 2)
        if not ok:
            return
        self._show(strip_ka2(pat, ratio=ratio), "kalpha2", f"ratio={ratio:g}")

    def find_peaks(self) -> None:
        """寻峰：在「去Kα2 → 扣背景 → 平滑」的净谱上找局部极大。"""
        pat = self.require_pattern()
        if pat is None:
            return
        rel, ok = QInputDialog.getDouble(
            self.window, tr("dlg.peaks.title"), tr("dlg.peaks.rel_min"),
            DEFAULT_PEAK_REL_MIN, 0.0001, 0.5, 4)
        if not ok:
            return
        net = prepare(pat)
        self._peaks = find_peaks(net, rel_min=rel)
        self._show(net, "peaks", f"{len(self._peaks)} peaks")
        self.sync_peak_markers()

    def reset(self) -> None:
        """重置：回到原始谱，清掉寻峰标记。"""
        self._processed = None
        self._peaks = []
        pat = getattr(self.window, "_pattern", None)
        if pat is not None:
            self.window.canvas.show_pattern(np.asarray(pat.two_theta),
                                            np.asarray(pat.intensity))
        self.sync_peak_markers()
        self.window.statusBar().showMessage(tr("status.reset"))

    # ------------------------------------------------------------------ #
    # 画布同步
    # ------------------------------------------------------------------ #
    def sync_peak_markers(self) -> None:
        """把寻峰结果标到画布上，并刷新峰列表停靠窗。

        （T7.1d 从 `MainWindow._sync_peak_markers` 下沉到此处 —— 主窗口
        已接近 400 行上限，而这段逻辑本就属于「处理」职责。）
        """
        peaks = self._peaks
        if not peaks:
            pat = getattr(self.window, "_pattern", None)
            if pat is not None:
                self.window.canvas.show_pattern(np.asarray(pat.two_theta),
                                                np.asarray(pat.intensity))
            self.window.peak_panel.set_peaks([])
            self.window.dock_peaks.setVisible(False)
            return
        pat = self._processed or getattr(self.window, "_pattern", None)
        self.window.canvas.show_pattern(
            np.asarray(pat.two_theta), np.asarray(pat.intensity),
            peaks=[(p.two_theta, p.intensity) for p in peaks])
        self.window.peak_panel.set_peaks(peaks)
        self.window.dock_peaks.setVisible(True)

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #
    def _show(self, pat: Pattern, op_key: str, detail: str,
              background=None) -> None:
        """把处理后的谱画到画布并更新状态栏。"""
        self._processed = pat
        self.window.canvas.show_pattern(
            np.asarray(pat.two_theta), np.asarray(pat.intensity))
        self.window.statusBar().showMessage(
            tr("status.processed", op=tr(f"menu.process.{op_key}"), detail=detail))
