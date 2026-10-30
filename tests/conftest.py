"""pytest 公共 fixture —— 数据根、实样路径与 Qt 离屏环境（T0.1 / T6.1b）。

约定：
- DATA_ROOT 指向家族只读数据根 D:/Project/XRD（COD 源、实样谱）。
- 只读引用，测试不写回数据根。
- GUI 测试跑在 **Qt 离屏平台**（offscreen）上，不弹窗、不抢焦点。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# 让 tests/ 直接 import ncm（无需安装包）
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA_ROOT = Path("D:/Project/XRD")
SAMPLE_811 = DATA_ROOT / "XRData/csuHJW/txt/Data040：NCM：811_raw.txt"
CIF_DIR = ROOT / "ncm" / "data" / "cif"


@pytest.fixture(scope="session")
def data_root() -> Path:
    """家族只读数据根。"""
    return DATA_ROOT


@pytest.fixture(scope="session")
def sample_811() -> Path:
    """真实 NCM811 实样谱（岛津导出两列文本）。"""
    if not SAMPLE_811.exists():
        pytest.skip(f"实样缺失: {SAMPLE_811}")
    return SAMPLE_811


@pytest.fixture(scope="session")
def cif_dir() -> Path:
    """内置 CIF 目录。"""
    return CIF_DIR


# --------------------------------------------------------------------------- #
# Qt 离屏环境（T6.1b）
# --------------------------------------------------------------------------- #

#: 离屏平台名（必须在 QApplication 创建**之前**设入环境变量才生效）
QT_PLATFORM = "offscreen"


@pytest.fixture(scope="session")
def qapp():
    """会话级 QApplication（离屏）。

    QApplication 整个进程只能有一个，重复创建会崩；故用 session 作用域。
    平台强制 offscreen，测试机上没有显示服务器也能跑。
    """
    os.environ.setdefault("QT_QPA_PLATFORM", QT_PLATFORM)
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app
