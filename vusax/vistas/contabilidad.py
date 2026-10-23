"""Contabilidad: plan de cuentas, asientos manuales, libro mayor, balanza y revisión de datos."""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from .. import db, reports
from ..config import SUBTIPOS, TIPO_ACTIVO, TIPO_CAPITAL, TIPO_COSTO, TIPO_GASTO, TIPO_INGRESO, TIPO_PASIVO
from . import comun
from .comun import usd
from .ventas import _f, _s

TIPOS = [TIPO_ACTIVO, TIPO_PASIVO, TIPO_CAPITAL, TIPO_INGRESO, TIPO_COSTO, TIPO_GASTO]


def _plan(d, coa) -> None:
    comun.tabla(coa)
    if comun.solo_lectura():
        return
    with st.expander("Add or edit an account"):
        sel = st.selectbox("Account", ["(new)"] + coa["codigo"].tolist(), key="cta_sel",
                           format_func=lambda c: c if c == "(new)" else f"{c} · {coa.set_index('codigo').loc[c, 'nombre']}")
        rec = coa[coa["codigo"] == sel].iloc[0] if sel != "(new)" else None
        with st.form(f"cta_form_{sel}"):
            c1, c2 = st.columns(2)
            codigo = c1.text_input("Code (4 digits)", value="" if rec is None else rec["codigo"], disabled=rec is not None)
            nombre = c2.text_input("Name", value="" if rec is None else rec["nombre"])
            tipo = c1.selectbox("Type", TIPOS, index=TIPOS.index(rec["tipo"]) if rec is not None and rec["tipo"] in TIPOS else 0)
            sub_opts = SUBTIPOS if rec is None or rec["subtipo"] in SUBTIPOS else SUBTIPOS + [rec["subtipo"]]
            sub = c2.selectbox("Subtype", sub_opts, index=sub_opts.index(rec["subtipo"]) if rec is not None and rec["subtipo"] in sub_opts else 0)
            activa = st.checkbox("Active", value=True if rec is None else str(rec["activa"]).upper() != "NO")
            ok = st.form_submit_button("Save account", type="primary")
        if ok:
            datos = {"nombre": nombre.strip(), "tipo": tipo, "subtipo": sub, "activa": "SI" if activa else "NO"}
            if not nombre.strip():
                st.error("The name is required.")
            elif rec is None:
                if not codigo.strip().isdigit() or len(codigo.strip()) != 4:
                    st.error("The code must be 4 digits.")
                elif codigo.strip() in set(coa["codigo"]):
                    st.error("That code already exists.")
                elif comun.intentar(db.guardar, "Cuentas", {"codigo": codigo.strip(), **datos}, ok="Account created."):
                    st.rerun()
            elif comun.intentar(db.modificar, "Cuentas", sel, datos, ok="Account updated."):
                st.rerun()


def _asientos(d, coa) -> None:
    st.caption("For opening balances, depreciation, corrections and anything that has no form of its own. "
               "The entry must balance: debits equal to credits.")
    a = d["Asientos"]
    if not comun.solo_lectura():
        n = st.session_state.setdefault("asi_n", 0)
        ops = comun.cuentas_opciones(coa)
        c1, c2 = st.columns(2)
        fecha = c1.date_input("Date", date.today(), key=f"asi_f_{n}")
        memo = c2.text_input("Description", key=f"asi_m_{n}")
        base = pd.DataFrame([{"cuenta": None, "debito": 0.0, "credito": 0.0, "memo": ""}] * 2)
        lin = st.data_editor(base, num_rows="dynamic", key=f"asi_l_{n}", width="stretch", column_config={
            "cuenta": st.column_config.SelectboxColumn("Account", options=list(ops), required=True,
                                                       help="Account code. See Chart of accounts."),
            "debito": st.column_config.NumberColumn("Debit", format="dollar", min_value=0.0),
            "credito": st.column_config.NumberColumn("Credit", format="dollar", min_value=0.0),
            "memo": st.column_config.TextColumn("Memo")})
        lin = lin[lin["cuenta"].notna()].fillna({"debito": 0.0, "credito": 0.0})
        deb, cre = round(lin["debito"].sum(), 2), round(lin["credito"].sum(), 2)
        x, y, z = st.columns(3)
        x.metric("Debits", usd(deb))
        y.metric("Credits", usd(cre))
        z.metric("Difference", usd(deb - cre), "Balanced" if abs(deb - cre) < 0.005 and deb > 0 else "Out of balance",
                 delta_color="off" if abs(deb - cre) < 0.005 and deb > 0 else "inverse")
        if st.button("Save entry", type="primary", disabled=abs(deb - cre) >= 0.005 or deb <= 0 or len(lin) < 2, key=f"asi_go_{n}"):
            num = f"AJ-{len(set(a['asiento'])) + 1001}"
            filas = [{"asiento": num, "fecha": fecha, "cuenta": r.cuenta, "debito": _f(r.debito), "credito": _f(r.credito),
                      "memo": _s(r.memo) or memo} for r in lin.itertuples()]
            if comun.intentar(db.guardar, "Asientos", filas, ok=f"Entry {num} saved."):
                st.session_state["asi_n"] = n + 1
                st.rerun()
    act = a[~a["anulado"]]
    if len(act):
        res = act.groupby("asiento").agg(fecha=("fecha", "min"), debito=("debito", "sum"), memo=("memo", "first")).reset_index()
        comun.tabla(res.sort_values("fecha", ascending=False), dinero=["debito"], fechas=["fecha"])
        if db.puede_escribir():
            sel = st.selectbox("Void an entry", [""] + res["asiento"].tolist(), key="anu_asi")
            if sel and st.button("Void entry", key="anu_asi_b"):
                if comun.intentar(db.anular, "Asientos", sel, col="asiento", ok="Entry voided."):
                    st.rerun()


def _mayor(j, coa) -> None:
    ops = comun.cuentas_opciones(coa, solo_activas=False)
    cta = comun.selector_cuenta("Account", ops, "mayor_cta")
    desde, hasta = comun.periodo("mayor")
    if cta:
        m = reports.libro_mayor(j, coa, cta, desde, hasta)
        comun.tabla(m, dinero=["debito", "credito", "saldo"], fechas=["fecha"])
        comun.descargas({"General Ledger": m}, f"ledger_{cta}", "mayor")


def _balanza(j, coa) -> None:
    al = pd.Timestamp(st.date_input("As of", date.today(), key="bal_al"))
    b = reports.balanza(j, coa, al)
    comun.tabla(b, dinero=["debito", "credito", "saldo_deudor", "saldo_acreedor"])
    if len(b):
        ok = abs(b["saldo_deudor"].sum() - b["saldo_acreedor"].sum()) < 0.01
        (st.success if ok else st.error)(f"Debit balances {usd(b['saldo_deudor'].sum())} · credit balances {usd(b['saldo_acreedor'].sum())}")
        comun.descargas({"Trial Balance": b}, f"trial_balance_{al:%Y%m%d}", "balanza")


def _revision(d, j, coa, inv) -> None:
    hallazgos = reports.revision_datos(d, j, coa, inv, pd.Timestamp(date.today()))
    if not hallazgos:
        st.success("I found no problems in the data.")
        return
    iconos = {"alto": ":material/error:", "medio": ":material/warning:", "bajo": ":material/info:"}
    for sev, msg in sorted(hallazgos, key=lambda x: ["alto", "medio", "bajo"].index(x[0])):
        st.markdown(f"{iconos[sev]} {msg}")


def contabilidad() -> None:
    comun.flash()
    L = db.libro()
    d, coa, j, inv = L["d"], L["coa"], L["j"], L["inv"]
    st.title("Accounting")
    t = st.tabs(["Chart of accounts", "Manual journal entries", "General ledger", "Trial balance", "Data review"])
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
