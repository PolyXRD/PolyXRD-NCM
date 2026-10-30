"""PolyXRD-NCM 主窗口（T6.4e 拆分后）。

布局（**单窗口**）：左侧谱图画布 + 右侧 CIF 面板 + 精修结果卡。
菜单：文件 / 处理 / 语言（运行时热切换）/ 帮助（关于、版权）。
状态栏：语言 · 当前文件 · 判定状态 · 取消按钮。

**职责边界（T6.4e 重构后）**
----------------------------
主窗口只做「界面 + 接线」，不再承载业务状态机：

- 菜单与动作装配 → :mod:`ncm.gui.menubar`
- 判定 → 精修 → 结果卡的状态机 → :mod:`ncm.gui.flow`
- 关于 / 版权 / 消息框 → :mod:`ncm.gui.dialogs`
- 处理工具条 → :mod:`ncm.gui.toolbar`
- 结果卡面板 → :mod:`ncm.gui.resultcard`

主窗口对既有属性的暴露（``act_*`` / ``menu_*`` / ``lbl_*`` / ``btn_*``）
保持不变，既有测试契约不受影响。
"""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QMainWindow, QSplitter

from ncm.core.solve import background_curve, residual_arrays
from ncm.gui import dialogs, files
from ncm.gui.canvas import PatternCanvas
from ncm.gui.exporter import Exporter
from ncm.gui.flow import RefineFlow
from ncm.gui.identify_dialog import IdentifyDialog
from ncm.gui.menubar import MenuBuilder
from ncm.gui.peakpanel import build_peak_dock
from ncm.gui.resources import resource_path
from ncm.gui.rightpanel import DEFAULT_WIDTH as RIGHT_PANEL_WIDTH
from ncm.gui.rightpanel import build_right_panel
from ncm.gui.statusbar import StatusBar
from ncm.gui.toolbar import ProcessController, ProcessToolbar
from ncm.i18n import (
    current_language,
    load_language,
    save_language,
    set_language,
    tr,
)
from ncm.version import APP_NAME, __version__


class MainWindow(QMainWindow):
    """主窗口：导入谱图 → 判定 → 精修 的单窗口载体。"""

    def __init__(self) -> None:
        super().__init__()
        load_language()
        self._pattern = None
        self._pattern_path: str | None = None
        self._build_menus()
        self._build_central()
        self._build_peak_dock()
        self._build_status()
        # 流程控制器（T6.4e 抽出）：判定 → 精修 → 结果卡的状态机
        self.flow = RefineFlow(self.current_structure, self)
        self.flow.status.connect(self._on_task_progress)
        self.flow.buttons.connect(self._on_flow_buttons)
        self.flow.fit_ready.connect(self._on_refined)
        self.flow.error.connect(self._on_flow_error)
        self.flow.cancelled.connect(self._on_refine_cancelled)
        self.flow.confirm_dialog.connect(self._on_confirm_dialog)
        self.flow.refine_running_changed.connect(self._set_refining)
        # 导出控制器（T7.1d）：结果就绪后才允许导出
        self.exporter = Exporter(
            self,
            result_provider=lambda: self.flow.last_result,
            card_provider=lambda: self.flow.last_card,
        )
        self._set_export_enabled(False)
        # 先接处理工具条（会创建 act_reset），再统一刷新文案 —— 顺序反了
        # retranslateUi 会找不到 act_reset
        self._wire_process()
        self.retranslateUi()

    # ------------------------------------------------------------------ #
    # 流程状态代理（状态真身在 RefineFlow 里）
    # ------------------------------------------------------------------ #
    @property
    def _identify_passed(self) -> bool:
        """物相判定是否已通过。"""
        return self.flow.is_identified

    @_identify_passed.setter
    def _identify_passed(self, value: bool) -> None:
        self.flow.set_identified(value)

    @property
    def _identify_runner(self):
        """判定后台任务包装（真身在 RefineFlow 里）。"""
        return self.flow.identify_runner

    @_identify_runner.setter
    def _identify_runner(self, value) -> None:
        self.flow.identify_runner = value

    @property
    def _refine_runner(self):
        """精修后台任务包装（真身在 RefineFlow 里）。"""
        return self.flow.refine_runner

    @_refine_runner.setter
    def _refine_runner(self, value) -> None:
        self.flow.refine_runner = value

    @property
    def _last_solution(self):
        """最近一次精修结果（None = 还没精修过）。"""
        return self.flow.last_result

    @property
    def _last_card(self) -> dict | None:
        """最近一次结果卡。"""
        return self.flow.last_card

    def _on_flow_buttons(self, identify: bool, refine: bool) -> None:
        """流程控制器 → 按钮可用状态。"""
        self.cif_panel.set_buttons_enabled(identify=identify, refine=refine)
        self.act_process["fit"].setEnabled(refine)

    def _on_flow_error(self, message: str) -> None:
        """流程控制器报错 → 弹窗。"""
        self._msg_box(message, error=True)

    def _on_export(self, kind: str) -> None:
        """菜单「导出」→ 交给导出控制器（T7.1d）。"""
        getattr(self.exporter, f"export_{kind}")()

    def _set_export_enabled(self, on: bool) -> None:
        """有精修结果时才允许导出。"""
        for key in ("png", "svg", "csv", "txt", "html"):
            act = getattr(self, f"act_export_{key}", None)
            if act is not None:
                act.setEnabled(on)

    # ------------------------------------------------------------------ #
    # 构建界面
    # ------------------------------------------------------------------ #
    def _build_menus(self) -> None:
        """装配菜单与全部 QAction（T6.4e 抽到 :mod:`ncm.gui.menubar`）。"""
        self.menus = MenuBuilder(
            self,
            on_open=self._on_open,
            on_import_cif=self._on_import_cif,
            on_about=self._on_about,
            on_copyright=self._on_copyright,
            on_language=self._on_language,
            on_export=self._on_export,
        )
        # 保持既有属性契约：act_* / menu_* 直接挂在主窗口上
        self.__dict__.update(self.menus.install())

    def _build_central(self) -> None:
        """两栏布局：左谱图画布 | 右 CIF 面板（下方含结果卡）。"""
        splitter = QSplitter(Qt.Horizontal, self)
        self.canvas = PatternCanvas(self)
        splitter.addWidget(self.canvas)
        right, self.cif_panel, self.result_card = build_right_panel(splitter)
        self.cif_panel.import_requested.connect(self._on_import_cif)
        self.cif_panel.identify_requested.connect(self._on_identify)
        self.cif_panel.refine_requested.connect(self._on_refine)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([700, RIGHT_PANEL_WIDTH])
        self.setCentralWidget(splitter)
        icon = resource_path("app-icon.png")
        if icon.exists():
            self.setWindowIcon(QIcon(str(icon)))
    def _build_peak_dock(self) -> None:
        """底部停靠窗口：寻峰结果表（可折叠，不占主视野）。"""
        self.peak_panel, self.dock_peaks = build_peak_dock(self)

    def _build_status(self) -> None:
        """状态栏：语言 · 文件 · 判定状态 · 取消按钮（T6.4e 抽到 statusbar）。"""
        self.status = StatusBar(self, on_cancel=self._on_cancel_refine)
        self.lbl_lang = self.status.lbl_lang
        self.lbl_file = self.status.lbl_file
        self.lbl_identify = self.status.lbl_identify
        self.btn_cancel = self.status.btn_cancel

    # ------------------------------------------------------------------ #
    # 处理工具条（T6.2）
    # ------------------------------------------------------------------ #
    def _wire_process(self) -> None:
        """装配处理工具条与动作接线。

        动作在 `act_process` 里已建好（菜单用），这里把它们挂上工具条并
        接上处理控制器；未导入谱图时全部禁用。
        """
        self.controller = ProcessController(self)
        self.toolbar = ProcessToolbar(self)
        self.toolbar.attach(self.act_process)
        self.act_reset = QAction(self)
        self.act_reset.triggered.connect(self.controller.reset)
        self.toolbar.addAction(self.act_reset)
        self.addToolBar(self.toolbar)
        self.act_process["smooth"].triggered.connect(self.controller.apply_smooth)
        self.act_process["background"].triggered.connect(
            self.controller.apply_background)
        self.act_process["kalpha2"].triggered.connect(
            self.controller.apply_kalpha2)
        self.act_process["peaks"].triggered.connect(self.controller.find_peaks)
        self.act_process["fit"].triggered.connect(self._on_refine)
        self._set_process_enabled(False)

    def _set_process_enabled(self, on: bool) -> None:
        """导入谱图后才允许处理动作（拟合动作留到 T6.3 接线）。"""
        for key in ("smooth", "background", "kalpha2", "peaks"):
            self.act_process[key].setEnabled(on)
        self.act_reset.setEnabled(on)

    def _sync_peak_markers(self) -> None:
        """把寻峰结果标到画布上，并刷新峰列表停靠窗。

        （T7.1d 起实现下沉到 `ProcessController.sync_peak_markers`，
        本方法只做转发，保持既有调用契约。）
        """
        self.controller.sync_peak_markers()

    def current_structure(self):
        """当前选中的内置 CIF 结构（未选中返回 None）。"""
        name = self.cif_panel.current_name()
        if not name:
            return None
        try:
            from ncm.core.solve import builtin_structure

            return builtin_structure(name)
        except (FileNotFoundError, ValueError):
            return None

    # ------------------------------------------------------------------ #
    # 多语言
    # ------------------------------------------------------------------ #
    def retranslateUi(self) -> None:
        """语言切换后刷新全部文案。"""
        self.setWindowTitle(f"{APP_NAME} v{__version__} · {tr('app.title')}")
        self.menus.retranslate()
        self.act_reset.setText(tr("menu.process.reset"))
        self.grp_cif = self.cif_panel.grp_cif
        self.cif_list = self.cif_panel.cif_list
        self.btn_import_cif = self.cif_panel.btn_import_cif
        self.btn_identify = self.cif_panel.btn_identify
        self.btn_refine = self.cif_panel.btn_refine
        self.cif_panel.retranslate()
        self.status.retranslate()
        self.canvas.retranslate()
        self.result_card.retranslate()

    def closeEvent(self, event) -> None:
        """关闭窗口时收掉后台线程（否则进程退不干净）。"""
        self.flow.shutdown()
        super().closeEvent(event)

    # ------------------------------------------------------------------ #
    # 槽：文件与谱图
    # ------------------------------------------------------------------ #
    def _on_open(self) -> None:
        """打开谱图，失败弹提示。"""
        path = files.choose_pattern(self)
        if not path:
            return
        try:
            pat = files.read_pattern(path)
        except Exception as exc:  # noqa: BLE001 —— 统一转成用户可读提示
            self._msg_box(files.describe_error(path, exc), error=True)
            return
        self._pattern = pat
        self._pattern_path = path
        self.canvas.show_pattern(np.asarray(pat.two_theta),
                                 np.asarray(pat.intensity))
        self.lbl_file.setText(tr("status.file", path=path))
        self._set_process_enabled(True)
        # 换谱 → 旧结果卡作废（不能拿上一份样的结果误导用户）
        self.result_card.clear()
        self._set_export_enabled(False)
        self.flow.set_pattern(pat, path)
        # 需求：导入后**先判定**是不是 NCM，不是则中止后续操作
        self._on_identify()

    # ------------------------------------------------------------------ #
    # 流程编排：判定 → 精修（T6.3 接入；T6.4e 抽到 RefineFlow）
    # ------------------------------------------------------------------ #
    def _on_identify(self) -> None:
        """启动物相判定（后台线程）。

        导入谱图后自动触发一次；也可由面板按钮手动重跑。
        判定未通过时**不进入精修**，并弹对话框说明原因。
        """
        self.flow.set_pattern(self._pattern, self._pattern_path)
        self.flow.start_identify()

    def _on_identified(self, res) -> None:
        """判定完成：按结论决定是否放行精修（转发给流程控制器）。"""
        self.flow.handle_identified(res)

    def _on_confirm_dialog(self, res) -> None:
        """判定不过 → 弹对话框；用户选「仍按 NCM 精修」则放行。"""
        dlg = IdentifyDialog(res, self)
        dlg.exec()
        if dlg.continue_anyway:
            # 用户明确选择「仍按 NCM 精修」（结构类型是层状 R-3m，
            # 只是晶胞不在 NCM 族内 —— 由用户承担这个判断）
            self.flow.allow_refine_anyway()

    def _on_refine(self) -> None:
        """启动精修（后台线程，跑三段管线；转发给流程控制器）。"""
        self.flow.start_refine()

    def _on_refined(self, result) -> None:
        """精修完成：画布换成观测/计算/差值叠加图 + 结果卡刷新 + 状态栏报 Rwp。

        这里是画布 / 结果卡 / 状态栏三者的**单一入口** —— 流程控制器只发
        `fit_ready` 信号，不直接写界面文案。
        """
        sr = result.stage1
        tt, yo, yc = residual_arrays(sr)
        self.canvas.show_fit(tt, yo, yc, np.asarray(yo) - np.asarray(yc),
                             background=background_curve(sr))
        self.result_card.set_card(self.flow.accept_result(result))
        self.lbl_identify.setText(tr("status.refine.done", rwp=result.rwp))
        # 有结果了 → 开放导出
        self._set_export_enabled(True)

    def _on_task_progress(self, msg: str, pct=None) -> None:
        """后台任务进度 → 状态栏。"""
        self.lbl_identify.setText(msg)

    def _on_task_failed(self, message: str) -> None:
        """后台任务出错 → 弹窗 + 恢复按钮状态。"""
        self._set_refining(False)
        self.cif_panel.set_buttons_enabled(identify=True,
                                           refine=self._identify_passed)
        self._msg_box(message, error=True)

    def _set_refining(self, running: bool) -> None:
        """精修期间：禁用「开始精修」、显示/隐藏「取消」按钮。"""
        self.act_process["fit"].setEnabled(not running)
        self.cif_panel.set_buttons_enabled(identify=not running,
                                           refine=self._identify_passed
                                           and not running)
        self.btn_cancel.setVisible(running)
        self.btn_cancel.setEnabled(running)
        if running:
            self.lbl_identify.setText(tr("status.refine.working"))

    def _on_refine_cancelled(self) -> None:
        """精修被用户取消。"""
        self._set_refining(False)

    def _on_cancel_refine(self) -> None:
        """用户点「取消」。"""
        self.flow.cancel()
        self.btn_cancel.setEnabled(False)

    def _on_import_cif(self) -> None:
        """导入用户 CIF（T6.3 接上判定流程后才会真正使用）。"""
        path = files.choose_cif(self)
        if path:
            self.lbl_file.setText(tr("status.file", path=path))

    # ------------------------------------------------------------------ #
    # 槽：语言与帮助
    # ------------------------------------------------------------------ #
    def _on_language(self, code: str) -> None:
        set_language(code)
        save_language(code)
        self.retranslateUi()

    def _on_about(self) -> None:
        """关于对话框（T6.4e 抽到 dialogs 模块）。"""
        dialogs.show_about(self)

    def _on_copyright(self) -> None:
        """版权与许可对话框（双语并列）。"""
        dialogs.show_copyright(self)

    # ------------------------------------------------------------------ #
    # 工具
    # ------------------------------------------------------------------ #
    def _msg_box(self, text: str, *, error: bool = False) -> None:
        """统一弹窗（纯文本）。"""
        dialogs.show_message(self, text, error=error)
