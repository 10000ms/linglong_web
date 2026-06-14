from linglong_web import (
    LinglongConfig,
    LinglongConfigBase,
    init_config,
)
import threading


class _TestConfig(LinglongConfigBase):
    DEBUG = True
    SERVICE_NAME = "linglong-test"
    SAMPLE_VALUE = "demo"


def setup_module(module):  # noqa: D401 - pytest hook
    init_config({"dev": _TestConfig}, mode_name="dev")
    LinglongConfig.reset()


def test_config_proxy_attribute_updates():
    LinglongConfig.reset()
    LinglongConfig.CUSTOM_KEY = 42
    assert LinglongConfig.CUSTOM_KEY == 42

    LinglongConfig.apply_updates({"ANOTHER_KEY": "ok"})
    snapshot = LinglongConfig.snapshot()
    assert snapshot["ANOTHER_KEY"] == "ok"

    LinglongConfig.load_from_dict({"BATCH_KEY": 11})
    assert LinglongConfig.BATCH_KEY == 11

    LinglongConfig.reset()
    assert LinglongConfig.CUSTOM_KEY == 42


def test_config_apply_updates_is_observed_atomically_under_concurrency():
    """并发读场景下，批量配置更新不应暴露中间态。
    Batched config updates should not expose mixed intermediate snapshots.
    """

    LinglongConfig.reset()
    LinglongConfig.apply_updates({"PAIR_A": 1, "PAIR_B": 1})

    stop = threading.Event()
    mixed_seen = []

    def _reader():
        while not stop.is_set():
            snap = LinglongConfig.snapshot()
            pair = (snap.get("PAIR_A"), snap.get("PAIR_B"))
            if pair not in {(1, 1), (2, 2)}:
                mixed_seen.append(pair)
                stop.set()

    reader_thread = threading.Thread(target=_reader, daemon=True)
    reader_thread.start()
    try:
        for _ in range(500):
            LinglongConfig.apply_updates({"PAIR_A": 2, "PAIR_B": 2})
            LinglongConfig.apply_updates({"PAIR_A": 1, "PAIR_B": 1})
    finally:
        stop.set()
        reader_thread.join(timeout=1.0)

    assert not mixed_seen


def test_config_get_with_default():
    """LinglongConfig.get(key, default) — dict 风格读取，缺失返回默认值，不抛异常。"""
    LinglongConfig.reset()
    # 存在的键返回其值 / existing key returns its value
    assert LinglongConfig.get("SAMPLE_VALUE", "fallback") == "demo"
    # 缺失键返回默认值（关键：不再抛 AttributeError）/ missing key returns default
    assert LinglongConfig.get("DOES_NOT_EXIST", "fallback") == "fallback"
    # 无默认值时返回 None / no default -> None
    assert LinglongConfig.get("DOES_NOT_EXIST") is None
