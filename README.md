# PolyXRD NCM

**三元锂电正极材料（NCM）XRD 粉末衍射精修专用工具。**

PolyXRD 家族成员：[PolyXRD](https://github.com/PolyXRD)（数据分析）·
PolyXRD-Converter（格式转换）· PolyXRD-SynthPattern（谱图合成）·
PolyXRD-RutAna（TiO₂ 晶型比）· PolyXRD-Graphite（石墨化度）· **NCM（本项目）**

## 这是什么

打开即一个界面：左侧谱图（读谱 + 平滑/扣背景/去 Kα2/寻峰/单峰拟合），右侧内置
层状 NCM 三元正极材料的 COD CIF（811 / 622 / 523 / 111 及前驱体）。导入 XRD 数据后
先做「是不是层状 NCM」判定——不是则弹窗停止；是则以 CIF 为起点做全谱 Rietveld 精修，
输出晶胞参数、晶粒尺寸、晶系/点群/空间群/劳厄群、Li 占位与 Rwp/RB/GOF，支持导出。

> 状态：**v0.1.0 开发中**（P0 立项阶段）。功能清单见 `docs/PROJECT_PLAN.md`，
> 任务进度见 `docs/TASKS.md`。

## 文档

| 文档 | 内容 |
|---|---|
| `docs/PROJECT_PLAN.md` | 方案、可行性实测、8 阶段路线图 |
| `docs/TASKS.md` | 原子任务卡与验收命令 |
| `docs/CIF_SOURCE.md` | 内置 CIF 的 COD 来源登记 |
| `docs/STD_FREEZE.md` | 判据与口径冻结 |

## 跑测试

```bash
cd /d/Project/PolyXRD-Tools/PolyXRD-NCM
D:/Project/XRD/python310/python.exe -m pytest -q
```

## 许可

双许可（Academic / Commercial），见 `LICENSE` 与 `LICENSE-CN`。
商用联系：sshztx@outlook.com · https://github.com/PolyXRD
