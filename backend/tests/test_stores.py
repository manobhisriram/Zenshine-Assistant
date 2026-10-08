import boto3
import fakeredis.aioredis
import pytest
from moto import mock_aws

from app.core.errors import RateLimited
from app.core.ratelimit import RateLimiter, RedisCounter
from app.services.leads import DynamoLeadStore, LeadService, valid_phone
from app.services.memory import RedisSessionStore
from tests.conftest import make_settings


async def test_redis_sessions_trim_and_isolate():
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    s = RedisSessionStore(r, max_turns=2, ttl=60)
    for i in range(5):
        await s.append("t", "sess", [{"role": "user", "content": f"q{i}"}, {"role": "assistant", "content": f"a{i}"}])
    hist = await s.load("t", "sess")
    assert len(hist) == 4 and hist[-1]["content"] == "a4"
    assert await s.load("other", "sess") == []
    await s.clear("t", "sess")
    assert await s.load("t", "sess") == []
    assert await s.ping()


async def test_redis_rate_limiter():
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    rl = RateLimiter(RedisCounter(r))
    await rl.enforce("x", "id", 2, 60)
    await rl.enforce("x", "id", 2, 60)
    with pytest.raises(RateLimited) as e:
        await rl.enforce("x", "id", 2, 60)
    assert "Retry-After" in e.value.headers
    await rl.enforce("x", "other", 2, 60)


async def test_rate_limiter_fails_open_on_backend_error():
    class Broken:
        async def incr(self, key, window):
            raise ConnectionError

    assert (await RateLimiter(Broken()).hit("x", "id", 1, 60)).allowed


async def test_dynamodb_leads(tmp_path, monkeypatch):
    for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        monkeypatch.setenv(k, "testing")
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name="us-east-1")
        ddb.create_table(
            TableName="leads",
            BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=[
                {"AttributeName": "tenant", "AttributeType": "S"},
                {"AttributeName": "lead_id", "AttributeType": "S"},
            ],
            KeySchema=[{"AttributeName": "tenant", "KeyType": "HASH"}, {"AttributeName": "lead_id", "KeyType": "RANGE"}],
        )
        sns = boto3.client("sns", region_name="us-east-1")
        arn = sns.create_topic(Name="leads")["TopicArn"]
        s = make_settings(
            tmp_path, leads_backend="dynamodb", leads_dynamodb_table="leads", leads_sns_topic_arn=arn, aws_region="us-east-1"
        )
        svc = LeadService(DynamoLeadStore(s), s)
        lead_id = await svc.capture({"tenant": "zenshine", "name": "Asha", "phone": "+91 98765 11111", "interest": ""})
        items = ddb.scan(TableName="leads")["Items"]
        assert len(items) == 1 and items[0]["lead_id"]["S"] == lead_id and "expires_at" in items[0]
        assert "interest" not in items[0]  # empty values are not stored
        assert await svc.ping()


def test_phone_validation():
    assert valid_phone("+91 98765 43210") and valid_phone("044-2345-6789")
    assert not valid_phone("abc") and not valid_phone("12") and not valid_phone("+" + "9" * 20)
