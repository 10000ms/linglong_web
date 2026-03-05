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
