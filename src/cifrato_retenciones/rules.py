from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
import re

from .catalogs import TaxCatalogs, load_internal_catalog
from .models import Invoice, RetentionResult

UVT_2026 = Decimal("52374")


@dataclass(frozen=True)
class Classification:
    concept: str
    confidence: Decimal
    evidence: list[str]


@dataclass(frozen=True)
class RuleContext:
    uvt: Decimal = UVT_2026
    assume_customer_is_withholding_agent: bool | None = None
    supplier_is_income_tax_filer: bool = True
    include_reteiva: bool = True
    include_reteica: bool = True
    catalogs: TaxCatalogs = load_internal_catalog()


def calculate_retentions(invoice: Invoice, context: RuleContext | None = None) -> list[RetentionResult]:
    ctx = context or RuleContext()
    classification = classify_invoice(invoice)
    withholding_agent = _is_withholding_agent(invoice, ctx)
    results: list[RetentionResult] = []

    results.append(_income_tax_result(invoice, classification, withholding_agent, ctx))

    if ctx.include_reteiva:
        results.append(_vat_withholding_result(invoice, classification, withholding_agent, ctx))

    if ctx.include_reteica:
        results.append(_local_tax_result(invoice, classification, ctx))

    return results


def classify_invoice(invoice: Invoice) -> Classification:
    text = " ".join(line.description for line in invoice.lines).lower()

    service_patterns = {
        "honorarios": [r"\bhonorario\b", r"\bhonorarios\b", r"\bcomision\b", r"\bcomisión\b", r"\bcomisiones\b"],
        "consultoria": [r"\bconsultoria\b", r"\bconsultoría\b", r"\basesoria\b", r"\basesoría\b"],
        "transporte": [r"\btransporte\b", r"\bcarga\b", r"\bflete\b", r"\btraslado\b"],
        "parqueadero": [r"\bparqueadero\b", r"\bparking\b", r"\bplaca vehiculo\b", r"\bplaca vehículo\b"],
        "servicio": [r"\bservicio\b", r"\bservicios\b", r"\bmano de obra\b", r"\bmantenimiento\b"],
    }
    goods_patterns = [
        r"\bpan\b",
        r"\btorta\b",
        r"\bcroissant\b",
        r"\bmacarron\b",
        r"\bcamaron\b",
        r"\brepuesto\b",
        r"\bbobina\b",
        r"\bbujia\b",
        r"\bmantequilla\b",
        r"\bmouse\b",
        r"\bconvertidor\b",
    ]

    for concept, patterns in service_patterns.items():
        matched = [pattern for pattern in patterns if re.search(pattern, text)]
        if matched:
            return Classification(concept=concept, confidence=Decimal("0.85"), evidence=_line_evidence(invoice, matched))

    matched_goods = [pattern for pattern in goods_patterns if re.search(pattern, text)]
    if matched_goods:
        return Classification(concept="compra_bienes", confidence=Decimal("0.75"), evidence=_line_evidence(invoice, matched_goods))

    return Classification(
        concept="indeterminado",
        confidence=Decimal("0.30"),
        evidence=[f"Descripciones: {', '.join(line.description for line in invoice.lines[:3])}"],
    )


def _income_tax_result(
    invoice: Invoice,
    classification: Classification,
    withholding_agent: bool,
    ctx: RuleContext,
) -> RetentionResult:
    base = _retention_base(invoice)

    if not withholding_agent:
        return RetentionResult(
            code="retefuente",
            name="Retencion en la fuente",
            applies=False,
            base=base,
            rate=Decimal("0"),
            amount=Decimal("0"),
            reason="No se calcula porque el comprador no parece ser agente de retencion en esta factura.",
            evidence=[f"Comprador: {invoice.customer.name} ({invoice.customer.document_id})"],
        )

    supplier_status = "declarante" if ctx.supplier_is_income_tax_filer else "no declarante"

    if classification.concept in {"honorarios", "consultoria"}:
        min_base = Decimal("0")
        rate = Decimal("0.11") if ctx.supplier_is_income_tax_filer else Decimal("0.10")
        label = "honorarios y comisiones"
    elif classification.concept in {"servicio", "parqueadero"}:
        min_base = ctx.uvt * Decimal("4")
        rate = Decimal("0.04") if ctx.supplier_is_income_tax_filer else Decimal("0.06")
        label = "servicios generales"
    elif classification.concept == "transporte":
        min_base = ctx.uvt * Decimal("4")
        rate = Decimal("0.01")
        label = "servicio de transporte de carga"
    elif classification.concept == "compra_bienes":
        min_base = ctx.uvt * Decimal("27")
        rate = Decimal("0.025") if ctx.supplier_is_income_tax_filer else Decimal("0.035")
        label = "compras generales"
    else:
        return RetentionResult(
            code="retefuente",
            name="Retencion en la fuente",
            applies=False,
            base=base,
            rate=Decimal("0"),
            amount=Decimal("0"),
            reason="No se calcula automaticamente porque no fue posible clasificar el concepto de la factura con suficiente confianza.",
            evidence=classification.evidence,
            missing_data=["concepto tributario o categoria de compra/servicio"],
        )

    if base < min_base:
        return RetentionResult(
            code="retefuente",
            name="Retencion en la fuente",
            applies=False,
            base=base,
            rate=rate,
            amount=Decimal("0"),
            reason=f"No aplica retencion por {label}: la base {money(base)} es menor al minimo {money(min_base)}.",
            evidence=classification.evidence,
        )

    return RetentionResult(
        code="retefuente",
        name="Retencion en la fuente",
        applies=True,
        base=base,
        rate=rate,
        amount=_money(base * rate),
        reason=f"Aplica retencion por {label}: base {money(base)} >= minimo {money(min_base)} y tarifa {percent(rate)} para proveedor {supplier_status}.",
        evidence=classification.evidence + [
            f"Base tomada del total antes de impuestos: {money(base)}",
        ],
    )


def _vat_withholding_result(
    invoice: Invoice,
    classification: Classification,
    withholding_agent: bool,
    ctx: RuleContext,
) -> RetentionResult:
    vat = sum((tax.amount for tax in invoice.taxes if tax.id == "01" or tax.name.upper() == "IVA"), Decimal("0"))
    retention_base = _retention_base(invoice)

    if vat <= 0:
        return RetentionResult(
            code="reteiva",
            name="ReteIVA",
            applies=False,
            base=Decimal("0"),
            rate=Decimal("0.15"),
            amount=Decimal("0"),
            reason="No aplica ReteIVA porque la factura no tiene IVA causado.",
            evidence=[f"IVA detectado: {money(vat)}"],
        )

    if not withholding_agent:
        return RetentionResult(
            code="reteiva",
            name="ReteIVA",
            applies=False,
            base=vat,
            rate=Decimal("0.15"),
            amount=Decimal("0"),
            reason="No se calcula ReteIVA porque el comprador no parece ser agente de retencion.",
            evidence=[f"IVA detectado: {money(vat)}"],
        )

    if classification.concept in {"honorarios", "consultoria"}:
        min_base = Decimal("0")
    elif classification.concept in {"servicio", "parqueadero", "transporte"}:
        min_base = ctx.uvt * Decimal("4")
    else:
        min_base = ctx.uvt * Decimal("27")
    if retention_base < min_base:
        return RetentionResult(
            code="reteiva",
            name="ReteIVA",
            applies=False,
            base=vat,
            rate=Decimal("0.15"),
            amount=Decimal("0"),
            reason=f"No aplica ReteIVA porque la base antes de impuestos {money(retention_base)} es menor al minimo {money(min_base)}.",
            evidence=[f"IVA detectado: {money(vat)}", f"Concepto clasificado: {classification.concept}"],
        )

    return RetentionResult(
        code="reteiva",
        name="ReteIVA",
        applies=True,
        base=vat,
        rate=Decimal("0.15"),
        amount=_money(vat * Decimal("0.15")),
        reason="Aplica ReteIVA sobre el IVA causado, usando tarifa general del 15% sobre el impuesto.",
        evidence=[f"IVA detectado en TaxTotal: {money(vat)}"],
    )


def _local_tax_result(invoice: Invoice, classification: Classification, ctx: RuleContext) -> RetentionResult:
    base = _retention_base(invoice)
    municipality = _municipality(invoice)
    withholding_agent = _is_withholding_agent(invoice, ctx)

    if classification.concept == "indeterminado":
        return RetentionResult(
            code="reteica",
            name="ReteICA",
            applies=False,
            base=base,
            rate=Decimal("0"),
            amount=Decimal("0"),
            reason="No se sugiere ReteICA porque no fue posible clasificar el concepto de la factura.",
            evidence=[f"Ciudad proveedor: {invoice.supplier.city or 'no disponible'}", f"Ciudad comprador: {invoice.customer.city or 'no disponible'}"],
            missing_data=["concepto tributario o actividad economica"],
        )

    if not withholding_agent:
        return RetentionResult(
            code="reteica",
            name="ReteICA",
            applies=False,
            base=base,
            rate=Decimal("0"),
            amount=Decimal("0"),
            reason="No aplica ReteICA porque el comprador no parece ser agente retenedor en esta factura.",
            evidence=[
                f"Comprador: {invoice.customer.name} ({invoice.customer.document_id})",
                f"Concepto clasificado: {classification.concept}",
            ],
        )

    if not municipality:
        return RetentionResult(
            code="reteica",
            name="ReteICA",
            applies=False,
            base=base,
            rate=Decimal("0"),
            amount=Decimal("0"),
            reason="No se sugiere ReteICA porque no hay municipio suficiente para asociar una tarifa local.",
            evidence=[f"Concepto clasificado: {classification.concept}"],
            missing_data=["municipio de retencion", "actividad economica/CIIU del proveedor", "tarifa ICA municipal para el CIIU", "configuracion del comprador como agente retenedor ICA en el municipio"],
        )

    ciiu = ctx.catalogs.ciiu_for_supplier(invoice.supplier.document_id)
    missing = []
    if not ciiu:
        missing.append("actividad economica/CIIU del proveedor")

    rate = ctx.catalogs.ica_rate(municipality, ciiu) if ciiu else None
    if ciiu and rate is None:
        missing.append("tarifa ICA municipal para el CIIU")

    if ctx.catalogs.is_known_not_ica_withholding_agent(invoice.customer.document_id, municipality):
        return RetentionResult(
            code="reteica",
            name="ReteICA",
            applies=False,
            base=base,
            rate=Decimal("0"),
            amount=Decimal("0"),
            reason=f"No aplica ReteICA en {municipality} porque se indicó que el comprador no es agente retenedor ICA en ese municipio.",
            evidence=[
                f"Concepto clasificado: {classification.concept}",
                f"Ciudad proveedor: {invoice.supplier.city or 'no disponible'}",
                f"Ciudad comprador: {invoice.customer.city or 'no disponible'}",
                f"CIIU catalogado: {ciiu or 'no disponible'}",
            ],
        )

    is_ica_agent = ctx.catalogs.is_ica_withholding_agent(invoice.customer.document_id, municipality)
    if not is_ica_agent:
        missing.append("configuracion del comprador como agente retenedor ICA en el municipio")

    if missing:
        missing_text = _human_join(missing)
        return RetentionResult(
            code="reteica",
            name="ReteICA",
            applies=False,
            base=base,
            rate=Decimal("0"),
            amount=Decimal("0"),
            reason=f"Se sugiere revisar ReteICA para {municipality}, pero no se calcula porque faltan estos datos externos al XML: {missing_text}.",
            evidence=[
                f"Concepto clasificado: {classification.concept}",
                f"Ciudad proveedor: {invoice.supplier.city or 'no disponible'}",
                f"Ciudad comprador: {invoice.customer.city or 'no disponible'}",
                f"CIIU catalogado: {ciiu or 'no disponible'}",
            ],
            missing_data=missing,
            suggested=True,
        )

    return RetentionResult(
        code="reteica",
        name="ReteICA",
        applies=True,
        base=base,
        rate=rate.rate,
        amount=_money(base * rate.rate),
        reason=f"Aplica ReteICA para {municipality}: proveedor con CIIU {ciiu}, comprador configurado como agente retenedor ICA y tarifa municipal {per_thousand(rate.rate)}.",
        evidence=[
            f"Concepto clasificado: {classification.concept}",
            f"Ciudad proveedor: {invoice.supplier.city or 'no disponible'}",
            f"Ciudad comprador: {invoice.customer.city or 'no disponible'}",
            f"Fuente tarifa: {rate.source}",
        ],
    )


def _is_withholding_agent(invoice: Invoice, ctx: RuleContext) -> bool:
    if ctx.assume_customer_is_withholding_agent is not None:
        return ctx.assume_customer_is_withholding_agent

    name = invoice.customer.name.lower()
    doc = re.sub(r"\D", "", invoice.customer.document_id)
    if "consumidor final" in name or set(doc) == {"2"}:
        return False
    return True


def _retention_base(invoice: Invoice) -> Decimal:
    if invoice.tax_exclusive_amount > 0:
        return invoice.tax_exclusive_amount
    if invoice.line_extension_amount > 0:
        return invoice.line_extension_amount
    return invoice.payable_amount


def _municipality(invoice: Invoice) -> str:
    # For the suggestion, we use the buyer's city as the probable withholding municipality.
    # In a production implementation, this should come from the branch/location
    # where the service or purchase is incurred, or from the client's configuration.
    return invoice.customer.city or invoice.supplier.city or ""


def _line_evidence(invoice: Invoice, patterns: list[str]) -> list[str]:
    evidence = []
    for line in invoice.lines:
        lower = line.description.lower()
        if any(re.search(pattern, lower) for pattern in patterns):
            evidence.append(f"Linea {line.id}: {line.description}")
    return evidence[:5]


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def money(value: Decimal) -> str:
    return f"${_money(value):,}".replace(",", ".")


def percent(value: Decimal) -> str:
    return f"{(value * Decimal('100')).normalize()}%"


def per_thousand(value: Decimal) -> str:
    return f"{(value * Decimal('1000')).normalize()} x 1000"


def _human_join(items: list[str]) -> str:
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return f"{', '.join(items[:-1])} y {items[-1]}"
