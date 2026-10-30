"""家族化资源与打包配置测试（T7.2）。

判据：
1. **家族资源齐备** —— logo / 启动图 / 图标都在 `ncm/resources/`；
2. **打包态资源路径正确** —— onefile 下资源在 `sys._MEIPASS/ncm/resources/`
   （原先只查 `_MEIPASS/<name>`，打包后必然找不到）；
3. **图标优先 PNG**（Qt6 内建 PNG 解码器；.ico 要额外加载 qico 插件，
   家族实测会显著提高启动期原生崩溃概率）；
4. **关于对话框是正式版**（有 logo、有版本号、有联系方式、logo 缺失能降级）；
5. **PyInstaller spec 存在且随包资源齐全**（CIF / 翻译表 / 品牌资源）。
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
RES = REPO / "ncm" / "resources"


# --------------------------------------------------------------------------- #
# 资源齐备
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("name", ["app-icon.png", "app-icon.ico",
                                  "splash-screen.png", "logo-horizontal.png",
                                  "crystal-mark.png"])
def test_brand_assets_present(name) -> None:
    """家族品牌资源必须随包。"""
    p = RES / name
    assert p.exists(), f"缺家族资源 {name}"
    assert p.stat().st_size > 500, f"{name} 太小，可能损坏"


def test_brand_assets_are_valid_images(qapp) -> None:
    """PNG 必须能被 Qt 解码（否则启动期静默失败）。

    需要 `qapp` fixture —— 没有 QApplication 时 QPixmap 解码会挂起。
    """
    from PySide6.QtGui import QPixmap

    for name in ("app-icon.png", "splash-screen.png", "logo-horizontal.png"):
        pix = QPixmap(str(RES / name))
        assert not pix.isNull(), f"{name} 解码失败"
        assert pix.width() > 0


def test_package_data_declares_resources() -> None:
    """pyproject 必须把 resources 与 CIF 声明为包数据（否则打包丢文件）。"""
    text = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    assert "resources/*" in text
    assert "data/cif/*.cif" in text
    assert "i18n" in text or "data/*.json" in text


# --------------------------------------------------------------------------- #
# 资源路径解析
# --------------------------------------------------------------------------- #
def test_resource_path_dev_mode() -> None:
    """开发态：返回包内 resources 下的路径。"""
    from ncm.gui.resources import resource_path

    p = resource_path("app-icon.png")
    assert p.exists()
    assert p.parent.name == "resources"


def test_resource_path_frozen_mode(monkeypatch, tmp_path) -> None:
    """★打包态：资源在 `_MEIPASS/ncm/resources/`（不是 `_MEIPASS/` 根）。"""
    import sys

    from ncm.gui import resources

    fake = tmp_path / "MEIPASS"
    (fake / "ncm" / "resources").mkdir(parents=True)
    (fake / "ncm" / "resources" / "app-icon.png").write_bytes(b"x")
    monkeypatch.setattr(sys, "_MEIPASS", str(fake), raising=False)
    p = resources.resource_path("app-icon.png")
    assert p.exists()
    assert "ncm" in p.parts


def test_app_icon_prefers_png() -> None:
    """图标优先 PNG（不加载 qico 插件 —— 家族实测会提高启动崩溃率）。"""
    from ncm.gui.resources import app_icon_path

    p = app_icon_path()
    assert p.endswith("app-icon.png")


def test_splash_path_returns_existing() -> None:
    from ncm.gui.resources import splash_path

    p = splash_path()
    assert p and Path(p).exists()


def test_logo_path_returns_existing() -> None:
    from ncm.gui.resources import logo_path

    p = logo_path()
    assert p and Path(p).exists()


# --------------------------------------------------------------------------- #
# 关于对话框
# --------------------------------------------------------------------------- #
def test_about_dialog_has_logo_version_contact(qapp) -> None:
    """关于对话框要有 logo、版本号、联系方式。"""
    from PySide6.QtWidgets import QLabel

    from ncm.gui.dialogs import AboutDialog
    from ncm.version import APP_CONTACT_EMAIL, __version__

    dlg = AboutDialog()
    texts = "\n".join(lbl.text() for lbl in dlg.findChildren(QLabel))
    assert __version__ in texts
    assert APP_CONTACT_EMAIL in texts
    assert "PolyXRD" in texts


def test_about_dialog_degrades_without_logo(qapp, monkeypatch) -> None:
    """logo 缺失时要能降级成纯文本（不能崩）。"""
    from ncm.gui import dialogs

    monkeypatch.setattr(dialogs, "logo_path", lambda: "")
    dlg = dialogs.AboutDialog()
    assert dlg is not None


def test_copyright_is_bilingual(qapp) -> None:
    """版权正文恒中英双语并列（不随界面语言切换）。"""
    from ncm.gui.dialogs import COPYRIGHT_BODY_EN, COPYRIGHT_BODY_ZH

    assert "PolyXRD Team" in COPYRIGHT_BODY_ZH
    assert "PolyXRD Team" in COPYRIGHT_BODY_EN
    assert "学术许可" in COPYRIGHT_BODY_ZH
    assert "Academic License" in COPYRIGHT_BODY_EN


# --------------------------------------------------------------------------- #
# 打包配置
# --------------------------------------------------------------------------- #
def test_pyinstaller_spec_exists() -> None:
    spec = REPO / "PolyXRD-NCM.spec"
    assert spec.exists()
    text = spec.read_text(encoding="utf-8")
    # 整目录带 ncm/data：含 spacegroups.json（缺它晶系/点群/空间群/劳厄群全空）、
    # cif/ 与 cif/impurity/ —— 比逐个列子目录更难漏。
    assert "ncm/data" in text, "数据资源未列入随包资源"
    assert "spacegroups" in text, "空间群表未随包"
    assert "ncm/i18n" in text, "翻译表未列入随包资源"
    assert "ncm/resources" in text, "品牌资源未列入随包资源"
    assert "console=False" in text, "应是无控制台程序"
    assert "app-icon.ico" in text
    assert "Splash(" in text, "onefile 解压期应有 bootloader 启动图"


def test_build_script_exists() -> None:
    """构建链按家族口径拆成三步，但「打包后必须冒烟」的判据不变。

    `build.bat` 只负责串联（`build_exe.bat` → `build_setup.bat`），
    PyInstaller 调用与冒烟都在 `build_exe.bat` 里。
    """
    chain = REPO / "build.bat"
    assert chain.exists()
    text = chain.read_text(encoding="utf-8")
    assert "build_exe.bat" in text, "一键构建应串联 exe 打包"
    assert "build_setup.bat" in text, "一键构建应串联安装包"

    exe_bat = REPO / "build_exe.bat"
    assert exe_bat.exists()
    exe_text = exe_bat.read_text(encoding="utf-8")
    assert "PyInstaller" in exe_text
    assert "--smoke" in exe_text, "打包后应冒烟"
