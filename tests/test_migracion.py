"""Simula la hoja de calculo de la version anterior y comprueba que migra sin perder datos."""

import hashlib
from datetime import date

import pandas as pd
import pytest
import streamlit as st

from vusax import auth, db, reports
from vusax.config import SCHEMAS


def _df(cols, filas):
    return pd.DataFrame(filas, columns=cols).astype(str)


@pytest.fixture()
def legado(monkeypatch):
    salt = "abc123"
    h = hashlib.pbkdf2_hmac("sha256", b"clave-vieja", salt.encode(), 100_000).hex()
    t = {
        "Usuarios": _df(["codigo", "nombre", "salt", "hash", "rol"], [["yit", "Yitsenia", salt, h, "admin"]]),
        "Productos": _df(["sku", "nombre", "categoria", "canal", "costo", "precio", "stock", "stock_min"],
                         [["P1", "Perfume", "Belleza", "Amazon FBA", "10", "25", "30", "5"],
                          ["P2", "Crema", "Belleza", "eBay", "4.5", "12", "12", "3"]]),
        "Clientes": _df(["id_cliente", "nombre", "email", "telefono", "direccion", "ciudad", "estado", "zip", "tipo"],
                        [["", "Cliente Viejo", "a@b.c", "", "", "", "", "", "Mayorista"]]),
        "Ingresos": _df(["fecha", "canal", "id_orden", "sku", "cantidad", "ingreso_bruto", "comisiones", "tarifas", "envio"],
                        [["2026-09-03", "Amazon FBA", "A1", "P1", "2", "$60.00", "9", "5", "0"],
                         ["9/4/2026", "TikTok Shop", "T1", "P2", "1", "12", "1.2", "0", "3"]]),
        "Gastos": _df(["fecha", "categoria", "proveedor", "descripcion", "monto", "metodo"],
                      [["2026-09-05", "Publicidad", "Meta", "Ads", "$120.50", "Tarjeta"],
                       ["9/6/2026", "Contabilidad", "CPA", "Mensual", "200", "Transferencia"]]),
        "Invoices": _df(["num", "fecha", "id_cliente", "cliente", "estado", "impuesto"],
                        [["INV-1001", "2026-09-07", "", "Cliente Viejo", "Enviada", "0"],
                         ["INV-1001", "2026-09-07", "", "Cliente Viejo", "Enviada", "0"]]),
        "Invoice_Items": _df(["num", "sku", "descripcion", "cantidad", "precio_unit"],
                             [["INV-1001", "P1", "Perfume", "3", "25"], ["INV-1001", "P2", "Crema", "2", "12"]]),
    }
    b = db.MemoryBackend(t)
    b.asegurar_esquema(SCHEMAS)
    db._migrar(b)
    monkeypatch.setattr(db, "backend", lambda: b)
    db.refrescar()
    st.session_state.clear()
    yield b
    db.refrescar()


def test_columnas_nuevas_e_ids(legado):
    head = legado.t["Ingresos"][0]
    assert head[:9] == ["fecha", "canal", "id_orden", "sku", "cantidad", "ingreso_bruto", "comisiones", "tarifas", "envio"]
    assert "id" in head and "anulado" in head
    ids = [r[head.index("id")] for r in legado.t["Ingresos"][1:]]
    assert all(i.startswith("ING-") for i in ids) and len(set(ids)) == 2
    cli = legado.t["Clientes"]
    assert cli[1][cli[0].index("id_cliente")].startswith("CLI-")
    itm = legado.t["Invoice_Items"]
    assert all(r[itm[0].index("id")].startswith("ITM-") for r in itm[1:])


def test_config_y_plan_sembrados(legado):
    cfg = {r[0]: r[1] for r in legado.t["Config"][1:]}
    assert cfg["inventario_inicio"] == date.today().isoformat()  # hay historia: el stock actual es la apertura de hoy
    assert cfg["empresa"] == "VUSAX LLC"
    assert len(legado.t["Cuentas"]) > 30
    db._migrar(legado)  # idempotente
    assert len(legado.t["Config"]) == len(SCHEMAS["Config"]) * 0 + len(cfg) + 1


def test_libro_con_datos_antiguos(legado):
    L = db.libro()
    d, j, coa = L["d"], L["j"], L["coa"]
    assert len(d["Invoices"]) == 1  # duplicado del formulario antiguo eliminado
    assert j["debito"].sum() == pytest.approx(j["credito"].sum(), abs=0.01)
    _, t = reports.estado_resultados(j, coa, "2026-01-01", "2026-12-31")
    # Ingresos: 60 + 12 (marketplace) + 75 + 24 (factura) = 171
    assert t["ingresos"] == pytest.approx(171.0)
    # Gastos: 9+5 + 1.2+3 de cargos, mas Meta 120.50 (6100) y CPA 200 (6300)
    assert t["gastos"] == pytest.approx(9 + 5 + 1.2 + 3 + 120.5 + 200)
    bal, tot = reports.balance_general(j, coa, "2026-12-31", "2026-01-01")
    assert tot["cuadra"]
    # Las ventas son anteriores a hoy (inicio de inventario): no mueven existencias
    inv = L["inv"].set_index("sku")
    assert inv.loc["P1", "existencias"] == 30 and inv.loc["P2", "existencias"] == 12


def test_login_con_hash_antiguo_y_mejora(legado):
    user, err = auth.verificar_login("yit", "clave-vieja")
    assert user and user["rol"] == "admin", err
    fila = legado.t["Usuarios"][1]
    head = legado.t["Usuarios"][0]
    assert fila[head.index("iter")] == auth.ITER_ACTUAL
    db.refrescar()
    assert auth.verificar_login("yit", "clave-vieja")[0]  # sigue entrando con el hash nuevo
    assert auth.verificar_login("yit", "otra")[0] is None


def test_bloqueo_tras_intentos(legado):
    for _ in range(auth.MAX_INTENTOS):
        assert auth.verificar_login("yit", "mala")[0] is None
    user, err = auth.verificar_login("yit", "clave-vieja")
    assert user is None and "Too many attempts" in err
    auth._intentos().clear()


def test_permisos_cierre_y_auditoria(legado):
    st.session_state["user"] = {"codigo": "lec", "nombre": "L", "rol": "read"}
    with pytest.raises(db.PermisoError):
        db.guardar("Gastos", {"fecha": date.today(), "categoria": "x", "monto": 1})
    st.session_state["user"] = {"codigo": "con", "nombre": "C", "rol": "accountant"}
    ids = db.guardar("Gastos", {"fecha": "2026-09-10", "categoria": "Software", "monto": 30, "metodo": "Tarjeta"})
    assert ids[0].startswith("GAS-")
    st.session_state["user"] = {"codigo": "adm", "nombre": "A", "rol": "admin"}
    db.guardar_config({"fecha_cierre": "2026-09-30"})
    with pytest.raises(ValueError, match="is closed"):
        db.guardar("Gastos", {"fecha": "2026-09-15", "categoria": "x", "monto": 1})
    with pytest.raises(ValueError, match="is closed"):
        db.anular("Gastos", ids[0])  # tampoco se pueden anular registros de periodos cerrados
    db.guardar("Gastos", {"fecha": "2026-10-02", "categoria": "x", "monto": 1})
    with pytest.raises(db.PermisoError):
        st.session_state["user"] = {"codigo": "con", "nombre": "C", "rol": "accountant"}
        db.guardar_config({"empresa": "Otra"})
    acciones = [r[2] for r in legado.t["Auditoria"][1:]]
    assert "crear" in acciones and "config" in acciones


def test_flujo_factura_cobro_y_anulacion(legado):
    st.session_state["user"] = {"codigo": "adm", "nombre": "A", "rol": "admin"}
    db.guardar("Invoices", {"num": "INV-1002", "fecha": "2026-10-01", "id_cliente": "", "cliente": "Cliente Viejo",
                            "estado": "Enviada", "impuesto": 6.5, "vence": "2026-10-31", "impuesto_pct": 6.5})
    db.guardar("Invoice_Items", [{"num": "INV-1002", "sku": "P1", "descripcion": "Perfume", "cantidad": 4, "precio_unit": 25}])
    db.guardar("Transacciones", {"fecha": "2026-10-05", "cuenta": "1010", "monto": 50, "contrapartida": "1100",
                                 "aplica_tipo": "FAC", "aplica_id": "INV-1002", "descripcion": "Cobro parcial"})
    from vusax import ledger
    ar = ledger.cuentas_por_cobrar(db.libro()["d"], pd.Timestamp("2026-10-10")).set_index("num")
    assert ar.loc["INV-1002", "total"] == pytest.approx(106.5)
    assert ar.loc["INV-1002", "saldo"] == pytest.approx(56.5)
    assert ar.loc["INV-1002", "estado"] == "Partial"
    # reemplazar lineas de un borrador
    db.reemplazar("Invoice_Items", "num", "INV-1002", [{"num": "INV-1002", "sku": "P1", "descripcion": "Perfume", "cantidad": 1, "precio_unit": 25}])
    assert len(db.libro()["d"]["Invoice_Items"][lambda x: x["num"] == "INV-1002"]) == 1
    db.anular("Invoices", "INV-1002")
    j = db.libro()["j"]
    assert "FAC:INV-1002" not in set(j["ref"])
    assert j["debito"].sum() == pytest.approx(j["credito"].sum(), abs=0.01)
