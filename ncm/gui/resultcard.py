"""精修结果卡面板（T6.4b）。

把 `ncm.core.resultcard.build_card()` 产出的结果卡渲染成界面上的分组表格：
晶体学 / 晶胞 / 组成 / 微结构 / 峰形 / 拟合优度。

**设计取舍**
------------
1. **数值格式化全在本模块**（`_fmt_*`），核心层只给原始数值 —— 这样
   换语言/换界面风格不会动核心层，也避免同一数字在两个地方格式不一致。
2. **晶系名按语言取**：`crystal_system_zh` 是中文，"三方"在英文界面里是
   噪声。故 zh_CN 用 `_zh`，其余语言用原生英文名（trigonal/hexagonal/…）。
3. **未测定的项显式标"—"**，不留空、不显示 0 —— 报告里"未测定"与
   "测得 0"是两回事（晶粒尺寸未检出时 D=inf，界面要写"超出检出上限"
   而不是 inf）。
4. 卡片内容由 `set_card()` 整体替换，`retranslate()` 只重刷文案不重算数值
   —— 切语言不该触发一次精修。
"""
from __future__ import annotations

import math

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ncm.i18n import current_language, tr

#: 卡片各分组的 i18n key（顺序即显示顺序）
GROUPS = ("structure", "cell", "composition", "microstructure", "profile",
          "fit")


def _fmt(v, digits: int = 4, dash: str = "—") -> str:
    """数值 -> 字符串；None/NaN -> 占位符。"""
    if v is None:
        return dash
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    if math.isnan(f):
        return dash
    if math.isinf(f):
        return "∞" if f > 0 else "-∞"
    return f"{f:.{digits}f}"


def _fmt_pct(v, digits: int = 4) -> str:
    """百分数（Rwp 等）-> 字符串。"""
    if v is None:
        return "—"
    return f"{_fmt(v, digits)} %"


def _fmt_ang(v, digits: int = 5) -> str:
    """长度（Å）-> 字符串。"""
    if v is None:
        return "—"
    return f"{_fmt(v, digits)} Å"


def _fmt_deg(v, digits: int = 3) -> str:
    """角度（度）-> 字符串。"""
    if v is None:
        return "—"
    return f"{_fmt(v, digits)}°"


def _fmt_nm(v) -> str:
    """晶粒尺寸（nm）-> 字符串；inf = 超出检出上限。"""
    if v is None:
        return "—"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    if math.isinf(f):
        return tr("card.value.above_limit")
    return f"{f:.2f} nm"


def _fmt_strain(v) -> str:
    """微观应变 -> 字符串。

    口径（VALIDATION_TCH §5）：ε 触下界（X→0）应写"未检出可分辨微观应变"，
    **不得显示 0.000 的假精度**。
    """
    if v is None:
        return "—"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    if abs(f) < 1e-9:
        return tr("card.value.no_strain")
    return f"{f:.2e}"


class ResultCard(QWidget):
    """结果卡面板（只读展示）。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._card: dict | None = None
        self._rows: dict[str, QLabel] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        inner = QWidget(scroll)
        self._body = QVBoxLayout(inner)
        self._body.setContentsMargins(6, 6, 6, 6)
        self._groups: dict[str, QGroupBox] = {}
        self._forms: dict[str, QFormLayout] = {}
        for key in GROUPS:
            grp = QGroupBox(inner)
            form = QFormLayout(grp)
            form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
            form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
            self._body.addWidget(grp)
            self._groups[key] = grp
            self._forms[key] = form
        self._body.addStretch(1)
        scroll.setWidget(inner)
        outer.addWidget(scroll)
        self.retranslate()

    # ------------------------------------------------------------------ #
    # 数据
    # ------------------------------------------------------------------ #
    def set_card(self, card: dict | None) -> None:
        """整体替换卡片内容（None = 清空）。"""
        self._card = card
        self.refresh()

    def card(self) -> dict | None:
        """当前卡片（原始 dict）。"""
        return self._card

    def clear(self) -> None:
        """清空卡片。"""
        self.set_card(None)

    # ------------------------------------------------------------------ #
    # 渲染
    # ------------------------------------------------------------------ #
    def _add_row(self, group: str, key: str, label: str, value: str) -> None:
        """在分组里加一行。

        注意 `QFormLayout.addRow(str, QWidget)` 的第一个参数是**标签文本**
        （Qt 内部会自建一个 QLabel），第二个才是字段控件。
        """
        form = self._forms[group]
        lbl = QLabel(self._groups[group])
        lbl.setText(value)
        lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lbl.setWordWrap(True)
        self._rows[key] = lbl
        form.addRow(label, lbl)

    def _clear_rows(self) -> None:
        """清掉所有行。

        行数不多（~30 行），切语言时整体重建比维护行标签映射简单得多，
        也避免了"标签换了但行还在"的错位。QLabel 对象按需新建，不缓存。
        """
        for key, lbl in list(self._rows.items()):
            # QFormLayout.removeRow(QWidget*) 会连同该 widget 一起销毁，
            # 不能再调 deleteLater()（会抛 "already deleted"）。
            self._forms[self._group_of[key]].removeRow(lbl)
        self._rows.clear()
        self._group_of.clear()

    # key -> 分组 的映射（`_clear_rows` 用）
    _group_of: dict[str, str] = {}

    def _row(self, group: str, key: str, label: str, value: str) -> None:
        """加一行并记录其分组归属。"""
        self._group_of[key] = group
        self._add_row(group, key, label, value)

    def refresh(self) -> None:
        """按当前卡片与当前语言重绘（含分组标题）。"""
        self._clear_rows()
        card = self._card
        if card:
            self._fill_structure(card)
            self._fill_cell(card)
            self._fill_composition(card)
            self._fill_microstructure(card)
            self._fill_profile(card)
            self._fill_fit(card)
        self.retranslate()

    def _fill_structure(self, card: dict) -> None:
        s = card.get("structure", {})
        self._row("structure", "s.name", tr("card.row.structure"),
                  s.get("name") or "—")
        self._row("structure", "s.sg", tr("card.row.space_group"),
                  s.get("space_group") or "—")
        self._row("structure", "s.system", tr("card.row.crystal_system"),
                  self._crystal_system(s))
        self._row("structure", "s.pg", tr("card.row.point_group"),
                  s.get("point_group") or "—")
        self._row("structure", "s.lg", tr("card.row.laue_group"),
                  s.get("laue_group") or "—")
        self._row("structure", "s.bravais", tr("card.row.bravais"),
                  s.get("bravais_lattice") or "—")

    def _crystal_system(self, s: dict) -> str:
        """晶系名（按界面语言）。"""
        if current_language() == "zh_CN":
            return s.get("crystal_system_zh") or s.get("crystal_system") or "—"
        return s.get("crystal_system") or s.get("crystal_system_zh") or "—"

    def _fill_cell(self, card: dict) -> None:
        c = card.get("cell", {})
        self._row("cell", "c.a", tr("card.row.a"), _fmt_ang(c.get("a")))
        self._row("cell", "c.b", tr("card.row.b"), _fmt_ang(c.get("b")))
        self._row("cell", "c.c", tr("card.row.c"), _fmt_ang(c.get("c")))
        self._row("cell", "c.al", tr("card.row.alpha"),
                  _fmt_deg(c.get("alpha")))
        self._row("cell", "c.be", tr("card.row.beta"), _fmt_deg(c.get("beta")))
        self._row("cell", "c.ga", tr("card.row.gamma"),
                  _fmt_deg(c.get("gamma")))
        self._row("cell", "c.v", tr("card.row.volume"),
                  f"{_fmt(c.get('volume'), 3)} Å³")
        self._row("cell", "c.ca", tr("card.row.c_over_a"),
                  _fmt(c.get("c_over_a"), 5))

    def _fill_composition(self, card: dict) -> None:
        cp = card.get("composition", {})
        occ = cp.get("li_occupancy")
        self._row("composition", "cp.occ", tr("card.row.li_occupancy"),
                  tr("card.value.not_measured") if occ is None
                  else _fmt(occ, 4))
        zo = cp.get("o_z")
        self._row("composition", "cp.zo", tr("card.row.o_z"),
                  tr("card.value.not_measured") if zo is None
                  else _fmt(zo, 5))

    def _fill_microstructure(self, card: dict) -> None:
        m = card.get("microstructure", {})
        size = m.get("crystallite_size_nm")
        self._row("microstructure", "m.size",
                  tr("card.row.crystallite_size"),
                  tr("card.value.not_measured") if size is None
                  else _fmt_nm(size))
        self._row("microstructure", "m.strain", tr("card.row.strain"),
                  _fmt_strain(m.get("strain")))

    def _fill_profile(self, card: dict) -> None:
        p = card.get("profile", {})
        self._row("profile", "p.zero", tr("card.row.zero"),
                  _fmt_deg(p.get("zero"), 5))
        self._row("profile", "p.uvw", tr("card.row.uvw"),
                  f"U={_fmt(p.get('U'), 6)}  V={_fmt(p.get('V'), 6)}  "
                  f"W={_fmt(p.get('W'), 6)}")
        self._row("profile", "p.eta", tr("card.row.eta"),
                  _fmt(p.get("eta"), 4))
        self._row("profile", "p.asym", tr("card.row.asym"),
                  _fmt(p.get("asym"), 5))
        self._row("profile", "p.b", tr("card.row.bfactor"),
                  _fmt(p.get("bfactor"), 4))
        po = p.get("po_r") or {}
        if po:
            txt = "  ".join(
                f"{name}({v[0]}{v[1]}{v[2]}) r={_fmt(v[3], 4)}"
                for name, v in po.items())
            self._row("profile", "p.po", tr("card.row.po"), txt)

    def _fill_fit(self, card: dict) -> None:
        f = card.get("fit", {})
        self._row("fit", "f.rwp", tr("card.row.rwp"), _fmt_pct(f.get("rwp")))
        self._row("fit", "f.rp", tr("card.row.rp"), _fmt_pct(f.get("rp")))
        self._row("fit", "f.rexp", tr("card.row.rexp"),
                  _fmt_pct(f.get("rexp")))
        rb = f.get("rbragg")
        self._row("fit", "f.rb", tr("card.row.rb"),
                  "—" if rb is None else _fmt_pct(rb))
        self._row("fit", "f.gof", tr("card.row.gof"), _fmt(f.get("gof"), 4))
        self._row("fit", "f.chi2", tr("card.row.chi2"), _fmt(f.get("chi2"), 4))
        self._row("fit", "f.iter", tr("card.row.iterations"),
                  f"{f.get('iterations', 0)}"
                  f"{'' if f.get('success') else '  ' + tr('card.value.not_converged')}")

    # ------------------------------------------------------------------ #
    # 多语言
    # ------------------------------------------------------------------ #
    def retranslate(self) -> None:
        """语言切换后刷新分组标题与行内容（不动数值来源）。"""
        titles = {
            "structure": "card.group.structure",
            "cell": "card.group.cell",
            "composition": "card.group.composition",
            "microstructure": "card.group.microstructure",
            "profile": "card.group.profile",
            "fit": "card.group.fit",
        }
        for key, tkey in titles.items():
            self._groups[key].setTitle(tr(tkey))
        # 行内容里含本地化文本（"未测定"/"超出检出上限"）与本地化标签，
        # 故标题刷完后重绘一次行；**不能**在 refresh() 里再调本方法（会递归）。
        if self._card:
            self._clear_rows()
            self._fill_structure(self._card)
            self._fill_cell(self._card)
            self._fill_composition(self._card)
            self._fill_microstructure(self._card)
            self._fill_profile(self._card)
            self._fill_fit(self._card)
