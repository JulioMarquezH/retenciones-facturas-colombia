from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
import json
from pathlib import Path


@dataclass(frozen=True)
class IcaRate:
    municipality: str
    ciiu: str
    rate: Decimal
    source: str


@dataclass(frozen=True)
class TaxCatalogs:
    supplier_ciiu: dict[str, str] = field(default_factory=dict)
    ica_rates: dict[tuple[str, str], IcaRate] = field(default_factory=dict)
    withholding_agents_ica: set[tuple[str, str]] = field(default_factory=set)
    known_non_withholding_agents_ica: set[tuple[str, str]] = field(default_factory=set)
    known_municipalities: set[str] = field(default_factory=set)

    def ciiu_for_supplier(self, supplier_document_id: str) -> str | None:
        return self.supplier_ciiu.get(_clean_doc(supplier_document_id))

    def ica_rate(self, municipality: str, ciiu: str) -> IcaRate | None:
        return self.ica_rates.get((_normalize_municipality(municipality), ciiu.strip().upper()))

    def is_ica_withholding_agent(self, customer_document_id: str, municipality: str) -> bool:
        return (_clean_doc(customer_document_id), _normalize_municipality(municipality)) in self.withholding_agents_ica

    def is_known_not_ica_withholding_agent(self, customer_document_id: str, municipality: str) -> bool:
        return (_clean_doc(customer_document_id), _normalize_municipality(municipality)) in self.known_non_withholding_agents_ica

    def municipalities(self) -> list[str]:
        names = set(self.known_municipalities)
        names.update(_normalize_municipality(rate.municipality) for rate in self.ica_rates.values())
        names.update(municipality for _, municipality in self.withholding_agents_ica)
        names.update(municipality for _, municipality in self.known_non_withholding_agents_ica)
        return sorted(names)


def empty_catalogs() -> TaxCatalogs:
    return TaxCatalogs()


def load_internal_catalog(path: str | Path | None = None) -> TaxCatalogs:
    catalog_path = Path(path) if path else Path(__file__).resolve().parent / "data" / "tax_catalog.json"
    if not catalog_path.exists():
        return empty_catalogs()

    raw = json.loads(catalog_path.read_text(encoding="utf-8"))

    supplier_ciiu = {
        _clean_doc(item["nit"]): str(item["ciiu"]).strip().upper()
        for item in raw.get("suppliers", [])
        if item.get("nit") and item.get("ciiu")
    }

    ica_rates = {}
    for item in raw.get("ica_rates", []):
        municipality = item.get("municipality", "")
        ciiu = str(item.get("ciiu", "")).strip().upper()
        rate_per_thousand = item.get("rate_per_thousand")
        if not municipality or not ciiu or rate_per_thousand in {None, ""}:
            continue
        ica_rates[(_normalize_municipality(municipality), ciiu)] = IcaRate(
            municipality=municipality,
            ciiu=ciiu,
            rate=Decimal(str(rate_per_thousand)) / Decimal("1000"),
            source=item.get("source", "Catalogo interno"),
        )

    withholding_agents_ica = {
        (_clean_doc(item["customer_nit"]), _normalize_municipality(item["municipality"]))
        for item in raw.get("ica_withholding_agents", [])
        if item.get("customer_nit") and item.get("municipality") and item.get("is_agent", True)
    }
    known_non_withholding_agents_ica = {
        (_clean_doc(item["customer_nit"]), _normalize_municipality(item["municipality"]))
        for item in raw.get("ica_withholding_agents", [])
        if item.get("customer_nit") and item.get("municipality") and item.get("is_agent") is False
    }
    known_municipalities = {
        _normalize_municipality(item)
        for item in raw.get("municipalities", [])
        if item
    }

    return TaxCatalogs(
        supplier_ciiu=supplier_ciiu,
        ica_rates=ica_rates,
        withholding_agents_ica=withholding_agents_ica,
        known_non_withholding_agents_ica=known_non_withholding_agents_ica,
        known_municipalities=known_municipalities,
    )


def _clean_doc(value: str) -> str:
    return "".join(ch for ch in value if ch.isdigit())


def _normalize_municipality(value: str) -> str:
    normalized = (
        (value or "")
        .upper()
        .replace("Á", "A")
        .replace("É", "E")
        .replace("Í", "I")
        .replace("Ó", "O")
        .replace("Ú", "U")
        .replace("Ü", "U")
    )
    normalized = "".join(ch for ch in normalized if ch.isalnum())
    aliases = {
        "BOGOTADC": "BOGOTA",
        "BOGOTA": "BOGOTA",
        "MEDELLIN": "MEDELLIN",
    }
    return aliases.get(normalized, normalized)
