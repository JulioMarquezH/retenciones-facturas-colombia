from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(frozen=True)
class Party:
    name: str
    document_id: str
    document_type: str | None = None
    tax_level_code: str | None = None
    city: str | None = None


@dataclass(frozen=True)
class Tax:
    id: str
    name: str
    percent: Decimal
    taxable_amount: Decimal
    amount: Decimal


@dataclass(frozen=True)
class InvoiceLine:
    id: str
    description: str
    quantity: Decimal
    line_extension_amount: Decimal
    taxes: list[Tax] = field(default_factory=list)


@dataclass(frozen=True)
class Invoice:
    id: str
    issue_date: str
    currency: str
    supplier: Party
    customer: Party
    line_extension_amount: Decimal
    tax_exclusive_amount: Decimal
    tax_inclusive_amount: Decimal
    payable_amount: Decimal
    taxes: list[Tax]
    lines: list[InvoiceLine]
    source_file: str | None = None


@dataclass(frozen=True)
class RetentionResult:
    code: str
    name: str
    applies: bool
    base: Decimal
    rate: Decimal
    amount: Decimal
    reason: str
    evidence: list[str] = field(default_factory=list)
    missing_data: list[str] = field(default_factory=list)
    suggested: bool = False
