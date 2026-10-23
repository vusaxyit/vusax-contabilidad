"""Panel principal."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .. import db, ledger, reports
from ..config import SUB_BANCO
from . import comun
from .comun import usd


def _delta(actual: float, previo: float) -> str | None:
    if abs(previo) < 0.005:
        return None
    return f"{(actual - previo) / abs(previo) * 100:+.0f}% vs previous period"


def panel() -> None:
    comun.flash()
    L = db.libro()
    d, j, coa, inv, cfg = L["d"], L["j"], L["coa"], L["inv"], L["cfg"]
    st.title(cfg["empresa"])
    desde, hasta = comun.periodo("panel")
    dias = (hasta - desde).days + 1
    ant_h, ant_d = desde - pd.Timedelta(days=1), desde - pd.Timedelta(days=dias)

    _, t = reports.estado_resultados(j, coa, desde, hasta)
    _, p = reports.estado_resultados(j, coa, ant_d, ant_h)
    s = reports.saldos(j, coa, hasta=hasta)
    efectivo = s.loc[s["subtipo"] == SUB_BANCO, "saldo"].sum()
    por_liquidar = s.loc[s["subtipo"] == "Pending Settlement", "saldo"].sum()
    ar, ap = ledger.cuentas_por_cobrar(d, hasta), ledger.cuentas_por_pagar(d, hasta)
    vencido_ar = ar.loc[(ar["saldo"] > 0.004) & (ar["dias_vencido"] > 0), "saldo"].sum()

    with st.container(border=True):
        a, b, c, e = st.columns(4)
        a.metric("Revenue", usd(t["ingresos"]), _delta(t["ingresos"], p["ingresos"]))
        b.metric("Gross profit", usd(t["utilidad_bruta"]), _delta(t["utilidad_bruta"], p["utilidad_bruta"]))
        c.metric("Expenses", usd(t["gastos"]), _delta(t["gastos"], p["gastos"]), delta_color="inverse")
        e.metric("Net income", usd(t["utilidad_neta"]), _delta(t["utilidad_neta"], p["utilidad_neta"]))
    with st.container(border=True):
        a, b, c, e = st.columns(4)
        a.metric("Cash in banks", usd(efectivo))
        b.metric("Pending settlement (marketplaces)", usd(por_liquidar))
        c.metric("Receivable", usd(ar["saldo"].sum()), f"{usd(vencido_ar)} overdue" if vencido_ar > 0 else None,
                 delta_color="inverse")
        e.metric("Payable", usd(ap["saldo"].sum()))

    izq, der = st.columns([3, 2])
    with izq:
        serie = reports.serie_mensual(j, coa, desde, hasta)
        if serie.empty:
            st.info("No activity in this period yet.")
        else:
            fig = go.Figure()
            fig.add_bar(x=serie["mes"], y=serie["ingresos"], name="Revenue", marker_color="#2E7D6B")
            fig.add_bar(x=serie["mes"], y=serie["costo"] + serie["gastos"], name="Cost and expenses", marker_color="#C9824B")
            fig.add_scatter(x=serie["mes"], y=serie["utilidad"], name="Net income", mode="lines+markers",
                            line=dict(color="#23395B", width=3))
            fig.update_layout(title="Revenue, cost and profit by month", barmode="group", height=360,
                              margin=dict(l=10, r=10, t=50, b=10), legend=dict(orientation="h", y=-0.15))
            fig.update_xaxes(type="category")
            st.plotly_chart(fig, width="stretch")
    with der:
        det, _ = reports.estado_resultados(j, coa, desde, hasta)
        ing = det[det["seccion"] == "Income"].sort_values("monto")
        if len(ing):
            fig = go.Figure(go.Bar(x=ing["monto"], y=ing["nombre"], orientation="h", marker_color="#2E7D6B"))
            fig.update_layout(title="Revenue by channel", height=360, margin=dict(l=10, r=10, t=50, b=10))
            st.plotly_chart(fig, width="stretch")

    st.subheader("Needs attention")
    avisos: list[str] = []
    venc = ar[(ar["saldo"] > 0.004) & (ar["dias_vencido"] > 0)]
    if len(venc):
        avisos.append(f"**{len(venc)} overdue customer invoice(s)** for {usd(venc['saldo'].sum())}.")
    prox = ap[(ap["saldo"] > 0.004) & (ap["dias_vencido"] > -8)]
    if len(prox):
        avisos.append(f"**{len(prox)} vendor bill(s)** overdue or due within 7 days: {usd(prox['saldo'].sum())}.")
    bajo = inv[(inv["activo"].astype(str).str.upper() != "NO") & (inv["stock_min"] > 0) & (inv["existencias"] <= inv["stock_min"])]
    if len(bajo):
        avisos.append(f"**{len(bajo)} product(s) at or below minimum stock**: " + ", ".join(bajo["sku"].head(6)) + ".")
    imp = float(s.set_index("codigo")["saldo"].get("2200", 0.0))
    if imp > 0.004:
        avisos.append(f"**Sales tax payable to the FL DOR**: {usd(imp)}.")
    problemas = reports.revision_datos(d, j, coa, inv, hasta)
    altos = [m for sev, m in problemas if sev == "alto"]
    if problemas:
        avisos.append(f"**Data review**: {len(problemas)} finding(s), {len(altos)} important. "
                      "Go to Accounting > Data review.")
    cierre = cfg.get("fecha_cierre", "").strip()
    avisos.append(f"Period closed through **{cierre}**." if cierre else "No closing date is set.")
    for a in avisos:
        st.markdown(f"- {a}")
