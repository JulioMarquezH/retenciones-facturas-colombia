from __future__ import annotations

from decimal import Decimal
import tempfile
from pathlib import Path
import unittest

from cifrato_retenciones.parser import parse_invoice_file
from cifrato_retenciones.rules import RuleContext, calculate_retentions, classify_invoice


INVOICE_XML = """<?xml version="1.0" encoding="utf-8"?>
<Invoice xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
         xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
         xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2">
  <cbc:ID>TEST-1</cbc:ID>
  <cbc:IssueDate>2026-04-01</cbc:IssueDate>
  <cbc:DocumentCurrencyCode>COP</cbc:DocumentCurrencyCode>
  <cac:AccountingSupplierParty>
    <cac:Party>
      <cac:PartyTaxScheme>
        <cbc:RegistrationName>PROVEEDOR SAS</cbc:RegistrationName>
        <cbc:CompanyID schemeName="31">900111222</cbc:CompanyID>
      </cac:PartyTaxScheme>
    </cac:Party>
  </cac:AccountingSupplierParty>
  <cac:AccountingCustomerParty>
    <cac:Party>
      <cac:PartyTaxScheme>
        <cbc:RegistrationName>CLIENTE SAS</cbc:RegistrationName>
        <cbc:CompanyID schemeName="31">900333444</cbc:CompanyID>
      </cac:PartyTaxScheme>
    </cac:Party>
  </cac:AccountingCustomerParty>
  <cac:TaxTotal>
    <cbc:TaxAmount currencyID="COP">380000.00</cbc:TaxAmount>
    <cac:TaxSubtotal>
      <cbc:TaxableAmount currencyID="COP">2000000.00</cbc:TaxableAmount>
      <cbc:TaxAmount currencyID="COP">380000.00</cbc:TaxAmount>
      <cac:TaxCategory>
        <cbc:Percent>19.00</cbc:Percent>
        <cac:TaxScheme>
          <cbc:ID>01</cbc:ID>
          <cbc:Name>IVA</cbc:Name>
        </cac:TaxScheme>
      </cac:TaxCategory>
    </cac:TaxSubtotal>
  </cac:TaxTotal>
  <cac:LegalMonetaryTotal>
    <cbc:LineExtensionAmount currencyID="COP">2000000.00</cbc:LineExtensionAmount>
    <cbc:TaxExclusiveAmount currencyID="COP">2000000.00</cbc:TaxExclusiveAmount>
    <cbc:TaxInclusiveAmount currencyID="COP">2380000.00</cbc:TaxInclusiveAmount>
    <cbc:PayableAmount currencyID="COP">2380000.00</cbc:PayableAmount>
  </cac:LegalMonetaryTotal>
  <cac:InvoiceLine>
    <cbc:ID>1</cbc:ID>
    <cbc:InvoicedQuantity unitCode="94">1</cbc:InvoicedQuantity>
    <cbc:LineExtensionAmount currencyID="COP">2000000.00</cbc:LineExtensionAmount>
    <cac:Item><cbc:Description>MOUSE INALAMBRICO</cbc:Description></cac:Item>
  </cac:InvoiceLine>
</Invoice>
"""


class ParserAndRulesTest(unittest.TestCase):
    def test_parses_invoice_and_calculates_retentions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "invoice.xml"
            path.write_text(INVOICE_XML, encoding="utf-8")

            invoice = parse_invoice_file(path)
            results = calculate_retentions(invoice)

        self.assertEqual(invoice.id, "TEST-1")
        self.assertEqual(classify_invoice(invoice).concept, "compra_bienes")

        retefuente = next(result for result in results if result.code == "retefuente")
        reteiva = next(result for result in results if result.code == "reteiva")

        self.assertTrue(retefuente.applies)
        self.assertEqual(retefuente.amount, Decimal("50000"))
        self.assertTrue(reteiva.applies)
        self.assertEqual(reteiva.amount, Decimal("57000"))

    def test_extracts_invoice_from_attached_document_cdata(self) -> None:
        attached = f"""<?xml version="1.0" encoding="utf-8"?>
<AttachedDocument xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:Description><![CDATA[{INVOICE_XML}]]></cbc:Description>
</AttachedDocument>
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "attached.xml"
            path.write_text(attached, encoding="utf-8")
            invoice = parse_invoice_file(path)

        self.assertEqual(invoice.id, "TEST-1")

    def test_uses_non_filer_purchase_rate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "invoice.xml"
            path.write_text(INVOICE_XML, encoding="utf-8")
            invoice = parse_invoice_file(path)

        results = calculate_retentions(invoice, RuleContext(supplier_is_income_tax_filer=False))
        retefuente = next(result for result in results if result.code == "retefuente")

        self.assertTrue(retefuente.applies)
        self.assertEqual(retefuente.rate, Decimal("0.035"))
        self.assertEqual(retefuente.amount, Decimal("70000"))


if __name__ == "__main__":
    unittest.main()
