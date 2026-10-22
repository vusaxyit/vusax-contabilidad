"""Contabilidad: plan de cuentas, asientos manuales, libro mayor, balanza y revisión de datos."""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from .. import db, reports
from . import comun
from .comun import usd
from .ventas import _f, _s

TIPOS = ["Activo", "Pasivo", "Capital", "Ingreso", "Costo", "Gasto"]
SUBTIPOS = ["Banco", "Tarjeta", "Por liquidar", "Por cobrar", "Inventario", "Por clasificar", "Por pagar", "Impuestos",
            "Capital socio", "Retiros socio", "Apertura", "Ventas", "COGS", "Operativo", "Otros", "Otro activo", "Otro pasivo"]


def _plan(d, coa) -> None:
    comun.tabla(coa)
    if comun.solo_lectura():
        return
    with st.expander("Agregar o editar una cuenta"):
        sel = st.selectbox("Cuenta", ["(nueva)"] + coa["codigo"].tolist(), key="cta_sel",
                           format_func=lambda c: c if c == "(nueva)" else f"{c} · {coa.set_index('codigo').loc[c, 'nombre']}")
        rec = coa[coa["codigo"] == sel].iloc[0] if sel != "(nueva)" else None
        with st.form(f"cta_form_{sel}"):
            c1, c2 = st.columns(2)
            codigo = c1.text_input("Código (4 dígitos)", value="" if rec is None else rec["codigo"], disabled=rec is not None)
            nombre = c2.text_input("Nombre", value="" if rec is None else rec["nombre"])
            tipo = c1.selectbox("Tipo", TIPOS, index=TIPOS.index(rec["tipo"]) if rec is not None and rec["tipo"] in TIPOS else 0)
            sub_opts = SUBTIPOS if rec is None or rec["subtipo"] in SUBTIPOS else SUBTIPOS + [rec["subtipo"]]
            sub = c2.selectbox("Subtipo", sub_opts, index=sub_opts.index(rec["subtipo"]) if rec is not None and rec["subtipo"] in sub_opts else 0)
            activa = st.checkbox("Activa", value=True if rec is None else str(rec["activa"]).upper() != "NO")
            ok = st.form_submit_button("Guardar cuenta", type="primary")
        if ok:
            datos = {"nombre": nombre.strip(), "tipo": tipo, "subtipo": sub, "activa": "SI" if activa else "NO"}
            if not nombre.strip():
                st.error("El nombre es obligatorio.")
            elif rec is None:
                if not codigo.strip().isdigit() or len(codigo.strip()) != 4:
                    st.error("El código debe tener 4 dígitos.")
                elif codigo.strip() in set(coa["codigo"]):
                    st.error("Ese código ya existe.")
                elif comun.intentar(db.guardar, "Cuentas", {"codigo": codigo.strip(), **datos}, ok="Cuenta creada."):
                    st.rerun()
            elif comun.intentar(db.modificar, "Cuentas", sel, datos, ok="Cuenta actualizada."):
                st.rerun()


def _asientos(d, coa) -> None:
    st.caption("Para saldos iniciales, depreciación, correcciones y cualquier movimiento que no tenga su propio formulario. "
               "El asiento debe cuadrar: débitos iguales a créditos.")
    a = d["Asientos"]
    if not comun.solo_lectura():
        n = st.session_state.setdefault("asi_n", 0)
        ops = comun.cuentas_opciones(coa)
        c1, c2 = st.columns(2)
        fecha = c1.date_input("Fecha", date.today(), key=f"asi_f_{n}")
        memo = c2.text_input("Descripción", key=f"asi_m_{n}")
        base = pd.DataFrame([{"cuenta": None, "debito": 0.0, "credito": 0.0, "memo": ""}] * 2)
        lin = st.data_editor(base, num_rows="dynamic", key=f"asi_l_{n}", width="stretch", column_config={
            "cuenta": st.column_config.SelectboxColumn("Cuenta", options=list(ops), required=True,
                                                       help="Código de la cuenta. Ver Plan de cuentas."),
            "debito": st.column_config.NumberColumn("Débito", format="dollar", min_value=0.0),
            "credito": st.column_config.NumberColumn("Crédito", format="dollar", min_value=0.0),
            "memo": st.column_config.TextColumn("Nota")})
        lin = lin[lin["cuenta"].notna()].fillna({"debito": 0.0, "credito": 0.0})
        deb, cre = round(lin["debito"].sum(), 2), round(lin["credito"].sum(), 2)
        x, y, z = st.columns(3)
        x.metric("Débitos", usd(deb))
        y.metric("Créditos", usd(cre))
        z.metric("Diferencia", usd(deb - cre), "Cuadra" if abs(deb - cre) < 0.005 and deb > 0 else "No cuadra",
                 delta_color="off" if abs(deb - cre) < 0.005 and deb > 0 else "inverse")
        if st.button("Guardar asiento", type="primary", disabled=abs(deb - cre) >= 0.005 or deb <= 0 or len(lin) < 2, key=f"asi_go_{n}"):
            num = f"AJ-{len(set(a['asiento'])) + 1001}"
            filas = [{"asiento": num, "fecha": fecha, "cuenta": r.cuenta, "debito": _f(r.debito), "credito": _f(r.credito),
                      "memo": _s(r.memo) or memo} for r in lin.itertuples()]
            if comun.intentar(db.guardar, "Asientos", filas, ok=f"Asiento {num} guardado."):
                st.session_state["asi_n"] = n + 1
                st.rerun()
    act = a[~a["anulado"]]
    if len(act):
        res = act.groupby("asiento").agg(fecha=("fecha", "min"), debito=("debito", "sum"), memo=("memo", "first")).reset_index()
        comun.tabla(res.sort_values("fecha", ascending=False), dinero=["debito"], fechas=["fecha"])
        if db.puede_escribir():
            sel = st.selectbox("Anular un asiento", [""] + res["asiento"].tolist(), key="anu_asi")
            if sel and st.button("Anular asiento", key="anu_asi_b"):
                if comun.intentar(db.anular, "Asientos", sel, col="asiento", ok="Asiento anulado."):
                    st.rerun()


def _mayor(j, coa) -> None:
    ops = comun.cuentas_opciones(coa, solo_activas=False)
    cta = comun.selector_cuenta("Cuenta", ops, "mayor_cta")
    desde, hasta = comun.periodo("mayor")
    if cta:
        m = reports.libro_mayor(j, coa, cta, desde, hasta)
        comun.tabla(m, dinero=["debito", "credito", "saldo"], fechas=["fecha"])
        comun.descargas({"Mayor": m}, f"mayor_{cta}", "mayor")


def _balanza(j, coa) -> None:
    al = pd.Timestamp(st.date_input("Al", date.today(), key="bal_al"))
    b = reports.balanza(j, coa, al)
    comun.tabla(b, dinero=["debito", "credito", "saldo_deudor", "saldo_acreedor"])
    if len(b):
        ok = abs(b["saldo_deudor"].sum() - b["saldo_acreedor"].sum()) < 0.01
        (st.success if ok else st.error)(f"Saldos deudores {usd(b['saldo_deudor'].sum())} · acreedores {usd(b['saldo_acreedor'].sum())}")
        comun.descargas({"Balanza": b}, f"balanza_{al:%Y%m%d}", "balanza")


def _revision(d, j, coa, inv) -> None:
    hallazgos = reports.revision_datos(d, j, coa, inv, pd.Timestamp(date.today()))
    if not hallazgos:
        st.success("No encontré problemas en los datos.")
        return
    iconos = {"alto": ":material/error:", "medio": ":material/warning:", "bajo": ":material/info:"}
    for sev, msg in sorted(hallazgos, key=lambda x: ["alto", "medio", "bajo"].index(x[0])):
        st.markdown(f"{iconos[sev]} {msg}")


def contabilidad() -> None:
    comun.flash()
    L = db.libro()
    d, coa, j, inv = L["d"], L["coa"], L["j"], L["inv"]
    st.title("Contabilidad")
    t = st.tabs(["Plan de cuentas", "Asientos manuales", "Libro mayor", "Balanza de comprobación", "Revisión de datos"])
    with t[0]:
        _plan(d, coa)
    with t[1]:
        _asientos(d, coa)
    with t[2]:
        _mayor(j, coa)
    with t[3]:
        _balanza(j, coa)
    with t[4]:
        _revision(d, j, coa, inv)
