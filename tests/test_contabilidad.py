import pandas as pd
import pytest

from vusax import ledger, reports
from vusax.config import CONFIG_DEFECTO
from vusax.demo import datos_demo_crudos


def armar(raw=None, **cfg_extra):
    d = ledger.preparar(raw if raw is not None else datos_demo_crudos())
    cfg = ledger.leer_config(d["Config"])
    cfg.update(cfg_extra)
    j, inv, ev = ledger.construir_diario(d, cfg)
    coa = reports.plan_df(d)
    return d, cfg, j, inv, ev, coa


def test_conversiones():
    s = pd.Series(["$1,234.50", "(10)", "", "abc", "7"])
    assert ledger.num(s).tolist() == [1234.5, -10.0, 0.0, 0.0, 7.0]
    f = ledger.parse_fecha(pd.Series(["2026-01-05", "01/05/2026", "46027", "", "x"]))
    assert f.iloc[0] == pd.Timestamp("2026-01-05")
    assert f.iloc[1] == pd.Timestamp("2026-01-05")
    assert f.iloc[2] == pd.Timestamp("2026-01-05")
    assert f.iloc[3:].isna().all()
    assert ledger.codigo("1010.0") == "1010"
    assert ledger.mapear_categoria("Publicidad Facebook") == "6100"
    assert ledger.mapear_categoria("6300") == "6300"
    assert ledger.mapear_categoria("cosa rara") == "6900"


def test_diario_cuadra_y_costo_promedio():
    d, cfg, j, inv, ev, coa = armar()
    assert j["debito"].sum() == pytest.approx(j["credito"].sum(), abs=0.01)
    por_ref = j.groupby("ref")[["debito", "credito"]].sum()
    assert ((por_ref["debito"] - por_ref["credito"]).abs() < 0.01).all()
    a = inv.set_index("sku").loc["A"]
    # 10 @5 de apertura + 10 @7 comprados = promedio 6; se venden 4 + 2
    assert a["costo_prom"] == pytest.approx(6.0)
    assert a["existencias"] == pytest.approx(14.0)
    assert a["valor"] == pytest.approx(84.0)
    cogs = ev[ev["tipo"] == "venta"]["valor"].sum()
    assert cogs == pytest.approx(36.0)


def test_estado_de_resultados():
    d, cfg, j, inv, ev, coa = armar()
    det, t = reports.estado_resultados(j, coa, "2026-01-01", "2026-12-31")
    assert t["ingresos"] == pytest.approx(140.0)
    assert t["costo"] == pytest.approx(36.0)
    assert t["gastos"] == pytest.approx(75.0)
    assert t["utilidad_neta"] == pytest.approx(29.0)
    # La utilidad no incluye aportes de socios ni impuesto de ventas
    assert "Aporte" not in " ".join(det["nombre"])


def test_balance_cuadra_y_saldos():
    d, cfg, j, inv, ev, coa = armar()
    bal, tot = reports.balance_general(j, coa, "2026-12-31", "2026-01-01")
    assert tot["cuadra"]
    assert tot["activos"] == pytest.approx(1199.0)
    assert tot["pasivos"] == pytest.approx(120.0)
    assert tot["capital"] == pytest.approx(1079.0)
    s = reports.saldos(j, coa, hasta="2026-12-31").set_index("codigo")["saldo"]
    assert s["1010"] == pytest.approx(1115.0)
    assert s["1100"] == pytest.approx(0.0)
    assert s["2200"] == pytest.approx(0.0)


def test_flujo_de_efectivo_cuadra():
    d, cfg, j, inv, ev, coa = armar()
    det, t = reports.flujo_efectivo(j, coa, "2026-01-01", "2026-12-31")
    assert t["cuadra"]
    assert t["efectivo_final"] == pytest.approx(1115.0)
    assert t["financiamiento"] == pytest.approx(1000.0)  # el saldo inicial de 2000 queda fuera del periodo


def test_cuentas_por_cobrar_y_pagar():
    d, cfg, j, inv, ev, coa = armar()
    ar = ledger.cuentas_por_cobrar(d, pd.Timestamp("2026-02-20"))
    assert ar.loc[0, "total"] == pytest.approx(42.6)
    assert ar.loc[0, "saldo"] == pytest.approx(0.0)
    assert ar.loc[0, "estado"] == "Paid"
    ar_antes = ledger.cuentas_por_cobrar(d, pd.Timestamp("2026-01-20"))
    assert ar_antes.loc[0, "saldo"] == pytest.approx(42.6)
    ap = ledger.cuentas_por_pagar(d, pd.Timestamp("2026-02-20"))
    assert ap.loc[0, "saldo"] == pytest.approx(70.0)
    assert ap.loc[0, "estado"] == "Overdue"  # vence 2026-02-04
    ag = reports.antiguedad(ap, "proveedor")
    assert ag.loc[ag["proveedor"] == "TOTAL", "Total"].iloc[0] == pytest.approx(70.0)


def test_anulados_no_entran():
    raw = datos_demo_crudos()
    raw["Gastos"].loc[0, "anulado"] = "SI"
    d, cfg, j, inv, ev, coa = armar(raw)
    _, t = reports.estado_resultados(j, coa, "2026-01-01", "2026-12-31")
    assert t["gastos"] == pytest.approx(25.0)
    assert j["debito"].sum() == pytest.approx(j["credito"].sum(), abs=0.01)


def test_ventas_antes_del_inicio_de_inventario_no_mueven_existencias():
    d, cfg, j, inv, ev, coa = armar(inventario_inicio="2026-03-01")
    a = inv.set_index("sku").loc["A"]
    # Todo es anterior al inicio: existencias = apertura (10), valoradas a 5
    assert a["existencias"] == pytest.approx(10.0)
    assert a["valor"] == pytest.approx(50.0)
    assert j["debito"].sum() == pytest.approx(j["credito"].sum(), abs=0.01)
    gl = reports.saldos(j, coa, hasta="2026-12-31").set_index("codigo")["saldo"]
    assert gl["1200"] == pytest.approx(50.0)  # el libro coincide con la valoracion


def test_encabezados_de_factura_duplicados_del_formulario_antiguo():
    raw = datos_demo_crudos()
    dup = raw["Invoices"].iloc[[0]].copy()
    raw["Invoices"] = pd.concat([raw["Invoices"], dup], ignore_index=True)
    d, cfg, j, inv, ev, coa = armar(raw)
    assert len(d["Invoices"]) == 1
    _, t = reports.estado_resultados(j, coa, "2026-01-01", "2026-12-31")
    assert t["ingresos"] == pytest.approx(140.0)


def test_capital_de_socios_reparte_utilidad():
    d, cfg, j, inv, ev, coa = armar()
    cap = reports.capital_socios(j, coa, cfg, "2026-01-01", "2026-12-31").set_index("socio")
    assert cap.loc["Yitsenia", "utilidad_asignada"] == pytest.approx(14.5)
    assert cap.loc["Azael Garcia", "utilidad_asignada"] == pytest.approx(14.5)
    assert cap.loc["Yitsenia", "aportes"] == pytest.approx(1000.0)
    assert cap.loc["TOTAL", "capital_final"] == pytest.approx(1079.0)


def test_impuesto_de_ventas_separa_marketplace():
    d, cfg, j, inv, ev, coa = armar()
    t = reports.impuesto_ventas(d, j, coa, "2026-01-01", "2026-12-31")
    f = t.iloc[0]
    assert f["ventas_marketplace"] == pytest.approx(100.0)
    assert f["ventas_facturas_gravables"] == pytest.approx(40.0)
    assert f["impuesto_cobrado"] == pytest.approx(2.6)
    assert f["impuesto_pagado"] == pytest.approx(2.6)


def test_marketplace_ignora_impuesto_y_directo_lo_registra():
    raw = datos_demo_crudos()
    nuevo = {c: "" for c in raw["Ingresos"].columns}
    nuevo.update({"id": "ING-X", "fecha": "2026-01-11", "canal": "Sitio web", "sku": "A", "cantidad": "1",
                  "ingreso_bruto": "20", "impuesto_cobrado": "1.30"})
    raw["Ingresos"] = pd.concat([raw["Ingresos"], pd.DataFrame([nuevo])], ignore_index=True)
    d, cfg, j, inv, ev, coa = armar(raw)
    s = reports.saldos(j, coa, hasta="2026-12-31").set_index("codigo")["saldo"]
    assert s["2200"] == pytest.approx(1.30)
    assert s["1070"] == pytest.approx(21.30)


def test_revision_detecta_problemas():
    raw = datos_demo_crudos()
    raw["Gastos"].loc[0, "fecha"] = "no es fecha"
    raw["Invoices"].loc[0, "estado"] = "Pagada"
    raw["Transacciones"] = raw["Transacciones"][raw["Transacciones"]["aplica_tipo"] != "FAC"]
    d, cfg, j, inv, ev, coa = armar(raw)
    msgs = " | ".join(m for _, m in reports.revision_datos(d, j, coa, inv, pd.Timestamp("2026-12-31")))
    assert "no valid date" in msgs
    assert "marked Paid" in msgs


def test_asiento_manual_descuadrado_se_reporta():
    raw = datos_demo_crudos()
    fila = {c: "" for c in raw["Asientos"].columns}
    fila.update({"id": "ASI-1", "asiento": "AJ-1", "fecha": "2026-02-01", "cuenta": "6900", "debito": "10"})
    raw["Asientos"] = pd.DataFrame([fila])
    d, cfg, j, inv, ev, coa = armar(raw)
    msgs = " | ".join(m for _, m in reports.revision_datos(d, j, coa, inv, pd.Timestamp("2026-12-31")))
    assert "unbalanced" in msgs


def test_libro_mayor_saldo_corrido():
    d, cfg, j, inv, ev, coa = armar()
    m = reports.libro_mayor(j, coa, "1010", "2026-01-01", "2026-12-31")
    assert m["saldo"].iloc[-1] == pytest.approx(1115.0)
    assert m["saldo"].iloc[0] == 0.0


def test_siguiente_numero():
    assert ledger.siguiente_numero("INV-", ["INV-1001", "INV-1005", "X-9999"]) == "INV-1006"
    assert ledger.siguiente_numero("INV-", []) == "INV-1001"
