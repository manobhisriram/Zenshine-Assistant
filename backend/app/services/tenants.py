"""Tenant (brand / market) configuration loaded from YAML."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator


class Brand(BaseModel):
    name: str
    legal_name: str = ""
    tagline: str = ""
    city: str = ""
    region: str = ""
    country: str = ""
    business_type: str = "business"


class Locale(BaseModel):
    default_language: str = "en"
    supported_languages: list[str] = ["en"]
    timezone: str = "UTC"


class Currency(BaseModel):
    code: str
    symbol: str
    minor_unit_decimals: int = 0


class Contact(BaseModel):
    phone: str
    phone_note: str = ""
    email: str = ""
    address: str = ""
    hours: str = ""


class Operations(BaseModel):
    same_day_cutoff: str = ""
    payment: str = ""


class Service(BaseModel):
    id: str
    name: str
    price: float | None = None
    unit: str = "visit"
    duration: str = ""
    notes: str = ""
    price_is_from: bool = False
    requires_site_visit: bool = False
    custom_quote: bool = False

    @model_validator(mode="after")
    def _price_or_custom(self) -> "Service":
        if self.price is None and not self.custom_quote:
            raise ValueError(f"service {self.id}: price or custom_quote is required")
        return self


class ComboTier(BaseModel):
    min_services: int = Field(ge=2)
    percent: float = Field(gt=0, le=100)


class FreeWith(BaseModel):
    trigger: str
    free: str


class Discounts(BaseModel):
    combo_tiers: list[ComboTier] = []
    first_time_flat: float = 0
    monthly_contract_percent: float = 0
    referral_flat: float = 0
    free_with: list[FreeWith] = []
    festival_note: str = ""


class Package(BaseModel):
    id: str
    name: str
    includes: list[str]
    list_price: float | None = None
    discounted_price: float | None = None
    starting_price: float | None = None
    custom_quote: bool = False
    notes: str = ""


class UIConfig(BaseModel):
    welcome_title: str
    welcome_body: str
    suggestions: list[str] = []
    disclaimer: str = ""


class Tenant(BaseModel):
    id: str
    brand: Brand
    locale: Locale = Locale()
    currency: Currency
    contact: Contact
    operations: Operations = Operations()
    services: list[Service]
    discounts: Discounts = Discounts()
    packages: list[Package] = []
    ui: UIConfig

    @model_validator(mode="after")
    def _references_resolve(self) -> "Tenant":
        ids = {s.id for s in self.services}
        if len(ids) != len(self.services):
            raise ValueError("duplicate service ids")
        for pkg in self.packages:
            missing = [i for i in pkg.includes if i not in ids]
            if missing:
                raise ValueError(f"package {pkg.id} references unknown services {missing}")
        for rule in self.discounts.free_with:
            if rule.trigger not in ids or rule.free not in ids:
                raise ValueError("free_with references unknown service")
        return self

    def service(self, service_id: str) -> Service | None:
        return next((s for s in self.services if s.id == service_id), None)

    def money(self, amount: float) -> str:
        d = self.currency.minor_unit_decimals
        return f"{self.currency.symbol}{amount:,.{d}f}"


class TenantRegistry:
    def __init__(self, directory: Path) -> None:
        self._tenants: dict[str, Tenant] = {}
        for path in sorted(directory.glob("*.yaml")):
            tenant = Tenant.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
            if tenant.id != path.stem:
                raise ValueError(f"{path.name}: tenant id '{tenant.id}' must match the file name")
            self._tenants[tenant.id] = tenant
        if not self._tenants:
            raise ValueError(f"no tenant definitions found in {directory}")

    def get(self, tenant_id: str) -> Tenant | None:
        return self._tenants.get(tenant_id)

    def ids(self) -> list[str]:
        return list(self._tenants)


@lru_cache(maxsize=4)
def load_registry(directory: str) -> TenantRegistry:
    return TenantRegistry(Path(directory))
