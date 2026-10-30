"""仓库骨架自检（T0.1 验收）。"""
from __future__ import annotations


def test_version() -> None:
    from ncm.version import APP_NAME, __version__

    assert __version__ == "0.1.0"
    assert APP_NAME == "PolyXRD NCM"


def test_package_importable() -> None:
    import ncm
    import ncm.core

    assert ncm is not None and ncm.core is not None
