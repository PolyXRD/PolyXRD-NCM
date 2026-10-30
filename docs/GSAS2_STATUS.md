# GSAS-II 状态与安装指引

> 对应任务卡：T0.4（安装与桥冒烟）、T8.3（交叉比对）
> 状态：**已解除 BLOCKED（2026-10-30，T8.3）** —— GSAS-II build 5844 已装在本机，
> 桥脚本可跑通 Le Bail + Rietveld。
>
> 影响范围：仅开发期交叉验证。**发布包不含 GSAS-II**，用户侧零影响。

---

## 1. 当年为什么判 BLOCKED（以及错在哪）

T0.4 的排查结论是「无任何可脚本化的官方安装渠道」，逐条依据是：

| 检查项 | 当时结果 |
|---|---|
| PyPI 包 `gsas2pkg` | 不存在 |
| GitHub `AdvancedPhotonSource/GSAS-II` releases | 无 release（API 404） |
| 官方 wiki `subversion.xray.aps.anl.gov/trac/pyGSAS` | HTTP 520 |
| 本机 conda / mamba | 均未安装 |

**错在哪**：官方发布不在 `GSAS-II` 仓库，而在 **`GSAS-II-buildtools`**：

- `https://github.com/AdvancedPhotonSource/GSAS-II-buildtools/releases/latest`
- 资产 `gsas2main-Latest-Windows-x86_64.exe`（约 **492 MB**，自带 Python 3.13.18
  与全部依赖，含编译扩展），另有 conda 包 `briantoby::gsas2pkg`。

## 2. 本机安装实况（2026-10-30）

| 项 | 值 |
|---|---|
| 安装包 | `gsas2main-Latest-Windows-x86_64.exe`（515 624 580 字节） |
| 安装器类型 | **NSIS**（文件头有 `NullsoftInst` 标记，不是 Inno Setup） |
| 静默安装 | `gsas2main.exe /S /D=D:\GSASII`（`/D=` 必须最后、不加引号） |
| 安装根 | `D:\GSASII` |
| 解释器 | `D:\GSASII\python.exe` → **Python 3.13.18** |
| 源码根 | `D:\GSASII\GSAS-II`（新版已把模块收进 `GSASII/` 包） |
| 编译扩展 | `D:\GSASII\GSAS-II\GSASII-bin\win_64_p3.13_n2.2` |
| 安装耗时 | 78 s（含 conda 解包 + gitstrap 首次更新） |

**新版 API 变化（build 5844）**：`from GSASII import GSASIIscriptable`，
不再是顶层的 `import GSASIIscriptable`。源码根须进 `sys.path`
（桥脚本用环境变量 `GSASII_ROOT` 接收）。

## 3. ★ 坑位：`0xC06D007F` 原生崩溃（不是装坏了）

现象：`G2Project.add_phase()` 让进程**直接消失**，exit code `0xC06D007F`
（= delay-load 找不到 DLL），无 traceback、stderr 全空。前半程
`add_powder_histogram()`、`GSASIIspc.SpcGroup('R -3 m')` 都正常，极具误导性。

**根因**：GSAS-II 的编译扩展依赖 `GSASII-bin\win_64_p*` 目录里的 DLL，
该目录必须**在子进程 PATH 上**；只在 `sys.path` 里不够。

**修法**（已落在 `tools/g2_env.py::g2_env()`）：

```python
env["PATH"] = ";".join([str(GSASII_bin_dir), str(gsas2_source), ...])
env["GSASII_ROOT"] = str(gsas2_source)
```

另有一个小坑：本机 enviroment 里 **PyCifRW 5.0.1 只装顶层 `CifFile` 模块**，
没有 `PyCifRW` 包；GSAS-II 里唯一的 CIF 引用是 `GSASIIobj.py` 的
`import CifFile as cif`，所以**不影响** CIF 读入（实测 `add_phase(cif)` 正常）。

## 4. 冒烟与交叉比对

```bash
# 只看环境（秒级，不需要 GSAS-II 也可跑）
python tools/g2_env.py

# 可用性冒烟：定位解释器 + 打印三个关键路径 +（--run）真跑一次
python tools/g2_smoke.py
python tools/g2_smoke.py --run

# 交叉比对：同一样品 + 同一 CIF，两套引擎各自精修 → 表格 + docs/evidence/*.json
python tools/g2_crosscheck.py            # 含本程序全谱精修（1–8 分钟）
python tools/g2_crosscheck.py --no-ours  # 只跑 GSAS-II（6 秒）
```

未安装时全部**退出码 0** 并打印 BLOCKED + 安装指引，不阻断 CI。

## 5. 交叉验证口径

| 项 | 要求 |
|---|---|
| 调用方式 | `scripts/gsas2_bridge.py`（家族 PolyXRD 提供的 JSON 子进程桥，本仓库直接复用不改） |
| 比对对象 | 同一样品 + 同一 CIF，两套引擎分别精修 |
| 验收判据 | 晶胞 a/c 相对偏差 ≤ 0.05%；**Rwp 差 ≤ 2 个百分点**（两套引擎背景/权重口径不同，不比绝对值） |
| 样本 | 真实 NCM811（`XRData/csuHJW/txt/Data040：NCM：811_raw.txt`）+ 合成 round-trip |
| Li 占位 / 晶粒尺寸 | 桥脚本能力边界之外 —— 改用独立来源比对（前驱体对 Maud 2.55 值，见 T8.2） |

## 6. 未安装时软件的行为（设计约定，不变）

| 场景 | 行为 |
|---|---|
| 开发期跑 `tools/g2_smoke.py` | 打印 BLOCKED + 安装指引，**退出码 0** |
| 交叉验证脚本 | 检测不到 GSAS-II 时**跳过**，报告里标注「未执行」 |
| 发布的 exe | **不含** GSAS-II 依赖与调用，用户侧零影响 |

**原则不变**：GSAS-II 只用于开发期「第二意见」，绝不是运行时依赖。
本软件的自研引擎必须能独立给出全部结果。
