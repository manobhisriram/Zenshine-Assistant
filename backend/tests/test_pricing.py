import pytest

from app.services.pricing import calculate_quote
from app.services.tenants import load_registry

T = load_registry("tenants").get("zenshine")


def q(items, **kw):
    return calculate_quote(T, [{"service_id": i, "quantity": n} for i, n in items], **kw)


def test_two_services_first_time():
    r = q([("house_cleaning", 1), ("kitchen", 1)], first_time_customer=True)
    assert r.total == 2780  # 3200 - 10% - 100


def test_three_services_get_20_percent():
    r = q([("house_cleaning", 1), ("kitchen", 1), ("bathroom", 1)], first_time_customer=True)
    assert r.total == 2860  # 3700 - 20% - 100


def test_bathroom_quantity():
    r = q([("bathroom", 3)])
    assert r.subtotal == 1500 and r.total == 1500


def test_free_door_window_with_house_cleaning():
    r = q([("house_cleaning", 1), ("door_window", 1)])
    assert r.total == 2000 and r.complimentary


def test_monthly_contract_does_not_stack_with_combo():
    r = q([("house_cleaning", 1), ("kitchen", 1)], monthly_contract=True)
    assert r.percent_applied == 15 and r.total == 2720


def test_custom_quote_excluded_from_total():
    r = q([("house_cleaning", 1), ("office", 1)])
    assert r.total == 2000 and r.custom_quote_items


def test_unknown_service_rejected():
    with pytest.raises(ValueError):
        q([("teleport", 1)])


def test_quantity_bounds():
    with pytest.raises(ValueError):
        q([("bathroom", 0 + 51)])


def test_discount_never_negative():
    r = q([("door_window", 1)], first_time_customer=True, referral=True)
    assert r.total >= 0
