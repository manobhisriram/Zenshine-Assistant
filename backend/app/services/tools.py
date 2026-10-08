"""Agent tools. Tool results are deterministic and validated; the model never computes prices."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core import metrics
from app.core.ratelimit import RateLimiter
from app.services.leads import LeadService, valid_phone
from app.services.pricing import calculate_quote
from app.services.tenants import Tenant


@dataclass(slots=True)
class ToolContext:
    tenant: Tenant
    session_id: str
    identity: str
    leads: LeadService
    limiter: RateLimiter


def tool_specs(tenant: Tenant) -> list[dict[str, Any]]:
    service_ids = [s.id for s in tenant.services]
    return [
        {
            "name": "calculate_quote",
            "description": (
                "Compute an exact price breakdown for one or more services, applying the company's combo, first-time, "
                "monthly-contract and referral discounts. Always use this for totals; never calculate prices yourself."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 20,
                        "items": {
                            "type": "object",
                            "properties": {
                                "service_id": {"type": "string", "enum": service_ids},
                                "quantity": {
                                    "type": "integer",
                                    "minimum": 1,
                                    "maximum": 50,
                                    "description": "Units: bathrooms, sofa sets, mattresses, tanks. Default 1.",
                                },
                            },
                            "required": ["service_id"],
                        },
                    },
                    "first_time_customer": {"type": "boolean"},
                    "monthly_contract": {"type": "boolean"},
                    "referral": {"type": "boolean"},
                },
                "required": ["items"],
            },
        },
        {
            "name": "request_callback",
            "description": (
                "Submit a callback request so the team calls the customer. Only call after the customer has given their "
                "name and phone number and agreed to be contacted."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "maxLength": 80},
                    "phone": {"type": "string", "maxLength": 24},
                    "interest": {"type": "string", "maxLength": 200, "description": "Services the customer is interested in"},
                    "preferred_time": {"type": "string", "maxLength": 80},
                    "consent": {"type": "boolean", "description": "True only if the customer agreed to be contacted"},
                },
                "required": ["name", "phone", "consent"],
            },
        },
    ]


async def execute_tool(name: str, args: dict[str, Any], ctx: ToolContext) -> tuple[dict[str, Any], bool]:
    """Returns (result, is_error)."""
    try:
        if name == "calculate_quote":
            quote = calculate_quote(
                ctx.tenant,
                args.get("items") or [],
                first_time_customer=bool(args.get("first_time_customer")),
                monthly_contract=bool(args.get("monthly_contract")),
                referral=bool(args.get("referral")),
            )
            metrics.TOOL_CALLS.labels(tool=name, outcome="ok").inc()
            return quote.as_dict(), False

        if name == "request_callback":
            if not args.get("consent"):
                return {"error": "Customer consent is required before submitting a callback request."}, True
            customer = str(args.get("name", "")).strip()[:80]
            phone = str(args.get("phone", "")).strip()
            if len(customer) < 2 or not valid_phone(phone):
                return {"error": "A valid name and phone number are required. Ask the customer to re-enter them."}, True
            await ctx.limiter.enforce("callback", ctx.identity, 3, 3600)
            lead_id = await ctx.leads.capture(
                {
                    "tenant": ctx.tenant.id,
                    "name": customer,
                    "phone": phone,
                    "interest": str(args.get("interest", ""))[:200],
                    "preferred_time": str(args.get("preferred_time", ""))[:80],
                    "session_id": ctx.session_id,
                }
            )
            metrics.TOOL_CALLS.labels(tool=name, outcome="ok").inc()
            return {
                "status": "submitted",
                "reference": lead_id[:8],
                "message": "The team will call back during working hours.",
            }, False

        metrics.TOOL_CALLS.labels(tool="unknown", outcome="rejected").inc()
        return {"error": f"Unknown tool '{name}'."}, True
    except Exception as exc:
        outcome = "invalid" if isinstance(exc, (ValueError, KeyError, TypeError)) else "error"
        metrics.TOOL_CALLS.labels(tool=name, outcome=outcome).inc()
        msg = str(exc) if outcome == "invalid" else "The tool failed. Apologise briefly and offer the phone number."
        if getattr(exc, "status_code", None) == 429:
            msg = "Too many callback requests from this session. Ask the customer to call the team directly."
        return {"error": msg}, True
