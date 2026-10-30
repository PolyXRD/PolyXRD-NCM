"""判定 → 精修 → 结果卡 的流程控制器（T6.4e 抽取）。

从 `MainWindow` 里抽出来的独立控制器：**主窗口只管界面，流程状态机放在
这里**。

为什么抽
--------
1. `main_window.py` 在 T6.3/T6.4 之后涨到 520 行，超 TASKS 规则 2 的
   「单文件 ≤ 400 行」硬约束；
2. 流程状态机（判定是否放行、后台任务起停、结果卡组装）是**可单测的业务
   逻辑**，混在窗口里就只能靠点界面来测。

对外**只发信号**，不反向依赖界面控件 —— 主窗口连信号后更新状态栏 / 画布 /
结果卡。这样控制器可以脱离 QMainWindow 单测。

线程约定
--------
控制器本身在主线程；后台任务走 `TaskRunner`（QThread），其信号在主线程
派发（Qt 的队列连接），因此控制器槽里碰 UI 是安全的。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal

from ncm.core.identify import IdentifyResult
from ncm.gui.workers import IdentifyWorker, RefineWorker, TaskRunner
from ncm.i18n import tr


class RefineFlow(QObject):
    """判定 → 精修 → 结果卡 的流程控制器。"""

    # ---- 状态 ----
    status = Signal(str)                  # 状态栏文案
    buttons = Signal(bool, bool)          # (判定按钮可用, 精修按钮可用)
    fit_ready = Signal(object)            # 管线结果 -> 主窗口画观测/计算/差值
    identify_passed_changed = Signal(bool)
    error = Signal(str)                   # 错误文案（主线程弹窗）
    cancelled = Signal()
    confirm_dialog = Signal(object)       # IdentifyResult -> 主窗口弹判定框
    refine_running_changed = Signal(bool)  # 精修起止（禁用按钮/显示取消）

    def __init__(self, structure_provider, parent=None) -> None:
        """structure_provider : callable() -> CifStructure | None
        （注入而不是直接依赖 CIF 面板，便于单测）。"""
        super().__init__(parent)
        self._structure_provider = structure_provider
        self._pattern = None
        self._pattern_path: str | None = None
        self._identify_passed = False
        self._last_result = None
        self._last_card = None
        # 后台任务包装（公开属性：主窗口与测试都要能替换/检查）
        self.identify_runner: TaskRunner | None = None
        self.refine_runner: TaskRunner | None = None

    # ------------------------------------------------------------------ #
    # 状态读取
    # ------------------------------------------------------------------ #
    @property
    def is_identified(self) -> bool:
        """物相判定是否已通过（或用户明确选择「仍按 NCM 精修」）。"""
        return self._identify_passed

    def set_identified(self, value: bool) -> None:
        """直接设置判定状态（供主窗口/测试设置）。"""
        self._identify_passed = bool(value)
        self.identify_passed_changed.emit(self._identify_passed)

    @property
    def last_result(self):
        """最近一次管线的结果（None = 还没精修过）。"""
        return self._last_result

    @property
    def last_card(self) -> dict | None:
        """最近一次生成的结果卡。"""
        return self._last_card

    @property
    def pattern(self):
        return self._pattern

    # ------------------------------------------------------------------ #
    # 输入
    # ------------------------------------------------------------------ #
    def set_pattern(self, pattern, path: str | None = None) -> None:
        """导入谱图。旧结果作废（不能拿上一份样的结果误导用户）。"""
        self._pattern = pattern
        self._pattern_path = path
        self._last_result = None
        self._last_card = None
        self._identify_passed = False

    def clear_result(self) -> None:
        """清掉最近一次精修的结果与结果卡。"""
        self._last_result = None
        self._last_card = None
        self._identify_passed = False

    # ------------------------------------------------------------------ #
    # 判定
    # ------------------------------------------------------------------ #
    def start_identify(self) -> None:
        """启动物相判定（后台线程）。

        导入谱图后自动触发；也可由面板按钮手动重跑。
        """
        if self._pattern is None:
            self.error.emit(tr("msg.no_pattern"))
            return
        if self.identify_runner is not None and self.identify_runner.is_running():
            return
        self.status.emit(tr("status.identify.running"))
        self.buttons.emit(False, False)
        runner = TaskRunner(IdentifyWorker(self._pattern), self)
        self.identify_runner = runner
        runner.progress.connect(self._on_progress)
        runner.finished.connect(self.handle_identified)
        runner.failed.connect(self.error)
        runner.start()

    def handle_identified(self, res: IdentifyResult) -> None:
        """判定完成：按结论决定是否放行精修。"""
        self.status.emit(tr("status.identify.ok") if res.ok
                         else tr("status.identify.fail", reason=res.kind))
        self._identify_passed = bool(res.ok)
        self.identify_passed_changed.emit(self._identify_passed)
        self.buttons.emit(True, res.ok)
        if res.ok:
            return
        # 判定不过：不进入精修，弹对话框说明原因
        self.confirm_dialog.emit(res)

    def allow_refine_anyway(self) -> None:
        """用户明确选择「仍按 NCM 精修」。

        结构类型是层状 R-3m，只是晶胞不在 NCM 族内 —— 由用户承担这个判断。
        """
        self._identify_passed = True
        self.identify_passed_changed.emit(True)
        self.buttons.emit(True, True)

    # ------------------------------------------------------------------ #
    # 精修
    # ------------------------------------------------------------------ #
    def start_refine(self) -> None:
        """启动精修（后台线程，跑三段管线）。"""
        if self._pattern is None:
            self.error.emit(tr("msg.no_pattern"))
            return
        structure = self._structure_provider()
        if structure is None:
            self.error.emit(tr("msg.no_cif"))
            return
        if not self._identify_passed:
            self.error.emit(tr("msg.identify_required"))
            return
        if self.refine_runner is not None and self.refine_runner.is_running():
            return
        from ncm.core.pipeline import default_options_for

        runner = TaskRunner(
            RefineWorker(self._pattern, structure,
                         pipeline=default_options_for(structure)), self)
        self.refine_runner = runner
        runner.progress.connect(self._on_progress)
        runner.finished.connect(self.handle_refined)
        runner.failed.connect(self._on_failed)
        runner.cancelled.connect(self._on_cancelled)
        runner.start()
        self.refine_running_changed.emit(True)

    def handle_refined(self, result) -> None:
        """精修完成：发信号让主窗口画图、填结果卡。

        状态栏文案由主窗口的 `_on_refined` 统一设置（它是画布/结果卡/
        状态栏三者的**单一入口**）——这里不再重复发，避免两个来源各写一次
        导致文案不一致。
        """
        self.refine_running_changed.emit(False)
        self.fit_ready.emit(result)

    def accept_result(self, result) -> dict:
        """登记精修结果并生成结果卡（主窗口 `_on_refined` 调它）。

        **结果必须登记在 flow 里**（而不是只存在主窗口的局部变量里）——
        导出控制器（`ncm.gui.exporter`）要通过 `last_result` / `last_card`
        取数据；只在主窗口存一份的话，导出会永远拿不到结果。

        返回结果卡（主窗口据此刷新结果卡面板）。
        """
        self._last_result = result
        self._last_card = self.build_card(result)
        return self._last_card

    def build_card(self, result) -> dict:
        """把管线结果汇成结果卡（附带样品名等上下文）。"""
        from ncm.core.pipeline import build_pipeline_card

        meta = {}
        if self._pattern_path:
            meta["sample_name"] = Path(self._pattern_path).name
        return build_pipeline_card(result, meta)

    def cancel(self) -> None:
        """用户点「取消」。"""
        if self.refine_runner is not None:
            self.refine_runner.cancel()

    def shutdown(self) -> None:
        """窗口关闭时收掉后台线程（否则进程退不干净）。"""
        for runner in (self.identify_runner, self.refine_runner):
            if runner is not None:
                runner.shutdown()

    # ------------------------------------------------------------------ #
    # 内部槽
    # ------------------------------------------------------------------ #
    def _on_progress(self, msg: str, pct) -> None:
        self.status.emit(msg)

    def _on_failed(self, message: str) -> None:
        self.refine_running_changed.emit(False)
        self.buttons.emit(True, self._identify_passed)
        self.error.emit(message)

    def _on_cancelled(self) -> None:
        self.refine_running_changed.emit(False)
        self.status.emit(tr("status.refine.cancelled"))
        self.cancelled.emit()
