"""Deterministic quote engine. Prices and discounts come from the tenant file, never from the model."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.services.tenants import Tenant


@dataclass(slots=True)
class QuoteLine:
    service_id: str
    name: str
    quantity: int
    unit_price: float
    line_total: float
    note: str = ""


@dataclass(slots=True)
class Quote:
    lines: list[QuoteLine] = field(default_factory=list)
    subtotal: float = 0.0
    combo_percent: float = 0.0
    contract_percent: float = 0.0
    percent_applied: float = 0.0
    percent_discount: float = 0.0
    flat_discounts: list[dict[str, Any]] = field(default_factory=list)
    total: float = 0.0
    custom_quote_items: list[str] = field(default_factory=list)
    site_visit_items: list[str] = field(default_factory=list)
    complimentary: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    summary: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "lines": [vars_of(line) for line in self.lines],
            "subtotal": self.subtotal,
            "percent_discount": {
                "percent": self.percent_applied,
                "amount": self.percent_discount,
                "combo_percent": self.combo_percent,
                "contract_percent": self.contract_percent,
            },
            "flat_discounts": self.flat_discounts,
            "total": self.total,
            "complimentary": self.complimentary,
            "custom_quote_items": self.custom_quote_items,
            "site_visit_items": self.site_visit_items,
            "warnings": self.warnings,
            "summary": self.summary,
        }


def vars_of(line: QuoteLine) -> dict[str, Any]:
    return {
        "service_id": line.service_id,
        "name": line.name,
        "quantity": line.quantity,
        "unit_price": line.unit_price,
        "line_total": line.line_total,
        "note": line.note,
    }


def _round(value: float, decimals: int) -> float:
    q = Decimal(1).scaleb(-decimals)
    return float(Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP))


def calculate_quote(
    tenant: Tenant,
    items: list[dict[str, Any]],
    *,
    first_time_customer: bool = False,
    monthly_contract: bool = False,
    referral: bool = False,
) -> Quote:
    """Compute a price breakdown.

    Rules (from the tenant file):
    - the combo tier is chosen by the number of distinct *paid* services;
    - a monthly contract percentage replaces the combo percentage when larger (they do not stack);
    - first-time and referral flat discounts stack on top of the percentage discount;
    - complimentary add-ons (e.g. door & window with a full house clean) cost nothing and do not count
      toward the tier; custom-quote and site-visit services are listed but excluded from the total.
    """
    d = tenant.currency.minor_unit_decimals
    quote = Quote()
    merged: dict[str, int] = {}
    for raw in items:
        sid = str(raw.get("service_id", ""))
        qty = int(raw.get("quantity", 1) or 1)
        if tenant.service(sid) is None:
            raise ValueError(f"Unknown service_id '{sid}'. Valid ids: {', '.join(s.id for s in tenant.services)}")
        if not 1 <= qty <= 50:
            raise ValueError("quantity must be between 1 and 50")
        merged[sid] = merged.get(sid, 0) + qty
    if not merged:
        raise ValueError("At least one service is required")

    free_ids = {rule.free for rule in tenant.discounts.free_with if rule.trigger in merged}

    paid_services = 0
    for sid, qty in merged.items():
        svc = tenant.service(sid)
        assert svc is not None
        if sid in free_ids:
            trigger = next(r.trigger for r in tenant.discounts.free_with if r.free == sid and r.trigger in merged)
            trigger_svc = tenant.service(trigger)
            quote.complimentary.append(f"{svc.name} (free with {trigger_svc.name if trigger_svc else trigger})")
            continue
        if svc.custom_quote:
            quote.custom_quote_items.append(svc.name)
            continue
        assert svc.price is not None
        if svc.requires_site_visit or svc.price_is_from:
            quote.site_visit_items.append(f"{svc.name} (from {tenant.money(svc.price)}; final price after site visit)")
            continue
        line_total = _round(svc.price * qty, d)
        quote.lines.append(QuoteLine(sid, svc.name, qty, svc.price, line_total, note=f"per {svc.unit}"))
        quote.subtotal += line_total
        paid_services += 1

    quote.subtotal = _round(quote.subtotal, d)

    combo = 0.0
    for tier in sorted(tenant.discounts.combo_tiers, key=lambda t: -t.min_services):
        if paid_services >= tier.min_services:
            combo = tier.percent
            break
    contract = tenant.discounts.monthly_contract_percent if monthly_contract else 0.0
    quote.combo_percent, quote.contract_percent = combo, contract
    quote.percent_applied = max(combo, contract)
    quote.percent_discount = _round(quote.subtotal * quote.percent_applied / 100, d)

    running = quote.subtotal - quote.percent_discount
    if first_time_customer and tenant.discounts.first_time_flat and quote.lines:
        amount = min(tenant.discounts.first_time_flat, running)
        quote.flat_discounts.append({"type": "first_time_customer", "amount": amount})
        running -= amount
    if referral and tenant.discounts.referral_flat and quote.lines:
        amount = min(tenant.discounts.referral_flat, running)
        quote.flat_discounts.append({"type": "referral", "amount": amount})
        running -= amount
    quote.total = _round(max(running, 0.0), d)

    if combo and contract and contract < combo:
        quote.warnings.append(
            "Combo discount is larger than the monthly-contract discount; the larger one applies (they do not stack)."
        )
    if quote.custom_quote_items or quote.site_visit_items:
        quote.warnings.append("Some items are not included in the total: custom quote or site visit is required.")

    quote.summary = _summary(tenant, quote)
    return quote


def _summary(tenant: Tenant, q: Quote) -> str:
    m = tenant.money
    parts = [
        f"{ln.name} x{ln.quantity} = {m(ln.line_total)}" if ln.quantity > 1 else f"{ln.name} = {m(ln.line_total)}"
        for ln in q.lines
    ]
    text = " + ".join(parts) + f" -> subtotal {m(q.subtotal)}" if parts else "No fixed-price services."
    if q.percent_applied:
        text += f"; {q.percent_applied:g}% discount -{m(q.percent_discount)}"
    for flat in q.flat_discounts:
        text += f"; {flat['type'].replace('_', ' ')} -{m(flat['amount'])}"
    if parts:
        text += f"; total {m(q.total)}"
    return text
