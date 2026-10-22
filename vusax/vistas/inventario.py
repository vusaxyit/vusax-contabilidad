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
    st.title("Inventario")
    t1, t2, t3 = st.tabs(["Existencias y valuación", "Productos", "Ajustes de inventario"])

    with t1:
        act = inv[inv["activo"].astype(str).str.upper() != "NO"]
        gl = float(reports.saldos(j, coa).set_index("codigo")["saldo"].get("1200", 0.0))
        a, b, c = st.columns(3)
        a.metric("Valor del inventario", usd(act["valor"].sum()))
        b.metric("Unidades en existencia", f"{act['existencias'].clip(lower=0).sum():,.0f}")
        c.metric("En el libro mayor (cuenta 1200)", usd(gl))
        solo_bajo = st.checkbox("Solo productos en o bajo el mínimo")
        v = act[(act["stock_min"] > 0) & (act["existencias"] <= act["stock_min"])] if solo_bajo else act
        if v.empty:
            st.info("No hay productos para mostrar.")
        else:
            comun.tabla(v[["sku", "nombre", "categoria", "existencias", "stock_min", "costo_prom", "valor", "precio"]],
                        dinero=["costo_prom", "valor", "precio"])
            comun.descargas({"Inventario": v}, "inventario", "inv")
        st.caption("El costo es promedio ponderado: cada compra de una factura de proveedor con SKU actualiza el costo y "
                   "cada venta descuenta existencias y registra el costo de ventas. Las existencias iniciales y su costo se "
                   f"toman de la hoja Productos a la fecha {cfg['inventario_inicio']}.")

    with t2:
        if not comun.solo_lectura():
            st.caption("Existencias iniciales y costo inicial son la posición de apertura a la fecha de inicio del inventario "
                       "(Ajustes). Después, compras, ventas y ajustes mueven las existencias automáticamente.")
            comun.catalogo("Productos", [
                ("sku", "SKU", "text"), ("nombre", "Nombre", "text"), ("categoria", "Categoría", "text"),
                ("canal", "Canal principal", "text"), ("costo", "Costo inicial por unidad", "num"),
                ("precio", "Precio de venta", "num"), ("stock", "Existencias iniciales", "num"),
                ("stock_min", "Stock mínimo", "num"), ("activo", "Activo", "sino")], "prod", d, "producto", "nombre")

    with t3:
        if not comun.solo_lectura():
            skus = d["Productos"]["sku"].tolist()
            with st.form("ajuste_inv"):
                c1, c2, c3 = st.columns(3)
                fecha = c1.date_input("Fecha", date.today())
                sku = c2.selectbox("SKU", skus) if skus else c2.text_input("SKU")
                cant = c3.number_input("Cantidad (negativa = merma o pérdida)", step=1.0, value=-1.0)
                motivo = st.text_input("Motivo")
                ok = st.form_submit_button("Registrar ajuste", type="primary")
            if ok:
                if cant == 0:
                    st.error("La cantidad no puede ser cero.")
                elif comun.intentar(db.guardar, "Ajustes_Inv", {"fecha": fecha, "sku": sku, "cantidad": cant, "motivo": motivo},
                                    ok="Ajuste registrado."):
                    st.rerun()
        aj = d["Ajustes_Inv"]
        aj = aj[~aj["anulado"]].sort_values("fecha", ascending=False)
        if len(aj):
            comun.tabla(aj[["id", "fecha", "sku", "cantidad", "motivo"]], fechas=["fecha"])
            if db.puede_escribir():
                sel = st.selectbox("Anular un ajuste", [""] + aj["id"].tolist(), key="anu_aj")
                if sel and st.button("Anular ajuste", key="anu_aj_b"):
                    if comun.intentar(db.anular, "Ajustes_Inv", sel, ok="Ajuste anulado."):
                        st.rerun()
