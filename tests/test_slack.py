import httpx
import pytest

from slack_relay.slack import SlackClient, SlackError

from .conftest import SLACK_URL, FakeSlack


def client(fake: FakeSlack, sleeps: list[float], **kw) -> SlackClient:
    return SlackClient(SLACK_URL, transport=httpx.MockTransport(fake), sleep=sleeps.append, **kw)


def test_success_first_try():
    fake, sleeps = FakeSlack(), []
    assert client(fake, sleeps).post({"text": "hi"}) == 1
    assert fake.messages == [{"text": "hi"}]
    assert sleeps == []


def test_honours_retry_after_on_429():
    fake = FakeSlack(httpx.Response(429, headers={"Retry-After": "3"}, text="rate_limited"))
    sleeps: list[float] = []
    assert client(fake, sleeps).post({"text": "hi"}) == 2
    assert sleeps == [3.0]


def test_backs_off_on_5xx_and_network_errors():
    fake = FakeSlack(
        httpx.Response(503),
        httpx.ConnectError("boom"),
        httpx.Response(500),
    )
    sleeps: list[float] = []
    assert client(fake, sleeps, base_delay=1).post({"text": "hi"}) == 4
    assert sleeps == [1, 2, 4]


def test_gives_up_after_max_attempts():
    fake = FakeSlack(*[httpx.Response(500, text="oops")] * 5)
    with pytest.raises(SlackError) as err:
        client(fake, [], max_attempts=3).post({"text": "hi"})
    assert err.value.attempts == 3
    assert "HTTP 500" in str(err.value)


def test_does_not_retry_permanent_4xx():
    fake = FakeSlack(httpx.Response(404, text="no_service"))
    with pytest.raises(SlackError) as err:
        client(fake, []).post({"text": "hi"})
    assert err.value.attempts == 1
    assert len(fake.requests) == 1
