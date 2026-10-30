"""后台工作线程（T6.3b）。

GUI 里凡是耗时超过 ~0.5 s 的活都必须放后台线程：

- 判定门：真实样快速路径 0.39 s（T5.1 实测），但走"池中最佳标定"路径
  可能到数秒；
- 精修：标准配方 40 s（T1.4 实测），**病态结构 >200 s**。

**三条硬要求**（TASKS.md T6.3）：
1. 精修在后台线程执行，主线程不阻塞（窗口可拖动、可交互）；
2. 接 `progress_cb` / `on_iter` 显示进度，并提供**取消**按钮；
3. 精修期间禁用「开始精修」，防止并发触发（在 main_window 侧实现）。

**设计取舍**
- 用 `QThread` + worker 对象，而不是 `QThreadPool`：池里的任务不好精确取消，
  而取消是硬需求。
- **取消是协作式的**：主线程点「取消」只置一个 flag，核心层的 `cancel_cb`
  在下一次残差评估时抛 `RefineCancelled`（见 `ncm/core/refine/nonlinear.py`
  的 T6.3a 修改）。这样不会在 LM 迭代中途硬杀线程留下不一致状态。
- **线程内的异常绝不能被 Qt 静默吞掉**：一律经 `failed` 信号回报主线程，
  再由主线程弹窗。
- 进度文案由 GUI 自己生成（`on_iter` 给迭代次数与当前 Rwp），**不复用核心层
  里硬编码的中文串** —— 否则英文/日文界面会出现中英混排。
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal, Slot

from ncm.core.pipeline import PipelineOptions, run_pipeline
from ncm.core.refine.nonlinear import RefineCancelled
from ncm.core.solve import SolveOptions, solve
from ncm.i18n import tr

#: 进度信号节流：每 N 次残差评估发一次（on_iter 每次评估都触发，不节流会淹没事件循环）
PROGRESS_THROTTLE = 40


class RefineWorker(QObject):
    """后台精修线程体。

    跑的是**三段管线**（`ncm.core.pipeline.run_pipeline`）：
    stage1 峰形/晶胞/PO → stage2 Li 占位 + z_O → stage3 晶粒尺寸反演。
    只跑 stage1 的话结果卡里 Li 占位与晶粒尺寸恒为「未测定」，
    满足不了需求原文（"给出结果包括…晶粒尺寸…Li 占位"）。
    """

    progress = Signal(str, object)     # (本地化文案, 百分比或 None)
    finished = Signal(object)          # RefinePipelineResult
    failed = Signal(str)               # 错误文案
    cancelled = Signal()

    def __init__(self, pat, structure, options: SolveOptions | None = None,
                 pipeline: PipelineOptions | None = None,
                 parent=None) -> None:
        super().__init__(parent)
        self.pat = pat
        self.structure = structure
        self.options = options
        self.pipeline = pipeline
        self._cancel = False
        self._iters = 0

    # ------------------------------------------------------------------ #
    # 取消
    # ------------------------------------------------------------------ #
    def request_cancel(self) -> None:
        """请求取消（线程安全：只是个 bool 置位）。"""
        self._cancel = True

    def cancel_cb(self) -> bool:
        """核心层的取消钩子。"""
        return self._cancel

    # ------------------------------------------------------------------ #
    # 进度
    # ------------------------------------------------------------------ #
    def _progress(self, msg: str, pct: float | None) -> None:
        self.progress.emit(tr("status.refine.working"), pct)

    def _on_iter(self, gen: int, rwp: float) -> None:
        self._iters = gen
        if gen % PROGRESS_THROTTLE == 0:
            self.progress.emit(
                tr("status.refine.iter", n=gen, rwp=rwp), None)

    # ------------------------------------------------------------------ #
    # 主流程
    # ------------------------------------------------------------------ #
    @Slot()
    def run(self) -> None:
        try:
            opt = self.pipeline
            if opt is None:
                opt = PipelineOptions(stage1=self.options or SolveOptions())
            res = run_pipeline(self.pat, self.structure, opt,
                               progress_cb=self._progress,
                               on_iter=self._on_iter,
                               cancel_cb=self.cancel_cb)
        except RefineCancelled:
            self.cancelled.emit()
        except Exception as exc:  # noqa: BLE001 —— 统一转成用户可读提示
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        else:
            self.finished.emit(res)


class IdentifyWorker(QObject):
    """后台物相判定线程体。"""

    progress = Signal(str, object)
    finished = Signal(object)          # IdentifyResult
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, pat, cif_pool=None, parent=None) -> None:
        super().__init__(parent)
        self.pat = pat
        self.cif_pool = cif_pool
        self._cancel = False

    def request_cancel(self) -> None:
        self._cancel = True

    def cancel_cb(self) -> bool:
        return self._cancel

    @Slot()
    def run(self) -> None:
        from ncm.core.identify import identify

        try:
            self.progress.emit(tr("status.identify.running"), None)
            if self.cif_pool is None:
                from ncm.core.identify import default_pool

                res = identify(self.pat, default_pool())
            else:
                res = identify(self.pat, self.cif_pool)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        else:
            self.finished.emit(res)


class TaskRunner(QObject):
    """线程包装：负责起停、转发信号、收尾清理。

    典型用法::

        runner = TaskRunner(RefineWorker(pat, struct))
        runner.finished.connect(self._on_refined)
        runner.failed.connect(self._on_failed)
        runner.start()
        ...
        runner.cancel()          # 用户点「取消」
        runner.shutdown()        # 窗口关闭时收尾
    """

    progress = Signal(str, object)
    finished = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, worker: QObject, parent=None) -> None:
        super().__init__(parent)
        self.worker = worker
        self.thread = QThread(self)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.progress)
        self.worker.finished.connect(self.finished)
        self.worker.failed.connect(self.failed)
        self.worker.cancelled.connect(self.cancelled)
        # 任一终态都收尾：退线程 + 回收 worker
        for sig in (self.finished, self.failed, self.cancelled):
            sig.connect(self._quit)
        self.thread.finished.connect(self.worker.deleteLater)

    def start(self) -> None:
        """启动线程。"""
        self.thread.start()

    def cancel(self) -> None:
        """请求取消（不阻塞；真正中止在核心层下一次残差评估时）。"""
        self.worker.request_cancel()

    def is_running(self) -> bool:
        """线程是否还在跑。"""
        return self.thread.isRunning()

    def shutdown(self, timeout_ms: int = 5000) -> None:
        """收尾：请求取消并等线程退出（窗口关闭时调用）。"""
        if self.thread.isRunning():
            self.worker.request_cancel()
            self.thread.quit()
            self.thread.wait(timeout_ms)
            if self.thread.isRunning():
                self.thread.terminate()
                self.thread.wait(1000)

    @Slot()
    def _quit(self) -> None:
        self.thread.quit()
