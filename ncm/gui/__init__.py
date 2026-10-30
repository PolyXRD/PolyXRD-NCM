"""PolyXRD-NCM GUI 包。

**导入约束**：本包内的模块都依赖 PySide6 / matplotlib-qt，**不能在包级
import** —— 否则连 `python -m ncm.cli.ncm` 这类纯命令行入口都会被迫拉起
GUI 依赖。具体模块（如 `ncm.gui.canvas` / `ncm.gui.main_window`）由调用方
显式导入。
"""
