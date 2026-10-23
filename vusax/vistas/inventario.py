"""Inventario y productos."""

from __future__ import annotations

from datetime import date

import streamlit as st

from .. import db, reports
from . import comun
from .comun import usd


def inventario() -> None:
    comun.flash()
    L = db.libro()
    d, cfg, coa, inv, j = L["d"], L["cfg"], L["coa"], L["inv"], L["j"]
    st.title("Inventory")
    t1, t2, t3 = st.tabs(["Stock and valuation", "Products", "Inventory adjustments"])

    with t1:
        act = inv[inv["activo"].astype(str).str.upper() != "NO"]
        gl = float(reports.saldos(j, coa).set_index("codigo")["saldo"].get("1200", 0.0))
        a, b, c = st.columns(3)
        a.metric("Inventory value", usd(act["valor"].sum()))
        b.metric("Units on hand", f"{act['existencias'].clip(lower=0).sum():,.0f}")
        c.metric("In the general ledger (account 1200)", usd(gl))
        solo_bajo = st.checkbox("Only products at or below minimum")
        v = act[(act["stock_min"] > 0) & (act["existencias"] <= act["stock_min"])] if solo_bajo else act
        if v.empty:
            st.info("No products to show.")
        else:
            comun.tabla(v[["sku", "nombre", "categoria", "existencias", "stock_min", "costo_prom", "valor", "precio"]],
                        dinero=["costo_prom", "valor", "precio"])
            comun.descargas({"Inventory": v}, "inventory", "inv")
        st.caption("Cost is weighted average: every purchase on a vendor bill with a SKU updates the cost, and every "
                   "sale reduces stock and records cost of goods sold. Opening stock and its cost come from the "
                   f"Productos sheet as of {cfg['inventario_inicio']}.")

    with t2:
        if not comun.solo_lectura():
            st.caption("Opening stock and opening cost are the position as of the inventory start date (Settings). "
                       "After that, purchases, sales and adjustments move stock automatically.")
            comun.catalogo("Productos", [
                ("sku", "SKU", "text"), ("nombre", "Name", "text"), ("categoria", "Category", "text"),
                ("canal", "Main channel", "text"), ("costo", "Opening cost per unit", "num"),
                ("precio", "Sale price", "num"), ("stock", "Opening stock", "num"),
                ("stock_min", "Minimum stock", "num"), ("activo", "Active", "sino")], "prod", d, "product", "nombre")

    with t3:
        if not comun.solo_lectura():
            skus = d["Productos"]["sku"].tolist()
            with st.form("ajuste_inv"):
                c1, c2, c3 = st.columns(3)
                fecha = c1.date_input("Date", date.today())
                sku = c2.selectbox("SKU", skus) if skus else c2.text_input("SKU")
                cant = c3.number_input("Quantity (negative = shrinkage or loss)", step=1.0, value=-1.0)
                motivo = st.text_input("Reason")
                ok = st.form_submit_button("Record adjustment", type="primary")
            if ok:
                if cant == 0:
                    st.error("The quantity cannot be zero.")
                elif comun.intentar(db.guardar, "Ajustes_Inv", {"fecha": fecha, "sku": sku, "cantidad": cant, "motivo": motivo},
                                    ok="Adjustment recorded."):
                    st.rerun()
        aj = d["Ajustes_Inv"]
        aj = aj[~aj["anulado"]].sort_values("fecha", ascending=False)
        if len(aj):
            comun.tabla(aj[["id", "fecha", "sku", "cantidad", "motivo"]], fechas=["fecha"])
            if db.puede_escribir():
                sel = st.selectbox("Void an adjustment", [""] + aj["id"].tolist(), key="anu_aj")
                if sel and st.button("Void adjustment", key="anu_aj_b"):
                    if comun.intentar(db.anular, "Ajustes_Inv", sel, ok="Adjustment voided."):
                        st.rerun()
