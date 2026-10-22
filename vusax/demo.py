"""Datos de ejemplo (modo demo y pruebas). No se usan con la base real."""

from __future__ import annotations

import pandas as pd

from .config import CONFIG_DEFECTO, PLAN_CUENTAS, SCHEMAS


def _df(nombre: str, filas: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(filas, columns=SCHEMAS[nombre]) if filas else pd.DataFrame(columns=SCHEMAS[nombre])
    return df.fillna("").astype(str)


def datos_demo_crudos() -> dict[str, pd.DataFrame]:
    """Escenario pequeno y verificable a mano (ver tests/test_contabilidad.py)."""
    raw = {n: _df(n, []) for n in SCHEMAS}
    raw["Config"] = _df("Config", [{"clave": k, "valor": v} for k, v in CONFIG_DEFECTO.items()])
    raw["Cuentas"] = _df("Cuentas", [{"codigo": c, "nombre": n, "tipo": t, "subtipo": s, "activa": "SI"}
                                     for c, n, t, s in PLAN_CUENTAS])
    raw["Productos"] = _df("Productos", [{"sku": "A", "nombre": "Producto A", "categoria": "Belleza",
                                          "canal": "Amazon FBA", "costo": "5", "precio": "20", "stock": "10",
                                          "stock_min": "5", "activo": "SI"}])
    raw["Clientes"] = _df("Clientes", [{"id_cliente": "CLI-1", "nombre": "Total Food Logistics LLC",
                                        "terminos": "30", "exento_impuesto": "NO", "activo": "SI"}])
    raw["Proveedores"] = _df("Proveedores", [{"id_proveedor": "PRV-1", "nombre": "PDP Group", "terminos": "30",
                                              "activo": "SI"}])
    raw["Facturas_Prov"] = _df("Facturas_Prov", [{"id": "BIL-1", "num": "PDP-77", "fecha": "2026-01-05",
                                                  "vence": "2026-02-04", "id_proveedor": "PRV-1",
                                                  "proveedor": "PDP Group"}])
    raw["Bill_Items"] = _df("Bill_Items", [{"id": "BIT-1", "id_bill": "BIL-1", "sku": "A", "cantidad": "10",
                                            "costo_unit": "7"}])
    raw["Ingresos"] = _df("Ingresos", [{"id": "ING-1", "fecha": "2026-01-10", "canal": "Amazon FBA",
                                        "id_orden": "111-1", "sku": "A", "cantidad": "4", "ingreso_bruto": "100",
                                        "comisiones": "15", "tarifas": "8", "envio": "2"}])
    raw["Gastos"] = _df("Gastos", [{"id": "GAS-1", "fecha": "2026-01-12", "categoria": "Software",
                                    "proveedor": "Shopify", "descripcion": "Suscripcion", "monto": "50",
                                    "metodo": "Tarjeta"}])
    raw["Invoices"] = _df("Invoices", [{"num": "INV-1001", "fecha": "2026-01-15", "id_cliente": "CLI-1",
                                        "cliente": "Total Food Logistics LLC", "estado": "Enviada",
                                        "impuesto": "2.6", "vence": "2026-02-14", "terminos": "30",
                                        "impuesto_pct": "6.5"}])
    raw["Invoice_Items"] = _df("Invoice_Items", [{"id": "ITM-1", "num": "INV-1001", "sku": "A", "cantidad": "2",
                                                  "precio_unit": "20"}])
    raw["Transacciones"] = _df("Transacciones", [
        {"id": "TRX-1", "fecha": "2026-01-02", "cuenta": "1010", "descripcion": "Aporte inicial", "monto": "1000",
         "contrapartida": "3010", "tercero": "Yitsenia"},
        {"id": "TRX-2", "fecha": "2026-01-20", "cuenta": "1010", "descripcion": "Pago Amazon", "monto": "75",
         "contrapartida": "1050"},
        {"id": "TRX-3", "fecha": "2026-01-25", "cuenta": "1010", "descripcion": "Cobro INV-1001", "monto": "42.6",
         "contrapartida": "1100", "aplica_tipo": "FAC", "aplica_id": "INV-1001"},
        {"id": "TRX-4", "fecha": "2026-01-31", "cuenta": "1010", "descripcion": "Pago DR-15", "monto": "-2.6",
         "contrapartida": "2200"},
    ])
    return raw
