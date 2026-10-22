"""Reportes financieros."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from .. import db, ledger, reports
from . import comun
from .comun import usd

REPORTES = [
    "Income Statement", "Income Statement by Month", "Balance Sheet", "Cash Flow",
    "Accounts Receivable Aging", "Accounts Payable Aging", "Profitability by Channel",
    "Profitability by Product", "Sales Tax (DR-15 worksheet)", "Partners' Equity",
]

# seccion del balance -> clave del diccionario de totales
SECCIONES_BALANCE = [("Assets", "activos"), ("Liabilities", "pasivos"), ("Equity", "capital")]


def _seccion(det: pd.DataFrame, titulo: str, col_monto="monto") -> None:
    x = det[det["seccion"] == titulo]
    if x.empty:
        return
    st.markdown(f"**{titulo}**")
    comun.tabla(x[["codigo", "nombre", col_monto]].rename(columns={"nombre": "cuenta"}), dinero=[col_monto])


def reportes() -> None:
    L = db.libro()
    d, j, coa, inv, ev, cfg = L["d"], L["j"], L["coa"], L["inv"], L["ev"], L["cfg"]
    st.title("Reports")
    nombre = st.selectbox("Report", REPORTES)
    tag = nombre.split(" (")[0].lower().replace(" ", "_").replace("'", "")

    if nombre == "Balance Sheet":
        al = pd.Timestamp(st.date_input("As of", pd.Timestamp.today()))
        det, t = reports.balance_general(j, coa, al, al.replace(month=1, day=1))
        for sec, clave in SECCIONES_BALANCE:
            _seccion(det, sec)
            st.markdown(f"Total {sec.lower()}: **{usd(t[clave])}**")
        (st.success if t["cuadra"] else st.error)(
            "Assets = Liabilities + Equity" if t["cuadra"] else "Out of balance: check Accounting > Data review.")
        comun.descargas({"Balance Sheet": det}, f"balance_sheet_{al:%Y%m%d}", tag)
        return

    if nombre.startswith("Accounts "):
        al = pd.Timestamp(st.date_input("Balances as of", pd.Timestamp.today()))
        cobrar = "Receivable" in nombre
        abiertas = ledger.cuentas_por_cobrar(d, al) if cobrar else ledger.cuentas_por_pagar(d, al)
        col = "cliente" if cobrar else "proveedor"
        ag = reports.antiguedad(abiertas, col)
        comun.tabla(ag, dinero=[c for c in ag.columns if c != col])
        st.markdown("**Open document detail**")
        ab = abiertas[abiertas["saldo"] > 0.004]
        comun.tabla(ab, dinero=["total", "pagado", "saldo"], fechas=["fecha", "vence"], enteros=["dias_vencido"])
        comun.descargas({"Aging": ag, "Detail": ab}, f"{tag}_{al:%Y%m%d}", tag)
        return

    desde, hasta = comun.periodo(tag)

    if nombre == "Income Statement":
        det, t = reports.estado_resultados(j, coa, desde, hasta)
        _seccion(det, "Income")
        _seccion(det, "Cost of Sales")
        st.markdown(f"**Gross profit: {usd(t['utilidad_bruta'])}**")
        _seccion(det, "Expenses")
        (st.success if t["utilidad_neta"] >= 0 else st.error)(f"Net income: {usd(t['utilidad_neta'])}")
        comun.descargas({"Income Statement": det}, f"income_statement_{desde:%Y%m%d}_{hasta:%Y%m%d}", tag)
    elif nombre == "Income Statement by Month":
        m = reports.resultados_mensual(j, coa, desde, hasta)
        if m.empty:
            st.info("No activity in this period.")
        else:
            comun.tabla(m, dinero=[c for c in m.columns if c not in ("seccion", "codigo", "nombre")])
            comun.descargas({"By Month": m}, f"income_statement_monthly_{desde:%Y%m%d}", tag)
    elif nombre == "Cash Flow":
        det, t = reports.flujo_efectivo(j, coa, desde, hasta)
        comun.tabla(det, dinero=["monto"])
        a, b, c, e = st.columns(4)
        a.metric("Operating", usd(t["operacion"]))
        b.metric("Financing", usd(t["financiamiento"]))
        c.metric("Opening cash", usd(t["efectivo_inicial"]))
        e.metric("Ending cash", usd(t["efectivo_final"]))
        if not t["cuadra"]:
            st.error("Cash flow does not reconcile with the cash in banks. Check the manual journal entries.")
        comun.descargas({"Cash Flow": det}, f"cash_flow_{desde:%Y%m%d}_{hasta:%Y%m%d}", tag)
    elif nombre.startswith("Profitability"):
        por = "canal" if "Channel" in nombre else "sku"
        e2 = ev[(ev["fecha"] >= desde) & (ev["fecha"] <= hasta)]
        r = reports.rentabilidad(e2, por)
        if r.empty:
            st.info("No product sales in this period.")
        else:
            comun.tabla(r, dinero=["ingresos", "cargos", "costo", "margen"], pct=["margen_pct"])
            fig = px.bar(r.head(15), x=por, y="margen", title="Margin (revenue less referral fees, fulfillment fees, shipping and cost)")
            st.plotly_chart(fig, width="stretch")
            comun.descargas({"Profitability": r}, f"profitability_{por}_{desde:%Y%m%d}", tag)
        st.caption("Each row uses the average inventory cost at the time of the sale.")
    elif nombre.startswith("Sales Tax"):
        tabla = reports.impuesto_ventas(d, j, coa, desde, hasta)
        if tabla.empty:
            st.info("No sales in this period.")
        else:
            comun.tabla(tabla, dinero=[c for c in tabla.columns if c != "mes"])
            comun.descargas({"Sales Tax": tabla}, f"sales_tax_{desde:%Y%m%d}", tag)
        saldo = float(reports.saldos(j, coa, hasta=hasta).set_index("codigo")["saldo"].get("2200", 0.0))
        st.metric("Payable balance in account 2200", usd(saldo))
        st.caption("Worksheet to prepare the DR-15. Amazon, eBay, Walmart and TikTok Shop sales are shown separately "
                   "because the platform collects and remits the tax. Confirm the rate, the county and the boxes with "
                   "the Florida Department of Revenue or with your accountant before filing.")
    elif nombre == "Partners' Equity":
        cap = reports.capital_socios(j, coa, cfg, desde, hasta)
        comun.tabla(cap, dinero=["capital_inicial", "aportes", "utilidad_asignada", "retiros", "capital_final"],
                    pct=["participacion_pct"])
        comun.descargas({"Partners Equity": cap}, f"partners_equity_{desde:%Y%m%d}", tag)
        st.caption("Profit is split using the percentages in Settings > Partners. Basis for Form 1065 and the K-1s.")
