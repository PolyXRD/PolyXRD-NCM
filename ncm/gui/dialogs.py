"""关于 / 版权 / 通用消息框（T6.4e 抽取 · T7.2 家族化升级）。

从 `MainWindow` 里抽出来的独立对话框工具：

- `show_message()`   —— 统一的消息框（信息 / 错误）；
- `show_about()`     —— 关于对话框（**家族风格**：logo + 版本 + 联系方式）；
- `show_copyright()` —— 版权与许可（家族双语正文，**恒以中英双语并列**，
  不随界面语言切换 —— 许可文本是法律文本，必须两种语言都在场）。

为什么抽：主窗口在 T6.3/T6.4 之后超了「单文件 ≤ 400 行」的硬约束；
这些对话框与主窗口的其它职责无关，独立出来才好复用。

**T7.2：关于对话框升级为正式版**
---------------------------------
原版是纯文本 `QMessageBox`，信息密度低、品牌感弱。现改为自绘对话框：
家族 logo + 产品名/版次 + 一句话定位 + 联系方式 + 版权行。

**logo 缺失时优雅降级**
----------------------
logo 是**可选**资源（资源没随包走时不该让程序起不来）—— 缺失时自动退回
纯文本布局。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QVBoxLayout,
)

from ncm.gui.resources import logo_path
from ncm.i18n import tr
from ncm.version import (
    APP_CONTACT_EMAIL,
    APP_CONTACT_URL,
    APP_NAME,
    APP_TAGLINE,
    __version__,
)

#: 版权要点（恒以中英双语并列展示，语言无关）—— 沿用家族措辞
COPYRIGHT_BODY_ZH = (
    "<p>© 2026 PolyXRD Team。本软件采用<b>双许可</b>发布："
    "<b>学术许可</b>（仅限非商业学术研究与教学，免费）或向版权持有人另行申请的"
    "<b>商业许可</b>。学术许可下可自由使用、复制、修改与分发，"
    "<b>不允许任何商业用途</b>；商用前必须联系版权持有人取得书面商业授权。</p>"
)

COPYRIGHT_BODY_EN = (
    "<p>Copyright © 2026 PolyXRD Team. This software is released under a "
    "<b>dual license</b>: the free <b>Academic License</b> (non-commercial "
    "academic research and education only) or a separately obtained "
    "<b>Commercial License</b>. The Academic License permits use, copying, "
    "modification and distribution <b>for non-commercial purposes only</b>; "
    "commercial use requires a separate written Commercial License.</p>"
)

#: 家族主色（与谱图色板同源，见 ncm.core.palette）
_BRAND = "#0284C7"
_MUTED = "#64748B"


def show_message(parent, text: str, *, error: bool = False) -> None:
    """统一消息框（纯文本）。"""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Critical if error else QMessageBox.Information)
    box.setWindowTitle(tr("msg.error") if error else tr("msg.info"))
    box.setText(text)
    box.exec()


class AboutDialog(QDialog):
    """关于对话框（家族风格：logo + 版本 + 联系方式）。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("menu.help.about"))
        self.setMinimumWidth(440)

        root = QVBoxLayout(self)
        root.setSpacing(10)

        # ---- 顶部：logo + 产品名/版次/定位 ----
        top = QHBoxLayout()
        top.setSpacing(14)
        logo = logo_path()
        if logo:
            lbl_logo = QLabel(self)
            pix = QPixmap(logo)
            if not pix.isNull():
                lbl_logo.setPixmap(pix.scaledToWidth(160, Qt.SmoothTransformation))
                top.addWidget(lbl_logo)
        info = QVBoxLayout()
        info.setSpacing(2)
        lbl_name = QLabel(self)
        lbl_name.setText(f"<span style='color:{_BRAND};"
                         f"font-size:17px;font-weight:600'>{APP_NAME}</span>")
        lbl_ver = QLabel(self)
        lbl_ver.setText(f"<span style='color:{_MUTED}'>v{__version__}</span>")
        lbl_tag = QLabel(self)
        lbl_tag.setText(f"<span style='color:{_MUTED}'>{APP_TAGLINE}</span>")
        lbl_tag.setWordWrap(True)
        for w in (lbl_name, lbl_ver, lbl_tag):
            info.addWidget(w)
        top.addLayout(info, 1)
        root.addLayout(top)

        # ---- 定位说明 ----
        lbl_desc = QLabel(self)
        lbl_desc.setText(tr("app.about_desc"))
        lbl_desc.setWordWrap(True)
        lbl_desc.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(lbl_desc)

        # ---- 联系方式 ----
        lbl_contact = QLabel(self)
        lbl_contact.setText(
            f"<span style='color:{_MUTED}'>"
            f"{tr('menu.help.contact', email=APP_CONTACT_EMAIL)}"
            f" · <a href='{APP_CONTACT_URL}'>github.com/PolyXRD</a></span>")
        lbl_contact.setOpenExternalLinks(True)
        root.addWidget(lbl_contact)

        lbl_copy = QLabel(self)
        lbl_copy.setText(f"<span style='color:{_MUTED}'>© 2026 PolyXRD Team</span>")
        root.addWidget(lbl_copy)


def show_about(parent) -> None:
    """关于对话框。"""
    dlg = AboutDialog(parent)
    dlg.exec()


def show_copyright(parent) -> None:
    """版权与许可对话框（双语并列）。"""
    html = (
        COPYRIGHT_BODY_ZH + COPYRIGHT_BODY_EN
        + f"<p style='color:{_MUTED}'>"
        f"{tr('menu.help.contact', email=APP_CONTACT_EMAIL)}"
        f" · <a href='{APP_CONTACT_URL}'>github.com/PolyXRD</a></p>"
    )
    box = QMessageBox(parent)
    box.setWindowTitle(tr("menu.help.copyright"))
    box.setTextFormat(Qt.RichText)
    box.setText(html)
    box.exec()
