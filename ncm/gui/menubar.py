"""菜单与 QAction 构建（T6.4e 抽取）。

从 `MainWindow` 抽出来的**菜单装配逻辑**：把「有哪些动作、挂在哪个菜单、
文案是什么」集中在一处，主窗口只负责把槽接上去。

为什么要抽
----------
`main_window.py` 在 T6.3/T6.4 之后超了「单文件 ≤ 400 行」的硬约束，而菜单
部分是**纯声明式**的（不碰任何业务状态），最适合独立成文件。

对外接口
--------
- :meth:`MenuBuilder.install` → 返回 ``{属性名: 对象}`` 字典，主窗口
  ``self.__dict__.update(...)`` 即可保持既有属性契约
  （``win.act_open`` / ``win.menu_file`` / ``win.act_process`` …）；
- :meth:`MenuBuilder.retranslate` → 语言切换后统一刷新菜单与动作文案。

文案全部走 i18n ``tr()``，三语 key 集合由 ``tests/test_i18n.py`` 硬断言。
"""
from __future__ import annotations

from PySide6.QtGui import QAction, QActionGroup

from ncm.i18n import current_language, tr

#: 语言菜单顺序
LANG_ORDER = ("zh_CN", "en_US", "ja_JP")

#: 处理类动作（键同时用于 i18n key：``menu.process.<key>``）
PROCESS_KEYS = ("smooth", "background", "kalpha2", "peaks", "fit")


class MenuBuilder:
    """构建主窗口的 QAction 与四条菜单。"""

    def __init__(self, window, *, on_open, on_import_cif, on_about,
                 on_copyright, on_language, on_export=None) -> None:
        """window : QMainWindow（作为 action 的 parent）

        五个回调都是主窗口的槽，构造时即接线 —— 菜单装配本身就是「声明
        有哪些动作 + 点了做什么」。

        on_export : callable(kind: str) -> None，kind ∈
                    {"png","svg","csv","txt","html"}；为 None 时导出动作
                    建好但**不接线**（保持禁用）。
        """
        self.window = window
        self._on_language = on_language
        self._on_export = on_export
        self._build_actions(on_open, on_import_cif, on_about, on_copyright)
        self._build_menus()

    # ------------------------------------------------------------------ #
    # 动作
    # ------------------------------------------------------------------ #
    def _build_actions(self, on_open, on_import_cif, on_about,
                       on_copyright) -> None:
        """创建全部 QAction（文案在 :meth:`retranslate` 中统一设置）。"""
        self.act_open = QAction(self.window)
        self.act_open.triggered.connect(on_open)
        self.act_import_cif = QAction(self.window)
        self.act_import_cif.triggered.connect(on_import_cif)
        # 导出类动作：T7.1 起真正可用（由 Exporter 接线）
        self.act_export_png = QAction(self.window)
        self.act_export_svg = QAction(self.window)
        self.act_export_csv = QAction(self.window)
        self.act_export_txt = QAction(self.window)
        self.act_export_html = QAction(self.window)
        if self._on_export is not None:
            for kind, act in (("png", self.act_export_png),
                              ("svg", self.act_export_svg),
                              ("csv", self.act_export_csv),
                              ("txt", self.act_export_txt),
                              ("html", self.act_export_html)):
                act.triggered.connect(
                    lambda _checked=False, k=kind: self._on_export(k))
        self.act_exit = QAction(self.window)
        self.act_exit.triggered.connect(self.window.close)
        self.act_about = QAction(self.window)
        self.act_about.triggered.connect(on_about)
        self.act_copyright = QAction(self.window)
        self.act_copyright.triggered.connect(on_copyright)
        # 处理类动作：菜单与工具条共用同一批 QAction（T6.2）
        self.act_process: dict[str, QAction] = {}
        for key in PROCESS_KEYS:
            act = QAction(self.window)
            act.setEnabled(False)
            self.act_process[key] = act
        # 语言组（互斥、可勾选）
        self.lang_group = QActionGroup(self.window)
        self.lang_group.setExclusive(True)
        self.act_langs: dict[str, QAction] = {}
        for code in LANG_ORDER:
            act = QAction(self.window)
            act.setCheckable(True)
            act.triggered.connect(
                lambda _checked=False, c=code: self._on_language(c))
            self.lang_group.addAction(act)
            self.act_langs[code] = act

    # ------------------------------------------------------------------ #
    # 菜单
    # ------------------------------------------------------------------ #
    def _build_menus(self) -> None:
        """组装四条菜单：文件 / 处理 / 语言 / 帮助。"""
        bar = self.window.menuBar()
        self.menu_file = bar.addMenu("")
        self.menu_file.addAction(self.act_open)
        self.menu_file.addAction(self.act_import_cif)
        self.menu_file.addSeparator()
        self.menu_file.addAction(self.act_export_png)
        self.menu_file.addAction(self.act_export_svg)
        self.menu_file.addAction(self.act_export_csv)
        self.menu_file.addAction(self.act_export_txt)
        self.menu_file.addAction(self.act_export_html)
        self.menu_file.addSeparator()
        self.menu_file.addAction(self.act_exit)
        self.menu_process = bar.addMenu("")
        for act in self.act_process.values():
            self.menu_process.addAction(act)
        self.menu_language = bar.addMenu("")
        for code in LANG_ORDER:
            self.menu_language.addAction(self.act_langs[code])
        self.menu_help = bar.addMenu("")
        self.menu_help.addAction(self.act_about)
        self.menu_help.addAction(self.act_copyright)

    # ------------------------------------------------------------------ #
    # 对外
    # ------------------------------------------------------------------ #
    def install(self) -> dict:
        """返回可直接挂到主窗口上的属性字典（保持既有属性契约）。"""
        return {
            "act_open": self.act_open,
            "act_import_cif": self.act_import_cif,
            "act_export_png": self.act_export_png,
            "act_export_svg": self.act_export_svg,
            "act_export_csv": self.act_export_csv,
            "act_export_txt": self.act_export_txt,
            "act_export_html": self.act_export_html,
            "act_exit": self.act_exit,
            "act_about": self.act_about,
            "act_copyright": self.act_copyright,
            "act_process": self.act_process,
            "act_langs": self.act_langs,
            "lang_group": self.lang_group,
            "menu_file": self.menu_file,
            "menu_process": self.menu_process,
            "menu_language": self.menu_language,
            "menu_help": self.menu_help,
        }

    def retranslate(self) -> None:
        """语言切换后刷新菜单标题与动作文案。"""
        self.menu_file.setTitle(tr("menu.file"))
        self.menu_process.setTitle(tr("menu.process"))
        self.menu_language.setTitle(tr("menu.language"))
        self.menu_help.setTitle(tr("menu.help"))
        self.act_open.setText(tr("menu.file.open"))
        self.act_import_cif.setText(tr("menu.file.import_cif"))
        self.act_export_png.setText(tr("menu.file.export_png"))
        self.act_export_svg.setText(tr("menu.file.export_svg"))
        self.act_export_csv.setText(tr("menu.file.export_csv"))
        self.act_export_txt.setText(tr("menu.file.export_txt"))
        self.act_export_html.setText(tr("menu.file.export_html"))
        self.act_exit.setText(tr("menu.file.exit"))
        self.act_about.setText(tr("menu.help.about"))
        self.act_copyright.setText(tr("menu.help.copyright"))
        for key, act in self.act_process.items():
            act.setText(tr(f"menu.process.{key}"))
        for code, act in self.act_langs.items():
            act.setText(tr(f"lang.{code}"))
            act.setChecked(code == current_language())
