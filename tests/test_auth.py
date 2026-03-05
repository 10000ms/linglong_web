import pytest

from linglong_web import login_required
from linglong_web import LoginRequiredError
from linglong_web.utils import set_context_user_id


@pytest.mark.asyncio
async def test_login_required_allows_authenticated_user():
    set_context_user_id(1001)

    @login_required
    async def secured_handler():
        return "ok"

    assert await secured_handler() == "ok"
    set_context_user_id(None)


@pytest.mark.asyncio
async def test_login_required_raises_for_anonymous():
    set_context_user_id(None)

    @login_required
    async def secured_handler():
        return "should not run"

    with pytest.raises(LoginRequiredError):
        await secured_handler()
