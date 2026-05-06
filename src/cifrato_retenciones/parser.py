from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .models import Invoice, InvoiceLine, Party, Tax

NS = {
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
}


class InvoiceParseError(ValueError):
    pass


def parse_invoice_file(path: str | Path) -> Invoice:
    source = Path(path)
    raw = source.read_text(encoding="utf-8-sig", errors="replace")
    return parse_invoice_xml(raw, source_file=str(source))


def parse_invoice_xml(raw: str, source_file: str | None = None) -> Invoice:
    invoice_xml = extract_invoice_xml(raw)
    root = ET.fromstring(invoice_xml)
    return parse_invoice_root(root, source_file=source_file)


def extract_invoice_xml(raw_xml: str) -> str:
    """Return the inner DIAN Invoice XML, even when wrapped in AttachedDocument."""
    if re.search(r"<(?:\w+:)?Invoice[\s>]", raw_xml):
        start = re.search(r"<(?:\w+:)?Invoice[\s>]", raw_xml)
        if start and "<AttachedDocument" not in raw_xml[: start.start()]:
            return raw_xml

    descriptions = re.findall(
        r"<cbc:Description><!\[CDATA\[(.*?)\]\]></cbc:Description>",
        raw_xml,
        flags=re.DOTALL,
    )
    for description in descriptions:
        candidate = html.unescape(description).strip()
        if re.search(r"<(?:\w+:)?Invoice[\s>]", candidate):
            return candidate

    generic_cdata = re.findall(r"<!\[CDATA\[(.*?)\]\]>", raw_xml, flags=re.DOTALL)
    for candidate in generic_cdata:
        if re.search(r"<(?:\w+:)?Invoice[\s>]", candidate):
            return html.unescape(candidate).strip()

    if re.search(r"<(?:\w+:)?Invoice[\s>]", raw_xml):
        return raw_xml

    raise InvoiceParseError("No se encontro un nodo Invoice dentro del XML.")


def parse_invoice_root(root: ET.Element, source_file: str | None = None) -> Invoice:
    if _local_name(root.tag) != "Invoice":
        raise InvoiceParseError(f"Se esperaba Invoice, se recibio {_local_name(root.tag)}.")

    return Invoice(
        id=_text(root, "./cbc:ID"),
        issue_date=_text(root, "./cbc:IssueDate"),
        currency=_text(root, "./cbc:DocumentCurrencyCode", default="COP"),
        supplier=_parse_party(root, "./cac:AccountingSupplierParty"),
        customer=_parse_party(root, "./cac:AccountingCustomerParty"),
        line_extension_amount=_decimal(_text(root, "./cac:LegalMonetaryTotal/cbc:LineExtensionAmount")),
        tax_exclusive_amount=_decimal(_text(root, "./cac:LegalMonetaryTotal/cbc:TaxExclusiveAmount")),
        tax_inclusive_amount=_decimal(_text(root, "./cac:LegalMonetaryTotal/cbc:TaxInclusiveAmount")),
        payable_amount=_decimal(_text(root, "./cac:LegalMonetaryTotal/cbc:PayableAmount")),
        taxes=[_parse_tax_total(tax_total) for tax_total in root.findall("./cac:TaxTotal", NS)],
        lines=[_parse_line(line) for line in root.findall("./cac:InvoiceLine", NS)],
        source_file=source_file,
    )


def _parse_party(root: ET.Element, path: str) -> Party:
    party_root = root.find(path, NS)
    if party_root is None:
        return Party(name="", document_id="")

    party = party_root.find("./cac:Party", NS)
    if party is None:
        return Party(name="", document_id="")

    tax_scheme = party.find("./cac:PartyTaxScheme", NS)
    legal_entity = party.find("./cac:PartyLegalEntity", NS)
    physical_address = party.find("./cac:PhysicalLocation/cac:Address", NS)

    name = _first_text(
        tax_scheme,
        ["./cbc:RegistrationName"],
        fallback=_first_text(legal_entity, ["./cbc:RegistrationName"], fallback=_text(party, "./cac:PartyName/cbc:Name")),
    )
    company_id_el = tax_scheme.find("./cbc:CompanyID", NS) if tax_scheme is not None else None
    company_id = (company_id_el.text or "").strip() if company_id_el is not None else ""
    document_type = company_id_el.attrib.get("schemeName") if company_id_el is not None else None

    return Party(
        name=name,
        document_id=company_id,
        document_type=document_type,
        tax_level_code=_first_text(tax_scheme, ["./cbc:TaxLevelCode"]),
        city=_first_text(physical_address, ["./cbc:CityName"]),
    )


def _parse_line(line: ET.Element) -> InvoiceLine:
    standard_item = line.find("./cac:Item/cac:StandardItemIdentification/cbc:ID", NS)
    return InvoiceLine(
        id=_text(line, "./cbc:ID"),
        description=_text(line, "./cac:Item/cbc:Description"),
        quantity=_decimal(_text(line, "./cbc:InvoicedQuantity", default="0")),
        line_extension_amount=_decimal(_text(line, "./cbc:LineExtensionAmount", default="0")),
        standard_item_id=(standard_item.text or "").strip() if standard_item is not None and standard_item.text else None,
        standard_item_scheme=standard_item.attrib.get("schemeName") if standard_item is not None else None,
        taxes=[_parse_tax_total(tax_total) for tax_total in line.findall("./cac:TaxTotal", NS)],
    )


def _parse_tax_total(tax_total: ET.Element) -> Tax:
    subtotal = tax_total.find("./cac:TaxSubtotal", NS)
    category = subtotal.find("./cac:TaxCategory", NS) if subtotal is not None else None
    scheme = category.find("./cac:TaxScheme", NS) if category is not None else None

    return Tax(
        id=_first_text(scheme, ["./cbc:ID"]),
        name=_first_text(scheme, ["./cbc:Name"]),
        percent=_decimal(_first_text(category, ["./cbc:Percent"], fallback="0")),
        taxable_amount=_decimal(_first_text(subtotal, ["./cbc:TaxableAmount"], fallback="0")),
        amount=_decimal(_text(tax_total, "./cbc:TaxAmount", default="0")),
    )


def _text(root: ET.Element | None, path: str, default: str = "") -> str:
    if root is None:
        return default
    el = root.find(path, NS)
    if el is None or el.text is None:
        return default
    return el.text.strip()


def _first_text(root: ET.Element | None, paths: list[str], fallback: str = "") -> str:
    for path in paths:
        value = _text(root, path)
        if value:
            return value
    return fallback


def _decimal(value: str) -> Decimal:
    try:
        return Decimal((value or "0").strip())
    except InvalidOperation as exc:
        raise InvoiceParseError(f"Valor numerico invalido: {value!r}") from exc


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]
