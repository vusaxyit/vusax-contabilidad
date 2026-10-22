"""Gastos, facturas de proveedores y pagos."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from .. import db, ledger
from . import comun
from .comun import usd
from .ventas import _f, _s


def _cuentas_gasto(coa) -> dict[str, str]:
    g = comun.cuentas_opciones(coa, tipos=["Gasto", "Costo"])
    retiros = comun.cuentas_opciones(coa, subtipos=["Retiros socio"])
    g.update({k: f"{v} (gasto personal del socio, no afecta la utilidad)" for k, v in retiros.items()})
    return g


def _tab_gastos(d, cfg, coa) -> None:
    if not comun.solo_lectura():
        with st.expander("Registrar gasto", expanded=False):
            cuentas = _cuentas_gasto(coa)
            pagos = comun.cuentas_opciones(coa, subtipos=["Banco", "Tarjeta"])
            with st.form("nuevo_gasto"):
                c1, c2 = st.columns(2)
                fecha = c1.date_input("Fecha", date.today())
                cuenta = c2.selectbox("Categoría (cuenta)", list(cuentas), format_func=lambda k: cuentas[k],
                                      index=list(cuentas).index("6900") if "6900" in cuentas else 0)
                prov = c1.text_input("Proveedor")
                pago = c2.selectbox("Pagado con", list(pagos), format_func=lambda k: pagos[k])
                desc = st.text_input("Descripción")
                monto = st.number_input("Monto", min_value=0.01, step=0.01)
                ok = st.form_submit_button("Registrar gasto", type="primary")
            if ok:
                es_tarjeta = coa.set_index("codigo").loc[pago, "subtipo"] == "Tarjeta"
                if comun.intentar(db.guardar, "Gastos", {
                        "fecha": fecha, "categoria": cuentas[cuenta].split(" · ", 1)[-1].split(" (")[0], "proveedor": prov,
                        "descripcion": desc, "monto": monto, "metodo": "Tarjeta" if es_tarjeta else "Banco",
                        "cuenta_gasto": cuenta, "cuenta_pago": pago}, ok="Gasto registrado."):
                    st.rerun()
    g = d["Gastos"]
    g = g[~g["anulado"]].sort_values("fecha", ascending=False)
    if g.empty:
        st.info("Todavía no hay gastos.")
        return
    g = g.assign(cuenta=g["cuenta_gasto"].where(g["cuenta_gasto"] != "", g["categoria"].map(ledger.mapear_categoria)))
    a, b = st.columns(2)
    a.metric("Total de gastos mostrados", usd(g["monto"].sum()))
    top = g.groupby("cuenta")["monto"].sum().sort_values(ascending=False)
    if len(top):
        nombre = coa.set_index("codigo")["nombre"].to_dict().get(top.index[0], top.index[0])
        b.metric("Categoría más grande", nombre, usd(top.iloc[0]), delta_color="off")
    comun.tabla(g[["id", "fecha", "cuenta", "categoria", "proveedor", "descripcion", "monto", "metodo"]].head(500),
                dinero=["monto"], fechas=["fecha"])
    if db.puede_escribir():
        sel = st.selectbox("Anular un gasto", [""] + g["id"].head(200).tolist(), key="anu_gasto")
        if sel and st.button("Anular gasto", key="anu_gasto_b"):
            if comun.intentar(db.anular, "Gastos", sel, ok="Gasto anulado."):
                st.rerun()


def _nueva_factura_prov(d, cfg, coa) -> None:
    n = st.session_state.setdefault("bill_n", 0)
    prov = d["Proveedores"][d["Proveedores"]["activo"].astype(str).str.upper() != "NO"]
    nuevo = "(proveedor nuevo)"
    c1, c2, c3 = st.columns(3)
    sel = c1.selectbox("Proveedor", [nuevo] + prov["id_proveedor"].tolist(), key=f"bill_p_{n}",
                       format_func=lambda v: v if v == nuevo else prov.set_index("id_proveedor").loc[v, "nombre"])
    nombre_nuevo = c1.text_input("Nombre del proveedor nuevo", key=f"bill_pn_{n}") if sel == nuevo else ""
    num = c2.text_input("Número de factura del proveedor", key=f"bill_num_{n}")
    fecha = c3.date_input("Fecha", date.today(), key=f"bill_f_{n}")
    term_def = 30
    if sel != nuevo:
        t = prov.set_index("id_proveedor").loc[sel, "terminos"]
        term_def = int(t) if t else 30
    plazo = c1.number_input("Días de plazo", min_value=0, value=term_def, key=f"bill_t_{n}_{sel}")
    notas = c2.text_input("Notas", key=f"bill_n_{n}")
    gastos = comun.cuentas_opciones(coa, tipos=["Gasto", "Costo"])
    skus = d["Productos"]["sku"].tolist()
    st.caption("Si indicas un SKU, la línea entra al inventario con su costo. Sin SKU, se registra como gasto en la cuenta elegida.")
    base = pd.DataFrame([{"sku": None, "descripcion": "", "cuenta": "6900", "cantidad": 1.0, "costo_unit": 0.0}])
    lineas = st.data_editor(base, num_rows="dynamic", key=f"bill_l_{n}", width="stretch", column_config={
        "sku": st.column_config.SelectboxColumn("SKU", options=skus, required=False),
        "descripcion": st.column_config.TextColumn("Descripción"),
        "cuenta": st.column_config.SelectboxColumn("Cuenta (si no es inventario)", options=list(gastos), required=True),
        "cantidad": st.column_config.NumberColumn("Cantidad", min_value=0.0, step=1.0),
        "costo_unit": st.column_config.NumberColumn("Costo unitario", format="dollar", min_value=0.0)})
    filas = []
    for r in lineas.to_dict("records"):
        if _f(r.get("cantidad")) and _f(r.get("costo_unit")):
            filas.append({"sku": _s(r.get("sku")), "descripcion": _s(r.get("descripcion")),
                          "cuenta": _s(r.get("cuenta")) or "6900", "cantidad": _f(r["cantidad"]),
                          "costo_unit": _f(r["costo_unit"])})
    total = round(sum(f["cantidad"] * f["costo_unit"] for f in filas), 2)
    st.metric("Total de la factura", usd(total))
    if st.button("Guardar factura de proveedor", type="primary", key=f"bill_go_{n}"):
        if not filas:
            st.error("Agrega al menos una línea con cantidad y costo.")
        elif sel == nuevo and not nombre_nuevo.strip():
            st.error("Escribe el nombre del proveedor.")
        else:
            try:
                if sel == nuevo:
                    id_prov = db.guardar("Proveedores", {"nombre": nombre_nuevo.strip(), "terminos": plazo, "activo": "SI"})[0]
                    nombre = nombre_nuevo.strip()
                else:
                    id_prov, nombre = sel, prov.set_index("id_proveedor").loc[sel, "nombre"]
                bid = db.guardar("Facturas_Prov", {"num": num, "fecha": fecha, "vence": fecha + timedelta(days=int(plazo)),
                                                   "id_proveedor": id_prov, "proveedor": nombre, "notas": notas})[0]
                db.guardar("Bill_Items", [{"id_bill": bid, **f} for f in filas])
            except Exception as e:
                st.error(str(e))
                return
            st.session_state["bill_n"] = n + 1
            st.session_state["_flash"] = f"Factura de proveedor guardada por {usd(total)}."
            st.rerun()


def _tab_facturas_prov(d, cfg, coa) -> None:
    ap = ledger.cuentas_por_pagar(d, ledger.hoy())
    if len(ap):
        a, b = st.columns(2)
        a.metric("Por pagar", usd(ap["saldo"].sum()))
        b.metric("Vencido", usd(ap.loc[ap["estado"] == "Vencida", "saldo"].sum()))
        comun.tabla(ap.sort_values("vence"), dinero=["total", "pagado", "saldo"], fechas=["fecha", "vence"],
                    enteros=["dias_vencido"])
    else:
        st.info("Todavía no hay facturas de proveedores.")
    if comun.solo_lectura():
        return
    with st.expander("Nueva factura de proveedor", expanded=not len(ap)):
        _nueva_factura_prov(d, cfg, coa)
    abiertas = ap[ap["saldo"] > 0.004]
    if len(abiertas):
        st.markdown("**Pagar una factura**")
        bid = st.selectbox("Factura", abiertas["id"].tolist(), key="pay_bill",
                           format_func=lambda i: f"{abiertas.set_index('id').loc[i, 'proveedor']} · {abiertas.set_index('id').loc[i, 'num']} · saldo {usd(abiertas.set_index('id').loc[i, 'saldo'])}")
        fila = abiertas.set_index("id").loc[bid]
        medios = comun.cuentas_opciones(coa, subtipos=["Banco", "Tarjeta"])
        with st.form("pago_bill"):
            c1, c2, c3 = st.columns(3)
            fecha = c1.date_input("Fecha de pago", date.today())
            monto = c2.number_input("Monto", min_value=0.01, value=float(fila["saldo"]), step=0.01)
            medio = c3.selectbox("Pagado desde", list(medios), format_func=lambda k: medios[k])
            ok = st.form_submit_button("Registrar pago", type="primary")
        if ok:
            if monto > fila["saldo"] + 0.005:
                st.error("El pago no puede superar el saldo.")
            elif comun.intentar(db.guardar, "Transacciones", {
                    "fecha": fecha, "cuenta": medio, "descripcion": f"Pago {fila['proveedor']} {fila['num']}",
                    "monto": -monto, "contrapartida": "2000", "tercero": fila["proveedor"], "aplica_tipo": "BILL",
                    "aplica_id": bid}, ok=f"Pago de {usd(monto)} registrado."):
                st.rerun()
    pend = ap[ap["pagado"] <= 0.004]
    if len(pend):
        sel = st.selectbox("Anular una factura sin pagos", [""] + pend["id"].tolist(), key="anu_bill",
                           format_func=lambda i: i if not i else f"{pend.set_index('id').loc[i, 'proveedor']} · {pend.set_index('id').loc[i, 'num']}")
        if sel and st.button("Anular factura de proveedor", key="anu_bill_b"):
            if comun.intentar(db.anular, "Facturas_Prov", sel, ok="Factura anulada."):
                st.rerun()


def gastos() -> None:
    comun.flash()
    L = db.libro()
    d, cfg, coa = L["d"], L["cfg"], L["coa"]
    st.title("Gastos y compras")
    t1, t2, t3 = st.tabs(["Gastos", "Facturas de proveedores", "Proveedores"])
    with t1:
        _tab_gastos(d, cfg, coa)
    with t2:
        _tab_facturas_prov(d, cfg, coa)
    with t3:
        if not comun.solo_lectura():
            comun.catalogo("Proveedores", [
                ("nombre", "Nombre", "text"), ("email", "Email", "text"), ("telefono", "Teléfono", "text"),
                ("direccion", "Dirección", "text"), ("terminos", "Días de plazo", "num"),
                ("es_1099", "Proveedor 1099", "sino"), ("notas", "Notas", "text"), ("activo", "Activo", "sino")],
                "prv", d, "proveedor", "nombre")
        p = d["Proveedores"]
        if len(p):
            comun.tabla(p.drop(columns=["notas"]), enteros=["terminos"])
