# Cifrato Retenciones

Solucion tecnica para recibir una o varias facturas electronicas DIAN UBL 2.1, extraer sus datos contables principales y calcular retenciones aplicables con una justificacion trazable.

## Alcance

- Lee XML DIAN, incluyendo archivos `AttachedDocument` que traen la factura real dentro de un `CDATA`.
- Extrae proveedor, comprador, NIT, fecha, lineas, impuestos, bases y totales.
- Clasifica el concepto principal de la factura con reglas simples sobre las descripciones de las lineas y, cuando existe, el codigo UNSPSC del item.
- Calcula retenciones nacionales iniciales:
  - Retencion en la fuente.
  - ReteIVA.
- Sugiere ReteICA cuando hay municipio/concepto/base suficientes para revisarla, pero no la marca como aplicada ni calcula monto cuando falte actividad economica/CIIU, tarifa local exacta o calidad de agente retenedor ICA.
- Entrega salida JSON con evidencia y razones por cada retencion.

## Supuestos

Esta prueba usa un motor de reglas configurable y deja explicitos los supuestos:

- La base de retencion se toma del valor antes de impuestos (`TaxExclusiveAmount` o `LineExtensionAmount`).
- Si el comprador es `Consumidor Final` o tiene documento generico `222222222222`, no se asume agente retenedor.
- Si el comprador parece empresa, se asume agente retenedor para efectos de la prueba, salvo que se indique lo contrario.
- La tarifa de Retefuente depende de si el proveedor/sujeto retenido es declarante o no declarante de renta. Para simplificar la prueba, la interfaz asume proveedor declarante.
- Para 2026 se usa UVT de `$52.374`, fijada por la DIAN en la Resolucion 000238 de 2025.
- ReteICA no se calcula con tarifas inventadas. El motor la puede marcar como sugerida para revision y conserva los datos faltantes necesarios para confirmar si aplica.

Fuente UVT 2026: https://normograma.dian.gov.co/dian/compilacion/docs/resolucion_dian_0238_2025.htm

## Reglas iniciales

| Concepto clasificado | Base minima | Tarifa declarante | Tarifa no declarante |
| --- | ---: | ---: | ---: |
| Compras generales | 27 UVT | 2.5% | 3.5% |
| Servicios generales / parqueadero | 4 UVT | 4% | 6% |
| Transporte de carga | 4 UVT | 1% | 1% |
| Honorarios y comisiones | 0 UVT | 11% | 10% |

ReteIVA se calcula como 15% del IVA causado cuando hay IVA, comprador agente retenedor y la base supera el minimo del concepto.

ReteICA depende del municipio, actividad economica/CIIU, tarifa oficial local y configuracion del comprador como agente retenedor ICA. La solucion soporta esos datos como catalogos externos:

- `supplier_ciiu`: CIIU del proveedor, normalmente obtenido del RUT, onboarding/KYC o maestro de terceros.
- `ica_rates`: tarifas ICA/ReteICA por municipio y CIIU, tomadas de fuentes oficiales municipales.
- `withholding_agents_ica`: configuracion interna del comprador como agente retenedor ICA por municipio.

Si esos datos no estan cargados, la salida puede marcar ReteICA como `suggested: true`, conserva `missing_data` y no suma ningun valor al total retenido.

Si el comprador es consumidor final o usa un documento generico, ReteICA se marca como no aplicable porque no se trata como agente retenedor.

El catalogo interno vive en:

```text
src/cifrato_retenciones/data/tax_catalog.json
```

El archivo incluye una lista de municipios principales para la interfaz. No incluye proveedores ni agentes retenedores de demostracion. Las tarifas solo deben cargarse cuando tengan fuente real; por ejemplo:

- Bogota + CIIU 4631: 4.14 x 1000, soportada por la Resolucion SDH-000265 de 2021 de la Secretaria Distrital de Hacienda.
- Medellin + CIIU 4631A: 2 x 1000, soportada por Gaceta Oficial No. 5281 / Acuerdo 093 de 2023.
- Medellin + CIIU 4631B: 4 x 1000, soportada por Gaceta Oficial No. 5281 / Acuerdo 093 de 2023.

Cuando una ciudad divide una actividad en variantes, como Medellin con 4631A/4631B, no se debe asumir una tarifa si el usuario solo informa 4631.

Estrategia para cobertura:

- Mantener un catalogo base con tarifas verificadas para CIIU frecuentes por municipio.
- No inventar tarifas cuando falte una combinacion municipio + CIIU.
- Si falta la tarifa, la interfaz permite ingresar manualmente la tarifa ICA x 1000 para recalcular esa factura.
- Ese dato manual queda tratado como contexto de la operacion, no como tarifa oficial persistida.


## Uso

Interfaz grafica local:

```bash
PYTHONPATH=src python3 -m cifrato_retenciones.web
```

Luego abrir:

```text
http://127.0.0.1:8000
```

CLI:

```bash
PYTHONPATH=src python3 -m cifrato_retenciones.cli /ruta/a/factura.xml
```

Procesar una carpeta completa:

```bash
PYTHONPATH=src python3 -m cifrato_retenciones.cli /Users/juliomarquez/Downloads/sample-invoices
```

Forzar que el comprador sea tratado como agente retenedor:

```bash
PYTHONPATH=src python3 -m cifrato_retenciones.cli /ruta/a/facturas --assume-withholding-agent
```

## Salida

La respuesta incluye:

- `invoice`: datos normalizados de la factura.
- `classification`: concepto detectado y evidencia.
- `retentions`: resultado por retencion:
  - `applies`
  - `base`
  - `rate`
  - `amount`
  - `reason`
  - `evidence`
  - `missing_data`

## Ejemplo resumido

```json
{
  "code": "retefuente",
  "name": "Retencion en la fuente",
  "applies": true,
  "base": "43738800.00",
  "rate": "0.025",
  "amount": "1093470",
  "reason": "Aplica retencion por compras generales: base $43.738.800 >= minimo $1.414.098 y tarifa 2.5%."
}
```

## Ejecutar pruebas

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```
