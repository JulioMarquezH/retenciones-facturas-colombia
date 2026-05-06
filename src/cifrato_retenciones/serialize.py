from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal
from typing import Any

from .models import Invoice, RetentionResult
from .rules import classify_invoice
from .catalogs import load_internal_catalog


def invoice_report(invoice: Invoice, retentions: list[RetentionResult]) -> dict[str, Any]:
    classification = classify_invoice(invoice)
    catalog_municipalities = load_internal_catalog().municipalities()
    invoice_municipalities = _unique(
        [
            *_same_normalized_catalog_matches(invoice.customer.city, catalog_municipalities),
            *_same_normalized_catalog_matches(invoice.supplier.city, catalog_municipalities),
        ]
    )
    return {
        "invoice": {
            "id": invoice.id,
            "issue_date": invoice.issue_date,
            "source_file": invoice.source_file,
            "currency": invoice.currency,
            "supplier": asdict(invoice.supplier),
            "customer": asdict(invoice.customer),
            "totals": {
                "line_extension_amount": invoice.line_extension_amount,
                "tax_exclusive_amount": invoice.tax_exclusive_amount,
                "tax_inclusive_amount": invoice.tax_inclusive_amount,
                "payable_amount": invoice.payable_amount,
            },
            "taxes": [asdict(tax) for tax in invoice.taxes],
            "lines": [asdict(line) for line in invoice.lines],
        },
        "classification": asdict(classification),
        "retentions": [asdict(retention) for retention in retentions],
        "options": {
            "municipalities": catalog_municipalities,
            "detected_municipality": invoice_municipalities[0] if invoice_municipalities else "",
        },
    }


def json_default(value: Any) -> str:
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _unique(values: list[str | None]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if not value:
            continue
        key = _normalize(value)
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _same_normalized_catalog_matches(value: str | None, catalog_values: list[str]) -> list[str]:
    if not value:
        return []
    normalized = _normalize(value)
    return [catalog_value for catalog_value in catalog_values if _normalize(catalog_value) == normalized]


def _normalize(value: str) -> str:
    aliases = {
        "BOGOTADC": "BOGOTA",
        "BOGOTA": "BOGOTA",
        "MEDELLIN": "MEDELLIN",
    }
    normalized = (
        value.upper()
        .replace("Á", "A")
        .replace("É", "E")
        .replace("Í", "I")
        .replace("Ó", "O")
        .replace("Ú", "U")
        .replace("Ü", "U")
    )
    normalized = "".join(ch for ch in normalized if ch.isalnum())
    return aliases.get(normalized, normalized)
