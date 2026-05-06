from __future__ import annotations

import argparse
import json
from decimal import Decimal
from pathlib import Path

from .parser import parse_invoice_file
from .rules import RuleContext, calculate_retentions
from .serialize import invoice_report, json_default


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="cifrato-retenciones",
        description="Calcula retenciones aplicables a una o varias facturas XML DIAN.",
    )
    parser.add_argument("paths", nargs="+", help="Archivos XML o carpetas con XML.")
    parser.add_argument("--uvt", type=str, default="52374", help="Valor UVT del periodo. Default: 52374.")
    parser.add_argument(
        "--assume-withholding-agent",
        action="store_true",
        help="Asume que el comprador es agente retenedor, incluso si la factura no permite inferirlo.",
    )
    parser.add_argument(
        "--supplier-non-filer",
        action="store_true",
        help="Trata al proveedor como no declarante de renta para escoger la tarifa de Retefuente.",
    )
    parser.add_argument(
        "--no-reteiva",
        action="store_true",
        help="No calcular ReteIVA.",
    )
    parser.add_argument(
        "--no-reteica",
        action="store_true",
        help="No reportar evaluacion de ReteICA.",
    )
    args = parser.parse_args()

    files = _expand_paths(args.paths)
    context = RuleContext(
        uvt=Decimal(args.uvt),
        assume_customer_is_withholding_agent=True if args.assume_withholding_agent else None,
        supplier_is_income_tax_filer=not args.supplier_non_filer,
        include_reteiva=not args.no_reteiva,
        include_reteica=not args.no_reteica,
    )

    reports = []
    for file in files:
        invoice = parse_invoice_file(file)
        retentions = calculate_retentions(invoice, context)
        reports.append(invoice_report(invoice, retentions))

    print(json.dumps({"count": len(reports), "reports": reports}, ensure_ascii=False, indent=2, default=json_default))


def _expand_paths(paths: list[str]) -> list[Path]:
    files: list[Path] = []
    for raw_path in paths:
        path = Path(raw_path)
        if path.is_dir():
            files.extend(sorted(path.rglob("*.xml")))
        else:
            files.append(path)
    return files


if __name__ == "__main__":
    main()
