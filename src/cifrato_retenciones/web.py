from __future__ import annotations

import json
import mimetypes
import os
from decimal import Decimal
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .catalogs import IcaRate, TaxCatalogs, load_internal_catalog
from .parser import InvoiceParseError, parse_invoice_xml
from .rules import RuleContext, calculate_retentions
from .serialize import invoice_report, json_default

WEB_DIR = Path(__file__).resolve().parent / "web_static"


def run(host: str = "127.0.0.1", port: int = 8000) -> None:
    server = ThreadingHTTPServer((host, port), RequestHandler)
    print(f"Interfaz disponible en http://{host}:{port}")
    server.serve_forever()


class RequestHandler(BaseHTTPRequestHandler):
    server_version = "CifratoRetenciones/0.1"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in {"", "/"}:
            self._serve_file(WEB_DIR / "index.html")
            return

        requested = (WEB_DIR / parsed.path.lstrip("/")).resolve()
        if WEB_DIR not in requested.parents and requested != WEB_DIR:
            self._send_json({"error": "Ruta no permitida"}, HTTPStatus.FORBIDDEN)
            return
        self._serve_file(requested)

    def do_HEAD(self) -> None:
        parsed = urlparse(self.path)
        path = WEB_DIR / "index.html" if parsed.path in {"", "/"} else WEB_DIR / parsed.path.lstrip("/")
        if not path.exists() or not path.is_file():
            self.send_response(HTTPStatus.NOT_FOUND)
            self.end_headers()
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(path.stat().st_size))
        self.end_headers()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/analyze":
            self._send_json({"error": "Ruta no encontrada"}, HTTPStatus.NOT_FOUND)
            return

        try:
            files = self._read_multipart_files()
            query = parse_qs(parsed.query)
            catalogs = _catalogs_from_query(query)
            context = RuleContext(
                uvt=Decimal(query.get("uvt", ["52374"])[0] or "52374"),
                assume_customer_is_withholding_agent=_optional_bool(query.get("withholding_agent", ["auto"])[0]),
                supplier_is_income_tax_filer=query.get("supplier_income_tax_filer", ["true"])[0] != "false",
                include_reteiva=query.get("reteiva", ["true"])[0] != "false",
                include_reteica=query.get("reteica", ["true"])[0] != "false",
                catalogs=catalogs,
            )
            reports = []
            errors = []
            for uploaded in files:
                try:
                    raw = uploaded["content"].decode("utf-8-sig", errors="replace")
                    invoice = parse_invoice_xml(raw, source_file=uploaded["filename"])
                    retentions = calculate_retentions(invoice, context)
                    reports.append(invoice_report(invoice, retentions))
                except (InvoiceParseError, ValueError) as exc:
                    errors.append({"file": uploaded["filename"], "error": str(exc)})

            self._send_json({"count": len(reports), "reports": reports, "errors": errors})
        except Exception as exc:  # pragma: no cover - defensive web boundary
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def _serve_file(self, path: Path) -> None:
        if not path.exists() or not path.is_file():
            self._send_json({"error": "Archivo no encontrado"}, HTTPStatus.NOT_FOUND)
            return

        content = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        content = json.dumps(payload, ensure_ascii=False, indent=2, default=json_default).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _read_multipart_files(self) -> list[dict[str, bytes | str]]:
        content_type = self.headers.get("Content-Type", "")
        marker = "boundary="
        if marker not in content_type:
            raise ValueError("La peticion debe ser multipart/form-data.")

        boundary = content_type.split(marker, 1)[1].strip().strip('"')
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        delimiter = b"--" + boundary.encode("utf-8")
        files = []

        for part in body.split(delimiter):
            part = part.strip()
            if not part or part == b"--":
                continue
            if part.endswith(b"--"):
                part = part[:-2].strip()
            headers_raw, _, content = part.partition(b"\r\n\r\n")
            headers_text = headers_raw.decode("utf-8", errors="replace")
            disposition = _header_value(headers_text, "Content-Disposition")
            filename = _disposition_param(disposition, "filename")
            if not filename:
                continue
            files.append({"filename": Path(filename).name, "content": content.rstrip(b"\r\n")})

        if not files:
            raise ValueError("No se recibieron archivos XML.")
        return files

    def log_message(self, format: str, *args: object) -> None:
        return


def _header_value(headers_text: str, header_name: str) -> str:
    prefix = header_name.lower() + ":"
    for line in headers_text.splitlines():
        if line.lower().startswith(prefix):
            return line.split(":", 1)[1].strip()
    return ""


def _disposition_param(disposition: str, key: str) -> str:
    target = key + "="
    for piece in disposition.split(";"):
        piece = piece.strip()
        if piece.startswith(target):
            return piece.split("=", 1)[1].strip().strip('"')
    return ""


def _optional_bool(value: str) -> bool | None:
    if value == "true":
        return True
    if value == "false":
        return False
    return None


def _catalogs_from_query(query: dict[str, list[str]]) -> TaxCatalogs:
    internal = load_internal_catalog()
    supplier_nit = _first(query, "ica_supplier_nit")
    customer_nit = _first(query, "ica_customer_nit")
    municipality = _first(query, "ica_municipality")
    ciiu = _first(query, "ica_ciiu")
    rate_raw = _first(query, "ica_rate")
    agent_raw = _first(query, "ica_agent")

    supplier_ciiu = dict(internal.supplier_ciiu)
    ica_rates = dict(internal.ica_rates)
    withholding_agents_ica = set(internal.withholding_agents_ica)
    known_non_withholding_agents_ica = set(internal.known_non_withholding_agents_ica)
    known_municipalities = set(internal.known_municipalities)

    if supplier_nit and ciiu:
        supplier_ciiu[_clean_doc(supplier_nit)] = ciiu.strip().upper()

    if municipality and ciiu and rate_raw:
        rate = Decimal(rate_raw.strip()) / Decimal("1000")
        ica_rates[(_normalize_municipality(municipality), ciiu.strip().upper())] = IcaRate(
            municipality=municipality,
            ciiu=ciiu.strip().upper(),
            rate=rate,
            source="Dato ingresado manualmente en la interfaz",
        )
    if municipality:
        known_municipalities.add(_normalize_municipality(municipality))

    if customer_nit and municipality and agent_raw == "true":
        withholding_agents_ica.add((_clean_doc(customer_nit), _normalize_municipality(municipality)))
    elif customer_nit and municipality and agent_raw == "false":
        known_non_withholding_agents_ica.add((_clean_doc(customer_nit), _normalize_municipality(municipality)))

    return TaxCatalogs(
        supplier_ciiu=supplier_ciiu,
        ica_rates=ica_rates,
        withholding_agents_ica=withholding_agents_ica,
        known_non_withholding_agents_ica=known_non_withholding_agents_ica,
        known_municipalities=known_municipalities,
    )


def _first(query: dict[str, list[str]], key: str) -> str:
    values = query.get(key, [""])
    return values[0].strip() if values else ""


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


def main() -> None:
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    run(host=host, port=port)


if __name__ == "__main__":
    main()
