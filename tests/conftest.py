import sys
from pathlib import Path

import pytest

# 确保 linglong_web 包可被导入（tests 目录运行时，sys.path 默认不包含父目录）
# Ensure `linglong_web` package is importable when running tests from this folder.
_PACKAGE_ROOT = Path(__file__).resolve().parents[1]
_PACKAGE_PARENT = _PACKAGE_ROOT.parent
if str(_PACKAGE_PARENT) not in sys.path:
    sys.path.insert(0, str(_PACKAGE_PARENT))

from linglong_web.utils import (
    set_request_id,
    set_context_user_id,
)


@pytest.fixture(autouse=True)
def reset_request_context():
    """确保每个测试都有新的 request-id 和空用户上下文。"""

    set_request_id(None)
    set_context_user_id(None)
    yield
    set_context_user_id(None)
