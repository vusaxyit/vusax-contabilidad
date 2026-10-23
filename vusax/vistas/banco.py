"""Banco: registro de movimientos, importación de extractos y conciliación."""

from __future__ import annotations

import io
from datetime import date

import pandas as pd
import streamlit as st

from .. import db, ledger, reports
from ..config import SUB_BANCO, TIPO_ACTIVO
from . import comun
from .comun import usd

SUB_MEDIOS = [SUB_BANCO, "Credit Card"]


def _opciones_contra(coa, cfg, tipo: str) -> dict[str, str]:
    if tipo.startswith("Marketplace"):
        return comun.cuentas_opciones(coa, subtipos=["Pending Settlement"])
    if tipo == "Partner contribution":
        o = comun.cuentas_opciones(coa, subtipos=["Partner Capital"])
        nombres = {"3010": cfg["socio1"], "3020": cfg["socio2"]}
        return {k: f"{k} · {nombres[k]} capital" if k in nombres else v for k, v in o.items()}
    if tipo.startswith("Partner draw"):
        o = comun.cuentas_opciones(coa, subtipos=["Partner Draws"])
        nombres = {"3110": cfg["socio1"], "3120": cfg["socio2"]}
        return {k: f"{k} · {nombres[k]} draws" if k in nombres else v for k, v in o.items()}
    if tipo.startswith("Sales tax payment"):
        return comun.cuentas_opciones(coa, subtipos=["Taxes"])
    return {k: v for k, v in comun.cuentas_opciones(coa).items()}


TIPOS = {
    "Marketplace or processor deposit": 1, "Partner contribution": 1, "Other deposit": 1,
    "Partner draw or distribution": -1, "Sales tax payment (DR-15)": -1, "Other withdrawal": -1,
    "Transfer between accounts": -1,
}


def _saldos_cuentas(coa, j) -> None:
    s = reports.saldos(j, coa)
    s = s[s["subtipo"].isin(SUB_MEDIOS + ["Pending Settlement"])]
    if s.empty:
        return
    cols = st.columns(min(len(s), 5))
    for col, r in zip(cols, s.itertuples()):
        col.metric(r.nombre, usd(r.saldo))


def _tab_registro(d, cfg, coa, j) -> None:
    _saldos_cuentas(coa, j)
    if not comun.solo_lectura():
        with st.expander("New transaction", expanded=False):
            tipo = st.selectbox("Transaction type", list(TIPOS), key="trx_tipo")
            medios = comun.cuentas_opciones(coa, subtipos=SUB_MEDIOS)
            with st.form(f"trx_{tipo}"):
                c1, c2, c3 = st.columns(3)
                fecha = c1.date_input("Date", date.today())
                cuenta = c2.selectbox("From account" if tipo.startswith("Transfer") else "Bank account",
                                      list(medios), format_func=lambda k: medios[k])
                monto = c3.number_input("Amount", min_value=0.01, step=0.01)
                if tipo.startswith("Transfer"):
                    destinos = {k: v for k, v in comun.cuentas_opciones(coa, subtipos=SUB_MEDIOS).items()}
                    contra = st.selectbox("To account (includes credit card payments)", list(destinos),
                                          format_func=lambda k: destinos[k])
                else:
                    ops = _opciones_contra(coa, cfg, tipo)
                    contra = st.selectbox("Offset account", list(ops), format_func=lambda k: ops[k]) if ops else ""
                desc = st.text_input("Description")
                tercero = st.text_input("Contact or reference")
                ok = st.form_submit_button("Save transaction", type="primary")
            if ok:
                if tipo.startswith("Transfer") and contra == cuenta:
                    st.error("The source and destination accounts must be different.")
                elif not contra:
                    st.error("Choose the offset account.")
                else:
                    signo = TIPOS[tipo]
                    if comun.intentar(db.guardar, "Transacciones", {
                            "fecha": fecha, "cuenta": cuenta, "descripcion": desc or tipo, "monto": signo * monto,
                            "contrapartida": contra, "tercero": tercero}, ok="Transaction saved."):
                        st.rerun()
    tx = d["Transacciones"]
    tx = tx[~tx["anulado"]].sort_values("fecha", ascending=False)
    if tx.empty:
        st.info("No bank transactions yet.")
        return
    nombres = coa.set_index("codigo")["nombre"].to_dict()
    v = tx.assign(cuenta_nombre=tx["cuenta"].map(nombres), contrapartida_nombre=tx["contrapartida"].map(nombres))
    comun.tabla(v[["id", "fecha", "cuenta_nombre", "descripcion", "monto", "contrapartida_nombre", "tercero", "aplica_tipo",
                   "aplica_id"]].head(500), dinero=["monto"], fechas=["fecha"])
    if db.puede_escribir():
        sel = st.selectbox("Void a transaction", [""] + v["id"].head(200).tolist(), key="anu_trx")
        if sel and st.button("Void transaction", key="anu_trx_b"):
            if comun.intentar(db.anular, "Transacciones", sel, ok="Transaction voided."):
                st.rerun()


# ───────────────────────────── Importar extracto ─────────────────────────────

def _leer_extracto(archivo) -> pd.DataFrame:
    texto = archivo.getvalue().decode("utf-8-sig", errors="replace")
    lineas = texto.splitlines()
    inicio = next((i for i, l in enumerate(lineas[:40]) if any(k in l.lower() for k in ("date", "fecha"))
                   and any(k in l.lower() for k in ("amount", "monto", "debit", "credit", "importe", "debito", "credito"))), 0)
    df = pd.read_csv(io.StringIO("\n".join(lineas[inicio:])), dtype=str).fillna("")
    cols = {c.strip().lower(): c for c in df.columns}
    pick = lambda *n: next((cols[k] for k in n if k in cols), None)
    f, de = pick("fecha", "date", "posting date", "transaction date", "fecha de operación"), \
        pick("descripcion", "descripción", "description", "memo", "detalle", "payee", "name")
    m, deb, cre = pick("monto", "amount", "importe"), pick("debit", "debito", "débito", "withdrawals", "retiros"), \
        pick("credit", "credito", "crédito", "deposits", "depositos", "depósitos")
    if not f or not de or not (m or deb or cre):
        raise ValueError("I could not find date, description and amount columns (or debit and credit).")
    if m:
        monto = ledger.num(df[m])
    elif deb and cre:
        monto = ledger.num(df[cre]) - ledger.num(df[deb]).abs()
    elif cre:
        monto = ledger.num(df[cre])
    else:
        monto = -ledger.num(df[deb]).abs()
    out = pd.DataFrame({"fecha": ledger.parse_fecha(df[f]), "descripcion": df[de].str.strip(), "monto": monto})
    return out[out["fecha"].notna() & (out["monto"] != 0)].reset_index(drop=True)


def _regla(desc: str, reglas: pd.DataFrame) -> str:
    t = desc.lower()
    for r in reglas.itertuples():
        if str(r.palabra).strip() and str(r.palabra).strip().lower() in t:
            return r.cuenta
    return ""


def _tab_importar(d, cfg, coa) -> None:
    if comun.solo_lectura():
        return
    medios = comun.cuentas_opciones(coa, subtipos=SUB_MEDIOS)
    cuenta = st.selectbox("Statement account", list(medios), format_func=lambda k: medios[k], key="imp_cta")
    arch = st.file_uploader("Bank statement (CSV)", type="csv", key="imp_banco")
    st.caption("Works with Bank of America and Chase CSV files. Before importing expenses from this statement, make sure "
               "you did not already record them under Expenses: the app only flags as duplicates the transactions that "
               "already exist in the bank register.")
    if not arch:
        return
    try:
        ext = _leer_extracto(arch)
    except Exception as e:
        st.error(str(e))
        return
    tx = d["Transacciones"][(~d["Transacciones"]["anulado"]) & (d["Transacciones"]["cuenta"] == cuenta)]
    vistos = {(r.fecha.strftime("%Y-%m-%d"), round(r.monto, 2), str(r.descripcion).lower()[:40]) for r in tx.itertuples() if pd.notna(r.fecha)}
    ext["duplicado"] = [(f.strftime("%Y-%m-%d"), round(m, 2), s.lower()[:40]) in vistos
                        for f, m, s in zip(ext["fecha"], ext["monto"], ext["descripcion"])]
    ext["contrapartida"] = [_regla(s, d["Reglas"]) for s in ext["descripcion"]]
    ops = {k: v for k, v in comun.cuentas_opciones(coa).items() if k != cuenta}
    etiquetas = {k: v for k, v in ops.items()}
    ext["contrapartida"] = ext["contrapartida"].map(lambda c: etiquetas.get(c, ""))
    ext.insert(0, "importar", (~ext["duplicado"]) & (ext["contrapartida"] != ""))
    st.write(f"{len(ext)} transactions read; {int(ext['duplicado'].sum())} duplicates; "
             f"{int((ext['contrapartida'] == '').sum())} without a category. Assign the offset account and tick the ones you want to import.")
    edit = st.data_editor(ext, hide_index=True, width="stretch", key=f"imp_ed_{arch.name}_{cuenta}",
                          disabled=["fecha", "descripcion", "monto", "duplicado"],
                          column_config={"fecha": st.column_config.DateColumn("Date", format="YYYY-MM-DD"),
                                         "monto": st.column_config.NumberColumn("Amount", format="dollar"),
                                         "importar": st.column_config.CheckboxColumn("Import"),
                                         "duplicado": st.column_config.CheckboxColumn("Duplicate"),
                                         "descripcion": st.column_config.TextColumn("Description"),
                                         "contrapartida": st.column_config.SelectboxColumn("Category or offset account", options=list(etiquetas.values()))})
    sel = edit[edit["importar"]]
    sin = sel[sel["contrapartida"] == ""]
    if st.button(f"Import {len(sel)} transactions", type="primary", disabled=sel.empty, key="imp_banco_go"):
        if len(sin):
            st.error(f"{len(sin)} selected transaction(s) have no category.")
        else:
            inv = {v: k for k, v in etiquetas.items()}
            filas = [{"fecha": r.fecha, "cuenta": cuenta, "descripcion": r.descripcion, "monto": r.monto,
                      "contrapartida": inv[r.contrapartida]} for r in sel.itertuples()]
            if comun.intentar(db.guardar, "Transacciones", filas, ok=f"{len(filas)} transactions imported.", detalle="extracto CSV"):
                st.rerun()


# ───────────────────────────── Conciliación ─────────────────────────────

def _tab_conciliar(d, cfg, coa, j) -> None:
    medios = comun.cuentas_opciones(coa, subtipos=SUB_MEDIOS)
    cuenta = st.selectbox("Account to reconcile", list(medios), format_func=lambda k: medios[k], key="conc_cta")
    tipo = coa.set_index("codigo").loc[cuenta, "tipo"]
    signo = 1 if tipo == TIPO_ACTIVO else -1
    c1, c2 = st.columns(2)
    fecha_ext = pd.Timestamp(c1.date_input("Statement date", date.today(), key="conc_f"))
    saldo_ext = c2.number_input("Ending balance per the statement", step=0.01, format="%.2f", key="conc_s")

    lin = j[j["cuenta"] == cuenta].copy()
    lin["importe"] = signo * (lin["debito"] - lin["credito"])
    agr = lin.groupby("ref").agg(fecha=("fecha", "min"), origen=("origen", "first"), memo=("memo", "first"),
                                 importe=("importe", "sum")).reset_index()
    conc = d["Conciliaciones"]
    previos = set(conc.loc[conc["cuenta"] == cuenta, "ref"])
    base_conc = agr[agr["ref"].isin(previos)]["importe"].sum()
    pend = agr[~agr["ref"].isin(previos) & (agr["fecha"] <= fecha_ext)].sort_values("fecha")
    todas = st.checkbox("Mark all as reconciled", key="conc_todas")
    pend = pend.assign(conciliar=todas)[["conciliar", "fecha", "origen", "memo", "importe", "ref"]]
    edit = st.data_editor(pend, hide_index=True, width="stretch", key=f"conc_ed_{cuenta}_{todas}_{fecha_ext:%Y%m%d}",
                          disabled=["fecha", "origen", "memo", "importe", "ref"],
                          column_config={"conciliar": st.column_config.CheckboxColumn("Reconciled"),
                                         "importe": st.column_config.NumberColumn("Amount", format="dollar"),
                                         "origen": st.column_config.TextColumn("Source"),
                                         "memo": st.column_config.TextColumn("Memo"),
                                         "fecha": st.column_config.DateColumn("Date", format="YYYY-MM-DD")})
    marcado = edit.loc[edit["conciliar"], "importe"].sum()
    conciliado = base_conc + marcado
    dif = round(saldo_ext - conciliado, 2)
    a, b, c = st.columns(3)
    a.metric("Reconciled balance", usd(conciliado))
    b.metric("Statement balance", usd(saldo_ext))
    c.metric("Difference", usd(dif), "Balanced" if abs(dif) < 0.005 else "Out of balance", delta_color="off" if abs(dif) < 0.005 else "inverse")
    if db.puede_escribir():
        if st.button("Finish reconciliation", type="primary", disabled=abs(dif) >= 0.005 or edit["conciliar"].sum() == 0, key="conc_go"):
            lote = db.nuevo_id("CON")
            filas = [{"id": lote, "cuenta": cuenta, "ref": r.ref, "fecha_extracto": fecha_ext, "saldo_extracto": saldo_ext}
                     for r in edit[edit["conciliar"]].itertuples()]
            if comun.intentar(db.guardar, "Conciliaciones", filas, ok="Reconciliation saved."):
                st.rerun()
        hist = conc[conc["cuenta"] == cuenta].groupby("id").agg(fecha_extracto=("fecha_extracto", "first"),
                                                              saldo_extracto=("saldo_extracto", "first"),
                                                              movimientos=("ref", "count")).reset_index()
        if len(hist):
            st.markdown("**Previous reconciliations**")
            comun.tabla(hist.sort_values("fecha_extracto", ascending=False), dinero=["saldo_extracto"], fechas=["fecha_extracto"])
            lote = st.selectbox("Undo a reconciliation", [""] + hist["id"].tolist(), key="conc_undo")
            if lote and st.button("Undo", key="conc_undo_b"):
                if comun.intentar(db.eliminar, "Conciliaciones", "id", lote, ok="Reconciliation undone."):
                    st.rerun()


def _tab_reglas(d, coa) -> None:
    st.caption("If a transaction description contains the keyword, that account is proposed when importing statements.")
    r = d["Reglas"]
    if len(r):
        nombres = coa.set_index("codigo")["nombre"].to_dict()
        comun.tabla(r.assign(cuenta_nombre=r["cuenta"].map(nombres))[["id", "palabra", "cuenta", "cuenta_nombre"]])
    if comun.solo_lectura():
        return
    ops = comun.cuentas_opciones(coa)
    with st.form("regla"):
        c1, c2 = st.columns(2)
        palabra = c1.text_input("Keyword or phrase")
        cuenta = c2.selectbox("Account", list(ops), format_func=lambda k: ops[k])
        ok = st.form_submit_button("Add rule")
    if ok and palabra.strip():
        if comun.intentar(db.guardar, "Reglas", {"palabra": palabra.strip(), "cuenta": cuenta}, ok="Rule saved."):
            st.rerun()
    if len(r):
        sel = st.selectbox("Delete rule", [""] + r["id"].tolist(), key="del_regla")
        if sel and st.button("Delete", key="del_regla_b"):
            if comun.intentar(db.eliminar, "Reglas", "id", sel, ok="Rule deleted."):
                st.rerun()


def banco() -> None:
    comun.flash()
    L = db.libro()
    d, cfg, coa, j = L["d"], L["cfg"], L["coa"], L["j"]
    st.title("Banking")
    t1, t2, t3, t4 = st.tabs(["Transactions", "Import statement", "Reconcile", "Category rules"])
    with t1:
        _tab_registro(d, cfg, coa, j)
    with t2:
        _tab_importar(d, cfg, coa)
    with t3:
        _tab_conciliar(d, cfg, coa, j)
    with t4:
        _tab_reglas(d, coa)
