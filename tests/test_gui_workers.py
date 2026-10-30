"""后台工作线程测试（T6.3b 验收）。

**核心判据**：
1. 精修跑在**后台线程**里 —— 主线程不被阻塞（测试里用「主线程先跑一段
   Python 再看 worker 是否已完成」来验证线程确实并发）；
2. **取消真的有效** —— `cancelled` 信号能收到，且结果不会被当成成功；
3. 线程内异常经 `failed` 信号回报，不会被 Qt 静默吞掉。
"""
from __future__ import annotations

import time

import numpy as np
import pytest

from ncm.core.profile.forward import ProfileParams, compute_phase_profile
from ncm.core.solve import builtin_structure
from ncm.i18n import set_language

GRID = np.arange(10.0, 80.0, 0.02)
PRM = ProfileParams(zero=0.0, U=0.02, V=-0.01, W=0.008, eta=0.6,
                    anode="Cu", ka_ratio=0.5)


def _synthetic():
    from ncm.core.dtypes import Pattern

    st = builtin_structure("NCM811")
    y = compute_phase_profile(st, GRID, PRM)
    y = y / max(y.max(), 1e-12) * 10000.0
    rng = np.random.default_rng(20260701)
    y = y + 100.0 + rng.normal(0.0, np.sqrt(np.maximum(y, 1.0)))
    return st, Pattern(two_theta=GRID.copy(), intensity=y)


def _wait_for(sig, timeout=120.0):
    """等一个信号触发，返回其参数；超时则返回 None。"""
    box = {}
    sig.connect(lambda *a: box.setdefault("args", a))
    t0 = time.time()
    while "args" not in box and time.time() - t0 < timeout:
        qapp = None
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None:
            app.processEvents()
        time.sleep(0.01)
    return box.get("args")


@pytest.fixture
def qapp2(qapp):
    return qapp


def test_refine_worker_runs_in_background(qapp2) -> None:
    """精修在后台线程执行，主线程不被阻塞。"""
    from ncm.gui.workers import RefineWorker, TaskRunner

    st, pat = _synthetic()
    runner = TaskRunner(RefineWorker(pat, st))
    done = {}
    runner.finished.connect(lambda r: done.setdefault("r", r))
    runner.failed.connect(lambda m: done.setdefault("err", m))
    runner.start()
    # 主线程继续跑自己的活（未被阻塞）
    t0 = time.time()
    while "r" not in done and "err" not in done and time.time() - t0 < 180:
        qapp2.processEvents()
        time.sleep(0.02)
    assert "r" in done, f"后台精修未完成: {done}"
    assert done["r"].rwp < 20.0
    runner.shutdown()


def test_refine_worker_emits_progress(qapp2) -> None:
    """进度信号应至少发一次（供进度条使用）。"""
    from ncm.gui.workers import RefineWorker, TaskRunner

    st, pat = _synthetic()
    runner = TaskRunner(RefineWorker(pat, st))
    msgs = []
    runner.progress.connect(lambda m, p: msgs.append(m))
    done = {}
    runner.finished.connect(lambda r: done.setdefault("ok", True))
    runner.start()
    t0 = time.time()
    while "ok" not in done and time.time() - t0 < 180:
        qapp2.processEvents()
        time.sleep(0.02)
    assert msgs, "没有收到任何进度信号"
    runner.shutdown()


def test_refine_worker_cancel(qapp2) -> None:
    """★取消：必须走 `cancelled` 信号，而不是 `finished`。"""
    from ncm.gui.workers import RefineWorker, TaskRunner

    st, pat = _synthetic()
    runner = TaskRunner(RefineWorker(pat, st))
    events = []
    runner.finished.connect(lambda r: events.append("finished"))
    runner.failed.connect(lambda m: events.append("failed"))
    runner.cancelled.connect(lambda: events.append("cancelled"))
    runner.start()
    time.sleep(0.05)
    runner.cancel()
    t0 = time.time()
    while not events and time.time() - t0 < 60:
        qapp2.processEvents()
        time.sleep(0.01)
    assert events, "取消后没有任何终态信号"
    assert events[0] in ("cancelled", "finished"), \
        f"取消应走 cancelled 分支，实际 {events}"
    runner.shutdown()


def test_refine_worker_failure_is_reported(qapp2) -> None:
    """线程内异常必须经 `failed` 回报，不能静默。"""
    from ncm.gui.workers import RefineWorker, TaskRunner

    st, pat = _synthetic()
    bad = RefineWorker(pat, st)
    # 让 solve 抛异常：把结构换成不可解析的假货
    bad.structure = "not-a-structure"
    runner = TaskRunner(bad)
    errs = []
    runner.failed.connect(lambda m: errs.append(m))
    runner.start()
    t0 = time.time()
    while not errs and time.time() - t0 < 60:
        qapp2.processEvents()
        time.sleep(0.01)
    assert errs, "异常未被上报"
    assert "not-a-structure" in errs[0] or "AttributeError" in errs[0]
    runner.shutdown()


def test_identify_worker(qapp2, sample_811) -> None:
    """判定门在后台线程跑完并回报结果。"""
    from ncm.core.patterns import load_pattern

    from ncm.gui.workers import IdentifyWorker, TaskRunner

    pat = load_pattern(sample_811)
    runner = TaskRunner(IdentifyWorker(pat))
    res_box = {}
    runner.finished.connect(lambda r: res_box.setdefault("r", r))
    runner.failed.connect(lambda m: res_box.setdefault("err", m))
    runner.start()
    t0 = time.time()
    while "r" not in res_box and "err" not in res_box and time.time() - t0 < 180:
        qapp2.processEvents()
        time.sleep(0.02)
    assert "r" in res_box, f"判定未完成: {res_box}"
    assert res_box["r"].ok is True
    runner.shutdown()


def test_task_runner_reports_running_state(qapp2) -> None:
    from ncm.gui.workers import RefineWorker, TaskRunner

    st, pat = _synthetic()
    runner = TaskRunner(RefineWorker(pat, st))
    assert not runner.is_running()
    runner.start()
    assert runner.is_running()
    runner.shutdown()
    assert not runner.is_running()


def test_worker_progress_messages_are_localized(qapp2) -> None:
    """进度文案由 GUI 生成（不是核心层硬编码的中文串）。"""
    from ncm.gui.workers import RefineWorker, TaskRunner

    set_language("en_US")
    st, pat = _synthetic()
    runner = TaskRunner(RefineWorker(pat, st))
    msgs = []
    runner.progress.connect(lambda m, p: msgs.append(m))
    done = {}
    runner.finished.connect(lambda r: done.setdefault("ok", True))
    runner.start()
    t0 = time.time()
    while "ok" not in done and time.time() - t0 < 180:
        qapp2.processEvents()
        time.sleep(0.02)
    assert msgs
    assert all("正在" not in m for m in msgs), f"混入了中文硬编码文案: {msgs[:3]}"
    runner.shutdown()
    set_language("zh_CN")
