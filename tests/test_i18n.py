"""多语言底座测试（T6.1a 验收）。

核心判据：**三语 key 集合必须完全一致** —— 任一语言漏一个 key，切换到该
语言时界面上就会出现 `⟪missing.key⟫`，这正是 T6.4「三语切换无 KeyError」
的提前拦截。
"""
from __future__ import annotations

import pytest

from ncm.i18n import (
    available_languages,
    current_language,
    load_language,
    save_language,
    set_language,
    tr,
)
from ncm.i18n.i18n_manager import CONFIG_PATH, TABLE

LANGS = ("zh_CN", "en_US", "ja_JP")


@pytest.fixture(autouse=True)
def _restore_language():
    """每个用例后恢复默认语言，避免用例间互相污染。"""
    prev = current_language()
    yield
    set_language(prev)


def test_language_table_has_three_languages() -> None:
    assert set(TABLE) == set(LANGS)
    assert set(available_languages()) == set(LANGS)
    assert available_languages()["zh_CN"] == "简体中文"


def test_all_languages_share_identical_key_set() -> None:
    """★三语 key 集合完全一致（缺一个都会在界面上暴露成 ⟪key⟫）。"""
    sets = {lang: set(TABLE[lang]) for lang in LANGS}
    ref = sets["zh_CN"]
    assert ref, "翻译表为空"
    for lang in LANGS[1:]:
        missing = ref - sets[lang]
        extra = sets[lang] - ref
        assert not missing, f"{lang} 缺少 key: {sorted(missing)}"
        assert not extra, f"{lang} 多出 key: {sorted(extra)}"


def test_no_empty_translation() -> None:
    for lang in LANGS:
        empty = [k for k, v in TABLE[lang].items() if not str(v).strip()]
        assert not empty, f"{lang} 存在空文案: {empty}"


def test_tr_returns_marker_for_missing_key() -> None:
    set_language("zh_CN")
    assert tr("definitely.missing.key") == "⟪definitely.missing.key⟫"


def test_tr_formats_kwargs() -> None:
    set_language("zh_CN")
    out = tr("status.file", path="D:/x/sample.xy")
    assert "D:/x/sample.xy" in out
    assert "{path}" not in out


def test_set_language_switches_and_ignores_unknown() -> None:
    set_language("en_US")
    assert current_language() == "en_US"
    assert tr("status.ready") == "Ready"
    set_language("ja_JP")
    assert tr("status.ready") == "準備完了"
    set_language("xx_XX")           # 未知代码应被忽略
    assert current_language() == "ja_JP"


def test_save_and_load_roundtrip(tmp_path, monkeypatch) -> None:
    cfg = tmp_path / "config.json"
    monkeypatch.setattr("ncm.i18n.i18n_manager.CONFIG_PATH", cfg)
    set_language("ja_JP")
    save_language()
    assert cfg.exists()
    set_language("zh_CN")
    load_language()
    assert current_language() == "ja_JP"


def test_load_language_tolerates_broken_file(tmp_path, monkeypatch) -> None:
    cfg = tmp_path / "config.json"
    cfg.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr("ncm.i18n.i18n_manager.CONFIG_PATH", cfg)
    set_language("zh_CN")
    load_language()
    assert current_language() == "zh_CN"


def test_config_path_is_ncm_specific() -> None:
    """持久化目录必须是 .ncm，不能与家族其它工具（.rutana）串味。"""
    assert CONFIG_PATH.parent.name == ".ncm"
