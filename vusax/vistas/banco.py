"""Banco: registro de movimientos, importación de extractos y conciliación."""

from __future__ import annotations

import io
from datetime import date

import pandas as pd
import streamlit as st

from .. import db, ledger, reports
from . import comun
from .comun import usd


def _opciones_contra(coa, cfg, tipo: str) -> dict[str, str]:
    if tipo.startswith("Depósito de marketplace"):
        return comun.cuentas_opciones(coa, subtipos=["Por liquidar"])
    if tipo == "Aporte de socio":
        o = comun.cuentas_opciones(coa, subtipos=["Capital socio"])
        nombres = {"3010": cfg["socio1"], "3020": cfg["socio2"]}
        return {k: f"{k} · Capital de {nombres[k]}" if k in nombres else v for k, v in o.items()}
    if tipo.startswith("Retiro"):
        o = comun.cuentas_opciones(coa, subtipos=["Retiros socio"])
        nombres = {"3110": cfg["socio1"], "3120": cfg["socio2"]}
        return {k: f"{k} · Retiros de {nombres[k]}" if k in nombres else v for k, v in o.items()}
    if tipo.startswith("Pago de impuesto"):
        return comun.cuentas_opciones(coa, subtipos=["Impuestos"])
    return {k: v for k, v in comun.cuentas_opciones(coa).items()}


TIPOS = {
    "Depósito de marketplace o procesador": 1, "Aporte de socio": 1, "Otro depósito": 1,
    "Retiro o distribución a socio": -1, "Pago de impuesto de ventas (DR-15)": -1, "Otro retiro": -1,
    "Transferencia entre cuentas": -1,
}


def _saldos_cuentas(coa, j) -> None:
    s = reports.saldos(j, coa)
    s = s[s["subtipo"].isin(["Banco", "Tarjeta", "Por liquidar"])]
    if s.empty:
        return
    cols = st.columns(min(len(s), 5))
    for col, r in zip(cols, s.itertuples()):
        col.metric(r.nombre, usd(r.saldo))


def _tab_registro(d, cfg, coa, j) -> None:
    _saldos_cuentas(coa, j)
    if not comun.solo_lectura():
        with st.expander("Nuevo movimiento", expanded=False):
            tipo = st.selectbox("Tipo de movimiento", list(TIPOS), key="trx_tipo")
            medios = comun.cuentas_opciones(coa, subtipos=["Banco", "Tarjeta"])
            with st.form(f"trx_{tipo}"):
                c1, c2, c3 = st.columns(3)
                fecha = c1.date_input("Fecha", date.today())
                cuenta = c2.selectbox("Cuenta de origen" if tipo.startswith("Transf") else "Cuenta bancaria",
                                      list(medios), format_func=lambda k: medios[k])
                monto = c3.number_input("Monto", min_value=0.01, step=0.01)
                if tipo.startswith("Transf"):
                    destinos = {k: v for k, v in comun.cuentas_opciones(coa, subtipos=["Banco", "Tarjeta"]).items()}
                    contra = st.selectbox("Cuenta de destino (incluye pago de tarjeta)", list(destinos),
                                          format_func=lambda k: destinos[k])
                else:
                    ops = _opciones_contra(coa, cfg, tipo)
                    contra = st.selectbox("Cuenta contraparte", list(ops), format_func=lambda k: ops[k]) if ops else ""
                desc = st.text_input("Descripción")
                tercero = st.text_input("Contacto o referencia")
                ok = st.form_submit_button("Guardar movimiento", type="primary")
            if ok:
                if tipo.startswith("Transf") and contra == cuenta:
                    st.error("El origen y el destino deben ser distintos.")
                elif not contra:
                    st.error("Elige la cuenta contraparte.")
                else:
                    signo = TIPOS[tipo]
                    if comun.intentar(db.guardar, "Transacciones", {
                            "fecha": fecha, "cuenta": cuenta, "descripcion": desc or tipo, "monto": signo * monto,
                            "contrapartida": contra, "tercero": tercero}, ok="Movimiento guardado."):
                        st.rerun()
    tx = d["Transacciones"]
    tx = tx[~tx["anulado"]].sort_values("fecha", ascending=False)
    if tx.empty:
        st.info("Todavía no hay movimientos bancarios.")
        return
    nombres = coa.set_index("codigo")["nombre"].to_dict()
    v = tx.assign(cuenta_nombre=tx["cuenta"].map(nombres), contrapartida_nombre=tx["contrapartida"].map(nombres))
    comun.tabla(v[["id", "fecha", "cuenta_nombre", "descripcion", "monto", "contrapartida_nombre", "tercero", "aplica_tipo",
                   "aplica_id"]].head(500), dinero=["monto"], fechas=["fecha"])
    if db.puede_escribir():
        sel = st.selectbox("Anular un movimiento", [""] + v["id"].head(200).tolist(), key="anu_trx")
        if sel and st.button("Anular movimiento", key="anu_trx_b"):
            if comun.intentar(db.anular, "Transacciones", sel, ok="Movimiento anulado."):
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
        raise ValueError("No encontré columnas de fecha, descripción y monto (o débito y crédito).")
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
    medios = comun.cuentas_opciones(coa, subtipos=["Banco", "Tarjeta"])
    cuenta = st.selectbox("Cuenta del extracto", list(medios), format_func=lambda k: medios[k], key="imp_cta")
    arch = st.file_uploader("Extracto bancario (CSV)", type="csv", key="imp_banco")
    st.caption("Funciona con los CSV de Bank of America y Chase. Antes de importar gastos de este extracto, confirma que no los "
               "registraste ya en Gastos: la app marca como duplicados los movimientos que ya existen en el registro bancario.")
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
    st.write(f"{len(ext)} movimientos leídos; {int(ext['duplicado'].sum())} duplicados; "
             f"{int((ext['contrapartida'] == '').sum())} sin categoría. Asigna la cuenta contraparte y marca los que quieras importar.")
    edit = st.data_editor(ext, hide_index=True, width="stretch", key=f"imp_ed_{arch.name}_{cuenta}",
                          disabled=["fecha", "descripcion", "monto", "duplicado"],
                          column_config={"fecha": st.column_config.DateColumn("Fecha", format="YYYY-MM-DD"),
                                         "monto": st.column_config.NumberColumn("Monto", format="dollar"),
                                         "contrapartida": st.column_config.SelectboxColumn("Categoría o contraparte", options=list(etiquetas.values()))})
    sel = edit[edit["importar"]]
    sin = sel[sel["contrapartida"] == ""]
    if st.button(f"Importar {len(sel)} movimientos", type="primary", disabled=sel.empty, key="imp_banco_go"):
        if len(sin):
            st.error(f"{len(sin)} movimiento(s) marcados no tienen categoría.")
        else:
            inv = {v: k for k, v in etiquetas.items()}
            filas = [{"fecha": r.fecha, "cuenta": cuenta, "descripcion": r.descripcion, "monto": r.monto,
                      "contrapartida": inv[r.contrapartida]} for r in sel.itertuples()]
            if comun.intentar(db.guardar, "Transacciones", filas, ok=f"{len(filas)} movimientos importados.", detalle="extracto CSV"):
                st.rerun()


# ───────────────────────────── Conciliación ─────────────────────────────

def _tab_conciliar(d, cfg, coa, j) -> None:
    medios = comun.cuentas_opciones(coa, subtipos=["Banco", "Tarjeta"])
    cuenta = st.selectbox("Cuenta a conciliar", list(medios), format_func=lambda k: medios[k], key="conc_cta")
    tipo = coa.set_index("codigo").loc[cuenta, "tipo"]
    signo = 1 if tipo == "Activo" else -1
    c1, c2 = st.columns(2)
    fecha_ext = pd.Timestamp(c1.date_input("Fecha del extracto", date.today(), key="conc_f"))
    saldo_ext = c2.number_input("Saldo final según el extracto", step=0.01, format="%.2f", key="conc_s")

    lin = j[j["cuenta"] == cuenta].copy()
    lin["importe"] = signo * (lin["debito"] - lin["credito"])
    agr = lin.groupby("ref").agg(fecha=("fecha", "min"), origen=("origen", "first"), memo=("memo", "first"),
                                 importe=("importe", "sum")).reset_index()
    conc = d["Conciliaciones"]
    previos = set(conc.loc[conc["cuenta"] == cuenta, "ref"])
    base_conc = agr[agr["ref"].isin(previos)]["importe"].sum()
    pend = agr[~agr["ref"].isin(previos) & (agr["fecha"] <= fecha_ext)].sort_values("fecha")
    todas = st.checkbox("Marcar todas como conciliadas", key="conc_todas")
    pend = pend.assign(conciliar=todas)[["conciliar", "fecha", "origen", "memo", "importe", "ref"]]
    edit = st.data_editor(pend, hide_index=True, width="stretch", key=f"conc_ed_{cuenta}_{todas}_{fecha_ext:%Y%m%d}",
                          disabled=["fecha", "origen", "memo", "importe", "ref"],
                          column_config={"importe": st.column_config.NumberColumn("Importe", format="dollar"),
                                         "fecha": st.column_config.DateColumn("Fecha", format="YYYY-MM-DD")})
    marcado = edit.loc[edit["conciliar"], "importe"].sum()
    conciliado = base_conc + marcado
    dif = round(saldo_ext - conciliado, 2)
    a, b, c = st.columns(3)
    a.metric("Saldo conciliado", usd(conciliado))
    b.metric("Saldo del extracto", usd(saldo_ext))
    c.metric("Diferencia", usd(dif), "Cuadra" if abs(dif) < 0.005 else "Descuadre", delta_color="off" if abs(dif) < 0.005 else "inverse")
    if db.puede_escribir():
        if st.button("Finalizar conciliación", type="primary", disabled=abs(dif) >= 0.005 or edit["conciliar"].sum() == 0, key="conc_go"):
            lote = db.nuevo_id("CON")
            filas = [{"id": lote, "cuenta": cuenta, "ref": r.ref, "fecha_extracto": fecha_ext, "saldo_extracto": saldo_ext}
                     for r in edit[edit["conciliar"]].itertuples()]
            if comun.intentar(db.guardar, "Conciliaciones", filas, ok="Conciliación guardada."):
                st.rerun()
        hist = conc[conc["cuenta"] == cuenta].groupby("id").agg(fecha_extracto=("fecha_extracto", "first"),
                                                              saldo_extracto=("saldo_extracto", "first"),
                                                              movimientos=("ref", "count")).reset_index()
        if len(hist):
            st.markdown("**Conciliaciones anteriores**")
            comun.tabla(hist.sort_values("fecha_extracto", ascending=False), dinero=["saldo_extracto"], fechas=["fecha_extracto"])
            lote = st.selectbox("Deshacer una conciliación", [""] + hist["id"].tolist(), key="conc_undo")
            if lote and st.button("Deshacer", key="conc_undo_b"):
                if comun.intentar(db.eliminar, "Conciliaciones", "id", lote, ok="Conciliación deshecha."):
                    st.rerun()


def _tab_reglas(d, coa) -> None:
    st.caption("Si la descripción de un movimiento contiene la palabra, se propone esa cuenta al importar extractos.")
    r = d["Reglas"]
    if len(r):
        nombres = coa.set_index("codigo")["nombre"].to_dict()
        comun.tabla(r.assign(cuenta_nombre=r["cuenta"].map(nombres))[["id", "palabra", "cuenta", "cuenta_nombre"]])
    if comun.solo_lectura():
        return
    ops = comun.cuentas_opciones(coa)
    with st.form("regla"):
        c1, c2 = st.columns(2)
        palabra = c1.text_input("Palabra o frase")
        cuenta = c2.selectbox("Cuenta", list(ops), format_func=lambda k: ops[k])
        ok = st.form_submit_button("Agregar regla")
    if ok and palabra.strip():
        if comun.intentar(db.guardar, "Reglas", {"palabra": palabra.strip(), "cuenta": cuenta}, ok="Regla guardada."):
            st.rerun()
    if len(r):
        sel = st.selectbox("Eliminar regla", [""] + r["id"].tolist(), key="del_regla")
        if sel and st.button("Eliminar", key="del_regla_b"):
            if comun.intentar(db.eliminar, "Reglas", "id", sel, ok="Regla eliminada."):
                st.rerun()


def banco() -> None:
    comun.flash()
    L = db.libro()
    d, cfg, coa, j = L["d"], L["cfg"], L["coa"], L["j"]
    st.title("Banco")
    t1, t2, t3, t4 = st.tabs(["Movimientos", "Importar extracto", "Conciliar", "Reglas de categorías"])
    with t1:
        _tab_registro(d, cfg, coa, j)
    with t2:
        _tab_importar(d, cfg, coa)
    with t3:
        _tab_conciliar(d, cfg, coa, j)
    with t4:
        _tab_reglas(d, coa)
