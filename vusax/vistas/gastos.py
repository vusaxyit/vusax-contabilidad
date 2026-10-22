"""Gastos, facturas de proveedores y pagos."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from .. import db, ledger
from ..config import SUB_BANCO, TIPO_COSTO, TIPO_GASTO
from . import comun
from .comun import usd
from .ventas import _f, _s

SUB_PAGO = [SUB_BANCO, "Credit Card"]


def _cuentas_gasto(coa) -> dict[str, str]:
    g = comun.cuentas_opciones(coa, tipos=[TIPO_GASTO, TIPO_COSTO])
    retiros = comun.cuentas_opciones(coa, subtipos=["Partner Draws"])
    g.update({k: f"{v} (partner's personal expense, does not affect profit)" for k, v in retiros.items()})
    return g


def _tab_gastos(d, cfg, coa) -> None:
    if not comun.solo_lectura():
        with st.expander("Record expense", expanded=False):
            cuentas = _cuentas_gasto(coa)
            pagos = comun.cuentas_opciones(coa, subtipos=SUB_PAGO)
            with st.form("nuevo_gasto"):
                c1, c2 = st.columns(2)
                fecha = c1.date_input("Date", date.today())
                cuenta = c2.selectbox("Category (account)", list(cuentas), format_func=lambda k: cuentas[k],
                                      index=list(cuentas).index("6900") if "6900" in cuentas else 0)
                prov = c1.text_input("Vendor")
                pago = c2.selectbox("Paid with", list(pagos), format_func=lambda k: pagos[k])
                desc = st.text_input("Description")
                monto = st.number_input("Amount", min_value=0.01, step=0.01)
                ok = st.form_submit_button("Record expense", type="primary")
            if ok:
                es_tarjeta = coa.set_index("codigo").loc[pago, "subtipo"] == "Credit Card"
                if comun.intentar(db.guardar, "Gastos", {
                        "fecha": fecha, "categoria": cuentas[cuenta].split(" · ", 1)[-1].split(" (")[0], "proveedor": prov,
                        "descripcion": desc, "monto": monto, "metodo": "Card" if es_tarjeta else "Bank",
                        "cuenta_gasto": cuenta, "cuenta_pago": pago}, ok="Expense recorded."):
                    st.rerun()
    g = d["Gastos"]
    g = g[~g["anulado"]].sort_values("fecha", ascending=False)
    if g.empty:
        st.info("No expenses yet.")
        return
    g = g.assign(cuenta=g["cuenta_gasto"].where(g["cuenta_gasto"] != "", g["categoria"].map(ledger.mapear_categoria)))
    a, b = st.columns(2)
    a.metric("Total expenses shown", usd(g["monto"].sum()))
    top = g.groupby("cuenta")["monto"].sum().sort_values(ascending=False)
    if len(top):
        nombre = coa.set_index("codigo")["nombre"].to_dict().get(top.index[0], top.index[0])
        b.metric("Largest category", nombre, usd(top.iloc[0]), delta_color="off")
    comun.tabla(g[["id", "fecha", "cuenta", "categoria", "proveedor", "descripcion", "monto", "metodo"]].head(500),
                dinero=["monto"], fechas=["fecha"])
    if db.puede_escribir():
        sel = st.selectbox("Void an expense", [""] + g["id"].head(200).tolist(), key="anu_gasto")
        if sel and st.button("Void expense", key="anu_gasto_b"):
            if comun.intentar(db.anular, "Gastos", sel, ok="Expense voided."):
                st.rerun()


def _nueva_factura_prov(d, cfg, coa) -> None:
    n = st.session_state.setdefault("bill_n", 0)
    prov = d["Proveedores"][d["Proveedores"]["activo"].astype(str).str.upper() != "NO"]
    nuevo = "(new vendor)"
    c1, c2, c3 = st.columns(3)
    sel = c1.selectbox("Vendor", [nuevo] + prov["id_proveedor"].tolist(), key=f"bill_p_{n}",
                       format_func=lambda v: v if v == nuevo else prov.set_index("id_proveedor").loc[v, "nombre"])
    nombre_nuevo = c1.text_input("New vendor name", key=f"bill_pn_{n}") if sel == nuevo else ""
    num = c2.text_input("Vendor bill number", key=f"bill_num_{n}")
    fecha = c3.date_input("Date", date.today(), key=f"bill_f_{n}")
    term_def = 30
    if sel != nuevo:
        t = prov.set_index("id_proveedor").loc[sel, "terminos"]
        term_def = int(t) if t else 30
    plazo = c1.number_input("Payment terms (days)", min_value=0, value=term_def, key=f"bill_t_{n}_{sel}")
    notas = c2.text_input("Notes", key=f"bill_n_{n}")
    gastos = comun.cuentas_opciones(coa, tipos=[TIPO_GASTO, TIPO_COSTO])
    skus = d["Productos"]["sku"].tolist()
    st.caption("If you enter a SKU, the line goes into inventory at its cost. Without a SKU, it is recorded as an expense in the account you choose.")
    base = pd.DataFrame([{"sku": None, "descripcion": "", "cuenta": "6900", "cantidad": 1.0, "costo_unit": 0.0}])
    lineas = st.data_editor(base, num_rows="dynamic", key=f"bill_l_{n}", width="stretch", column_config={
        "sku": st.column_config.SelectboxColumn("SKU", options=skus, required=False),
        "descripcion": st.column_config.TextColumn("Description"),
        "cuenta": st.column_config.SelectboxColumn("Account (if not inventory)", options=list(gastos), required=True),
        "cantidad": st.column_config.NumberColumn("Qty", min_value=0.0, step=1.0),
        "costo_unit": st.column_config.NumberColumn("Unit cost", format="dollar", min_value=0.0)})
    filas = []
    for r in lineas.to_dict("records"):
        if _f(r.get("cantidad")) and _f(r.get("costo_unit")):
            filas.append({"sku": _s(r.get("sku")), "descripcion": _s(r.get("descripcion")),
                          "cuenta": _s(r.get("cuenta")) or "6900", "cantidad": _f(r["cantidad"]),
                          "costo_unit": _f(r["costo_unit"])})
    total = round(sum(f["cantidad"] * f["costo_unit"] for f in filas), 2)
    st.metric("Bill total", usd(total))
    if st.button("Save vendor bill", type="primary", key=f"bill_go_{n}"):
        if not filas:
            st.error("Add at least one line with quantity and cost.")
        elif sel == nuevo and not nombre_nuevo.strip():
            st.error("Enter the vendor name.")
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
            st.session_state["_flash"] = f"Vendor bill saved for {usd(total)}."
            st.rerun()


def _tab_facturas_prov(d, cfg, coa) -> None:
    ap = ledger.cuentas_por_pagar(d, ledger.hoy())
    if len(ap):
        a, b = st.columns(2)
        a.metric("Payable", usd(ap["saldo"].sum()))
        b.metric("Overdue", usd(ap.loc[ap["estado"] == "Overdue", "saldo"].sum()))
        comun.tabla(ap.sort_values("vence"), dinero=["total", "pagado", "saldo"], fechas=["fecha", "vence"],
                    enteros=["dias_vencido"])
    else:
        st.info("No vendor bills yet.")
    if comun.solo_lectura():
        return
    with st.expander("New vendor bill", expanded=not len(ap)):
        _nueva_factura_prov(d, cfg, coa)
    abiertas = ap[ap["saldo"] > 0.004]
    if len(abiertas):
        st.markdown("**Pay a bill**")
        bid = st.selectbox("Bill", abiertas["id"].tolist(), key="pay_bill",
                           format_func=lambda i: f"{abiertas.set_index('id').loc[i, 'proveedor']} · {abiertas.set_index('id').loc[i, 'num']} · balance {usd(abiertas.set_index('id').loc[i, 'saldo'])}")
        fila = abiertas.set_index("id").loc[bid]
        medios = comun.cuentas_opciones(coa, subtipos=SUB_PAGO)
        with st.form("pago_bill"):
            c1, c2, c3 = st.columns(3)
            fecha = c1.date_input("Payment date", date.today())
            monto = c2.number_input("Amount", min_value=0.01, value=float(fila["saldo"]), step=0.01)
            medio = c3.selectbox("Paid from", list(medios), format_func=lambda k: medios[k])
            ok = st.form_submit_button("Record payment", type="primary")
        if ok:
            if monto > fila["saldo"] + 0.005:
                st.error("The payment cannot exceed the balance.")
            elif comun.intentar(db.guardar, "Transacciones", {
                    "fecha": fecha, "cuenta": medio, "descripcion": f"Payment {fila['proveedor']} {fila['num']}",
                    "monto": -monto, "contrapartida": "2000", "tercero": fila["proveedor"], "aplica_tipo": "BILL",
                    "aplica_id": bid}, ok=f"Payment of {usd(monto)} recorded."):
                st.rerun()
    pend = ap[ap["pagado"] <= 0.004]
    if len(pend):
        sel = st.selectbox("Void a bill with no payments", [""] + pend["id"].tolist(), key="anu_bill",
                           format_func=lambda i: i if not i else f"{pend.set_index('id').loc[i, 'proveedor']} · {pend.set_index('id').loc[i, 'num']}")
        if sel and st.button("Void vendor bill", key="anu_bill_b"):
            if comun.intentar(db.anular, "Facturas_Prov", sel, ok="Bill voided."):
                st.rerun()


def gastos() -> None:
    comun.flash()
    L = db.libro()
    d, cfg, coa = L["d"], L["cfg"], L["coa"]
    st.title("Expenses & Purchases")
    t1, t2, t3 = st.tabs(["Expenses", "Vendor bills", "Vendors"])
    with t1:
        _tab_gastos(d, cfg, coa)
    with t2:
        _tab_facturas_prov(d, cfg, coa)
    with t3:
        if not comun.solo_lectura():
            comun.catalogo("Proveedores", [
                ("nombre", "Name", "text"), ("email", "Email", "text"), ("telefono", "Phone", "text"),
                ("direccion", "Address", "text"), ("terminos", "Payment terms (days)", "num"),
                ("es_1099", "1099 vendor", "sino"), ("notas", "Notes", "text"), ("activo", "Active", "sino")],
                "prv", d, "vendor", "nombre")
        p = d["Proveedores"]
        if len(p):
            comun.tabla(p.drop(columns=["notas"]), enteros=["terminos"])
