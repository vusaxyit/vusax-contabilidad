"""Panel principal."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .. import db, ledger, reports
from . import comun
from .comun import usd


def _delta(actual: float, previo: float) -> str | None:
    if abs(previo) < 0.005:
        return None
    return f"{(actual - previo) / abs(previo) * 100:+.0f}% vs periodo anterior"


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
    efectivo = s.loc[s["subtipo"] == "Banco", "saldo"].sum()
    por_liquidar = s.loc[s["subtipo"] == "Por liquidar", "saldo"].sum()
    ar, ap = ledger.cuentas_por_cobrar(d, hasta), ledger.cuentas_por_pagar(d, hasta)
    vencido_ar = ar.loc[(ar["saldo"] > 0.004) & (ar["dias_vencido"] > 0), "saldo"].sum()

    with st.container(border=True):
        a, b, c, e = st.columns(4)
        a.metric("Ingresos", usd(t["ingresos"]), _delta(t["ingresos"], p["ingresos"]))
        b.metric("Utilidad bruta", usd(t["utilidad_bruta"]), _delta(t["utilidad_bruta"], p["utilidad_bruta"]))
        c.metric("Gastos", usd(t["gastos"]), _delta(t["gastos"], p["gastos"]), delta_color="inverse")
        e.metric("Utilidad neta", usd(t["utilidad_neta"]), _delta(t["utilidad_neta"], p["utilidad_neta"]))
    with st.container(border=True):
        a, b, c, e = st.columns(4)
        a.metric("Efectivo en bancos", usd(efectivo))
        b.metric("Por liquidar (marketplaces)", usd(por_liquidar))
        c.metric("Por cobrar", usd(ar["saldo"].sum()), f"{usd(vencido_ar)} vencido" if vencido_ar > 0 else None,
                 delta_color="inverse")
        e.metric("Por pagar", usd(ap["saldo"].sum()))

    izq, der = st.columns([3, 2])
    with izq:
        serie = reports.serie_mensual(j, coa, desde, hasta)
        if serie.empty:
            st.info("Todavía no hay movimientos en este periodo.")
        else:
            fig = go.Figure()
            fig.add_bar(x=serie["mes"], y=serie["ingresos"], name="Ingresos", marker_color="#2E7D6B")
            fig.add_bar(x=serie["mes"], y=serie["costo"] + serie["gastos"], name="Costo y gastos", marker_color="#C9824B")
            fig.add_scatter(x=serie["mes"], y=serie["utilidad"], name="Utilidad neta", mode="lines+markers",
                            line=dict(color="#23395B", width=3))
            fig.update_layout(title="Ingresos, costos y utilidad por mes", barmode="group", height=360,
                              margin=dict(l=10, r=10, t=50, b=10), legend=dict(orientation="h", y=-0.15))
            fig.update_xaxes(type="category")
            st.plotly_chart(fig, width="stretch")
    with der:
        det, _ = reports.estado_resultados(j, coa, desde, hasta)
        ing = det[det["seccion"] == "Ingresos"].sort_values("monto")
        if len(ing):
            fig = go.Figure(go.Bar(x=ing["monto"], y=ing["nombre"], orientation="h", marker_color="#2E7D6B"))
            fig.update_layout(title="Ingresos por canal", height=360, margin=dict(l=10, r=10, t=50, b=10))
            st.plotly_chart(fig, width="stretch")

    st.subheader("Requiere atención")
    avisos: list[str] = []
    venc = ar[(ar["saldo"] > 0.004) & (ar["dias_vencido"] > 0)]
    if len(venc):
        avisos.append(f"**{len(venc)} factura(s) de clientes vencidas** por {usd(venc['saldo'].sum())}.")
    prox = ap[(ap["saldo"] > 0.004) & (ap["dias_vencido"] > -8)]
    if len(prox):
        avisos.append(f"**{len(prox)} factura(s) de proveedores** vencidas o por vencer en 7 días: {usd(prox['saldo'].sum())}.")
    bajo = inv[(inv["activo"].astype(str).str.upper() != "NO") & (inv["stock_min"] > 0) & (inv["existencias"] <= inv["stock_min"])]
    if len(bajo):
        avisos.append(f"**{len(bajo)} producto(s) en o bajo el stock mínimo**: " + ", ".join(bajo["sku"].head(6)) + ".")
    imp = float(s.set_index("codigo")["saldo"].get("2200", 0.0))
    if imp > 0.004:
        avisos.append(f"**Impuesto de ventas por pagar al FL DOR**: {usd(imp)}.")
    problemas = reports.revision_datos(d, j, coa, inv, hasta)
    altos = [m for sev, m in problemas if sev == "alto"]
    if problemas:
        avisos.append(f"**Revisión de datos**: {len(problemas)} observación(es), {len(altos)} importante(s). "
                      "Entra a Contabilidad > Revisión de datos.")
    cierre = cfg.get("fecha_cierre", "").strip()
    avisos.append(f"Periodo cerrado hasta **{cierre}**." if cierre else "No hay fecha de cierre configurada.")
    for a in avisos:
        st.markdown(f"- {a}")
