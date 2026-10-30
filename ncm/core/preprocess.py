"""谱图预处理门面（T1.1）。

把 vendor 来的 `smooth` / `background` / `kalpha2` 三件事统一成一条可配置的处理链，
供 GUI 工具条与 CLI 共用。**不新增算法**，只做调度与顺序约束。

处理顺序（物理上有讲究，不可随意调换）
--------------------------------------
1. **去 Kα2**：必须在扣背景之前。Rachinger 剥离靠的是「Kα2 峰 = Kα1 峰右移 Δ2θ、
   强度比 r」的逐点递推，落在**原始计数**上才有意义；若先扣背景，递推会把
   背景模型误差一起放大成负值。
2. **扣背景**：在去 Kα2 之后。此时谱线只剩 Kα1 分量，边缘取点更干净。
3. **平滑**：放最后。平滑会改变峰宽与峰高，早做会让 Rachinger 递推失真。

精修（Rietveld）**不吃**预处理后的谱 —— 它自己把背景当线性参数拟合。预处理
结果只用于：寻峰、单峰拟合、判定门指纹、以及界面上给人看。这一点写死在
`for_refinement()` 里，避免有人误把平滑谱喂给精修。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ncm.core.background import BgConfig, BG_MODES, estimate_background
from ncm.core.dtypes import Pattern
from ncm.core.kalpha2 import KAlpha2Config, strip_kalpha2
from ncm.core.smooth import SmoothConfig, savitzky_golay


@dataclass(frozen=True)
class PreprocessConfig:
    """一条预处理链的开关集合。默认全关 = 原样直通。"""

    smooth_window: int = 0          # 0 = 不平滑；≥5 的奇数生效
    smooth_poly: int = 2
    bg_mode: str | None = None      # None = 不扣背景
    bg_edge_frac: float = 0.10
    bg_poly_deg: int = 1
    ka2: bool = False
    ka2_ratio: float = 0.5
    anode: str = "Cu"

    def validate(self) -> None:
        if self.bg_mode is not None and self.bg_mode not in BG_MODES:
            raise ValueError(f"未知背景模式: {self.bg_mode}（可用: {BG_MODES}）")
        if self.smooth_window and self.smooth_window % 2 == 0:
            raise ValueError(f"平滑窗口必须为奇数: {self.smooth_window}")
        if not 0.0 < self.ka2_ratio <= 1.0:
            raise ValueError(f"Kα2/Kα1 强度比越界: {self.ka2_ratio}")


@dataclass(frozen=True)
class PreprocessResult:
    """处理链结果。`pattern` 是最终谱，`steps` 记录每一步的中间产物。"""

    pattern: Pattern
    steps: list[tuple[str, Pattern]] = field(default_factory=list)
    background: np.ndarray | None = None
    notes: list[str] = field(default_factory=list)

    def summary(self) -> str:
        """一行摘要（写日志 / 报告头用）。"""
        names = [n for n, _ in self.steps] or ["原样"]
        head = f"{self.pattern.two_theta.size} 点 {self.pattern.two_theta[0]:.2f}–" \
               f"{self.pattern.two_theta[-1]:.2f}°"
        return f"{head} | 处理: {' → '.join(names)}"


def smooth(p: Pattern, *, window: int, polyorder: int = 2) -> Pattern:
    """Savitzky–Golay 平滑（window=0 时直通）。"""
    cfg = SmoothConfig(enabled=window > 0, window=max(window, 5),
                       polyorder=polyorder)
    y = savitzky_golay(p.intensity, cfg)
    return Pattern(two_theta=p.two_theta.copy(), intensity=y,
                   meta={**p.meta, "smooth_window": window, "smooth_poly": polyorder})


def strip_background(p: Pattern, *, mode: str = "linear_edges",
                     edge_frac: float = 0.10, poly_deg: int = 1
                     ) -> tuple[Pattern, np.ndarray]:
    """扣背景。返回（净谱, 背景曲线）。

    净谱不做负值裁剪 —— 负值对判定门"弱峰是否存在"仍有信息量，
    真要看峰时由调用方自行 clip。
    """
    if mode not in BG_MODES:
        raise ValueError(f"未知背景模式: {mode}（可用: {BG_MODES}）")
    bg = estimate_background(p, BgConfig(mode=mode, edge_frac=edge_frac,
                                         poly_deg=poly_deg))
    net = Pattern(two_theta=p.two_theta.copy(),
                  intensity=p.intensity - bg,
                  meta={**p.meta, "bg_mode": mode})
    return net, bg


def strip_ka2(p: Pattern, *, anode: str = "Cu", ratio: float = 0.5,
              iters: int = 8) -> Pattern:
    """Rachinger Kα2 剥离。"""
    cfg = KAlpha2Config(enabled=True, ratio=ratio, anode=anode, iters=iters)
    return strip_kalpha2(p, cfg)


def apply(p: Pattern, cfg: PreprocessConfig) -> PreprocessResult:
    """按 `去Kα2 → 扣背景 → 平滑` 的顺序执行整条链。"""
    cfg.validate()
    steps: list[tuple[str, Pattern]] = []
    notes: list[str] = []
    cur = p
    bg: np.ndarray | None = None

    if cfg.ka2:
        cur = strip_ka2(cur, anode=cfg.anode, ratio=cfg.ka2_ratio)
        steps.append(("去Kα2", cur))
        notes.append(f"Rachinger 剥离，Iα2/Iα1={cfg.ka2_ratio}，靶材 {cfg.anode}")

    if cfg.bg_mode is not None:
        cur, bg = strip_background(cur, mode=cfg.bg_mode,
                                   edge_frac=cfg.bg_edge_frac,
                                   poly_deg=cfg.bg_poly_deg)
        steps.append(("扣背景", cur))
        notes.append(f"背景模式 {cfg.bg_mode}，边缘取点 {cfg.bg_edge_frac:.0%}")

    if cfg.smooth_window:
        cur = smooth(cur, window=cfg.smooth_window, polyorder=cfg.smooth_poly)
        steps.append(("平滑", cur))
        notes.append(f"SG 平滑 window={cfg.smooth_window} poly={cfg.smooth_poly}")

    return PreprocessResult(pattern=cur, steps=steps, background=bg, notes=notes)


def for_refinement(p: Pattern) -> Pattern:
    """返回**喂给精修**的谱 —— 永远是原始谱。

    存在这个函数本身就是为了让人看见：精修不走预处理链。
    Rietveld 把背景当线性参数一起最小化，平滑会破坏残差的统计性质
    （相邻点不再独立），去 Kα2 会丢掉双线信息导致峰形模型失配。
    """
    return Pattern(two_theta=p.two_theta.copy(), intensity=p.intensity.copy(),
                   meta=dict(p.meta))
