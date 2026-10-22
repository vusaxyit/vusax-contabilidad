"""Reportes financieros."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from .. import db, ledger, reports
from . import comun
from .comun import usd

REPORTES = [
    "Estado de resultados", "Estado de resultados por mes", "Balance general", "Flujo de efectivo",
    "Cuentas por cobrar (antigüedad)", "Cuentas por pagar (antigüedad)", "Rentabilidad por canal",
    "Rentabilidad por producto", "Impuesto de ventas (apoyo DR-15)", "Capital de los socios",
]


def _seccion(det: pd.DataFrame, titulo: str, col_monto="monto") -> None:
    x = det[det["seccion"] == titulo]
    if x.empty:
        return
    st.markdown(f"**{titulo}**")
    comun.tabla(x[["codigo", "nombre", col_monto]].rename(columns={"nombre": "cuenta"}), dinero=[col_monto])


def reportes() -> None:
    L = db.libro()
    d, j, coa, inv, ev, cfg = L["d"], L["j"], L["coa"], L["inv"], L["ev"], L["cfg"]
    st.title("Reportes")
    nombre = st.selectbox("Reporte", REPORTES)
    tag = nombre.split(" (")[0].lower().replace(" ", "_")

    if nombre == "Balance general":
        al = pd.Timestamp(st.date_input("Al", pd.Timestamp.today()))
        det, t = reports.balance_general(j, coa, al, al.replace(month=1, day=1))
        for sec in ("Activos", "Pasivos", "Capital"):
            _seccion(det, sec)
            st.markdown(f"Total {sec.lower()}: **{usd(t[sec.lower()])}**")
        (st.success if t["cuadra"] else st.error)(
            "Activos = Pasivos + Capital" if t["cuadra"] else "El balance no cuadra: revisa Contabilidad > Revisión de datos.")
        comun.descargas({"Balance": det}, f"balance_{al:%Y%m%d}", tag)
        return

    if nombre.startswith("Cuentas por"):
        al = pd.Timestamp(st.date_input("Saldos al", pd.Timestamp.today()))
        cobrar = "cobrar" in nombre
        abiertas = ledger.cuentas_por_cobrar(d, al) if cobrar else ledger.cuentas_por_pagar(d, al)
        col = "cliente" if cobrar else "proveedor"
        ag = reports.antiguedad(abiertas, col)
        comun.tabla(ag, dinero=[c for c in ag.columns if c != col])
        st.markdown("**Detalle de documentos abiertos**")
        ab = abiertas[abiertas["saldo"] > 0.004]
        comun.tabla(ab, dinero=["total", "pagado", "saldo"], fechas=["fecha", "vence"], enteros=["dias_vencido"])
        comun.descargas({"Antiguedad": ag, "Detalle": ab}, f"{tag}_{al:%Y%m%d}", tag)
        return

    desde, hasta = comun.periodo(tag)

    if nombre == "Estado de resultados":
        det, t = reports.estado_resultados(j, coa, desde, hasta)
        _seccion(det, "Ingresos")
        _seccion(det, "Costo de ventas")
        st.markdown(f"**Utilidad bruta: {usd(t['utilidad_bruta'])}**")
        _seccion(det, "Gastos")
        (st.success if t["utilidad_neta"] >= 0 else st.error)(f"Utilidad neta: {usd(t['utilidad_neta'])}")
        comun.descargas({"Resultados": det}, f"resultados_{desde:%Y%m%d}_{hasta:%Y%m%d}", tag)
    elif nombre == "Estado de resultados por mes":
        m = reports.resultados_mensual(j, coa, desde, hasta)
        if m.empty:
            st.info("Sin movimientos en el periodo.")
        else:
            comun.tabla(m, dinero=[c for c in m.columns if c not in ("seccion", "codigo", "nombre")])
            comun.descargas({"Resultados por mes": m}, f"resultados_mes_{desde:%Y%m%d}", tag)
    elif nombre == "Flujo de efectivo":
        det, t = reports.flujo_efectivo(j, coa, desde, hasta)
        comun.tabla(det, dinero=["monto"])
        a, b, c, e = st.columns(4)
        a.metric("Operación", usd(t["operacion"]))
        b.metric("Financiamiento", usd(t["financiamiento"]))
        c.metric("Efectivo inicial", usd(t["efectivo_inicial"]))
        e.metric("Efectivo final", usd(t["efectivo_final"]))
        if not t["cuadra"]:
            st.error("El flujo no concilia con el efectivo en bancos. Revisa los asientos manuales.")
        comun.descargas({"Flujo": det}, f"flujo_{desde:%Y%m%d}_{hasta:%Y%m%d}", tag)
    elif nombre.startswith("Rentabilidad"):
        por = "canal" if "canal" in nombre else "sku"
        e2 = ev[(ev["fecha"] >= desde) & (ev["fecha"] <= hasta)]
        r = reports.rentabilidad(e2, por)
        if r.empty:
            st.info("No hay ventas con producto en el periodo.")
        else:
            comun.tabla(r, dinero=["ingresos", "cargos", "costo", "margen"], pct=["margen_pct"])
            fig = px.bar(r.head(15), x=por, y="margen", title="Margen (ingresos menos comisiones, tarifas, envío y costo)")
            st.plotly_chart(fig, width="stretch")
            comun.descargas({"Rentabilidad": r}, f"rentabilidad_{por}_{desde:%Y%m%d}", tag)
        st.caption("Las ventas de cada fila incluyen el costo promedio del inventario al momento de la venta.")
    elif nombre.startswith("Impuesto de ventas"):
        tabla = reports.impuesto_ventas(d, j, coa, desde, hasta)
        if tabla.empty:
            st.info("Sin ventas en el periodo.")
        else:
            comun.tabla(tabla, dinero=[c for c in tabla.columns if c != "mes"])
            comun.descargas({"Impuesto de ventas": tabla}, f"impuesto_ventas_{desde:%Y%m%d}", tag)
        saldo = float(reports.saldos(j, coa, hasta=hasta).set_index("codigo")["saldo"].get("2200", 0.0))
        st.metric("Saldo por pagar en la cuenta 2200", usd(saldo))
        st.caption("Ayuda de trabajo para preparar el DR-15. Las ventas de Amazon, eBay, Walmart y TikTok Shop se "
                   "muestran aparte porque la plataforma cobra y remite el impuesto. Confirma tasa, condado y "
                   "casillas con el Departamento de Ingresos de Florida o con tu contador antes de presentar.")
    elif nombre == "Capital de los socios":
        cap = reports.capital_socios(j, coa, cfg, desde, hasta)
        comun.tabla(cap, dinero=["capital_inicial", "aportes", "utilidad_asignada", "retiros", "capital_final"],
                    pct=["participacion_pct"])
        comun.descargas({"Capital socios": cap}, f"capital_socios_{desde:%Y%m%d}", tag)
        st.caption("La utilidad se reparte según los porcentajes de Ajustes > Socios. Base para el Formulario 1065 y los K-1.")
