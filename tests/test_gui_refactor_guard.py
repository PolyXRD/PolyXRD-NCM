"""T6.4e 重构守护测试。

锁住两条硬约束，防止后续迭代又把主窗口撑大：

1. **单文件 ≤ 400 行**（TASKS.md 规则 2）—— 超过就要拆卡；
2. **主窗口只做界面** —— 流程状态机在 `flow.py`、菜单在 `menubar.py`、
   对话框在 `dialogs.py`、状态栏在 `statusbar.py`。

这些是**结构性**约束，靠人 review 守不住，必须有测试。
"""
from __future__ import annotations

from pathlib import Path

GUI_DIR = Path(__file__).resolve().parents[1] / "ncm" / "gui"

#: TASKS.md 规则 2 的单文件行数上限
MAX_FILE_LINES = 400


def _lines(name: str) -> int:
    """统计源文件行数（忽略空行与纯注释行，只看实体代码）。"""
    text = (GUI_DIR / name).read_text(encoding="utf-8")
    return len(text.splitlines())


def test_main_window_within_line_limit() -> None:
    """★主窗口不得超过 400 行（T6.4e 拆分目标）。"""
    n = _lines("main_window.py")
    assert n <= MAX_FILE_LINES, (
        f"main_window.py 涨到 {n} 行，超 {MAX_FILE_LINES} 行上限 —— "
        f"请拆卡（参考 T6.4e：菜单→menubar.py、状态栏→statusbar.py、"
        f"流程→flow.py、对话框→dialogs.py）")


def test_gui_modules_within_line_limit() -> None:
    """GUI 目录下所有模块都不得超过 400 行。"""
    over = []
    for p in sorted(GUI_DIR.glob("*.py")):
        n = len(p.read_text(encoding="utf-8").splitlines())
        if n > MAX_FILE_LINES:
            over.append(f"{p.name}={n}")
    assert not over, "超行数上限的模块: " + ", ".join(over)


def test_main_window_delegates_to_extracted_modules() -> None:
    """主窗口应通过抽取出的模块装配菜单/状态栏，而不是自己从头搭。"""
    src = (GUI_DIR / "main_window.py").read_text(encoding="utf-8")
    assert "MenuBuilder(" in src, "菜单未走 menubar.MenuBuilder"
    assert "StatusBar(" in src, "状态栏未走 statusbar.StatusBar"
    assert "RefineFlow(" in src, "流程未走 flow.RefineFlow"
    assert "dialogs.show_message" in src, "消息框未走 dialogs 模块"


def test_extracted_modules_own_their_logic() -> None:
    """抽取出的模块应真正承载逻辑，而不是空壳转发。"""
    menubar = (GUI_DIR / "menubar.py").read_text(encoding="utf-8")
    assert "QAction(" in menubar and "addMenu(" in menubar
    statusbar = (GUI_DIR / "statusbar.py").read_text(encoding="utf-8")
    assert "QLabel(" in statusbar and "QPushButton(" in statusbar
    flow = (GUI_DIR / "flow.py").read_text(encoding="utf-8")
    assert "Signal(" in flow and "start_refine" in flow
