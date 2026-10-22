"""Ajustes (solo administradores): empresa, impuestos, cierre, socios, usuarios, respaldo y auditoría."""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from .. import db, exports
from ..auth import normalizar_rol
from ..config import ROLES, SUB_BANCO
from . import comun


def _empresa(cfg, coa) -> None:
    bancos = comun.cuentas_opciones(coa, subtipos=[SUB_BANCO])
    with st.form("cfg_empresa"):
        c1, c2 = st.columns(2)
        empresa = c1.text_input("Company name", cfg["empresa"])
        direccion = c2.text_input("Address", cfg["direccion_empresa"])
        email = c1.text_input("Email for invoices", cfg["email_empresa"])
        prefijo = c2.text_input("Invoice prefix", cfg["prefijo_factura"])
        banco = c1.selectbox("Default bank account", list(bancos), format_func=lambda k: bancos[k],
                             index=list(bancos).index(cfg["banco_defecto"]) if cfg["banco_defecto"] in bancos else 0)
        plazo = c2.number_input("Default payment terms (days)", 0, 365, int(float(cfg["terminos_defecto"])))
        canales = st.text_input("Sales channels (comma separated)", cfg["canales"])
        ok = st.form_submit_button("Save", type="primary")
    if ok and comun.intentar(db.guardar_config, {
            "empresa": empresa, "direccion_empresa": direccion, "email_empresa": email, "prefijo_factura": prefijo,
            "banco_defecto": banco, "terminos_defecto": plazo, "canales": canales}, ok="Settings saved."):
        st.rerun()


def _impuestos(cfg) -> None:
    with st.form("cfg_imp"):
        tasa = st.number_input("Default sales tax rate (%)", 0.0, 20.0, float(cfg["tasa_impuesto"]), step=0.1,
                               help="This is the combined state and county rate. Verify yours on the DR-15 from the Florida Department of Revenue.")
        cierre_on = st.checkbox("Lock closed periods", value=bool(cfg["fecha_cierre"]))
        cierre = st.date_input("Do not allow records dated on or before", pd.Timestamp(cfg["fecha_cierre"]).date()
                               if cfg["fecha_cierre"] else date.today().replace(day=1))
        inicio = st.date_input("Inventory start date", pd.Timestamp(cfg["inventario_inicio"]).date(),
                               help="Stock and costs on the Productos sheet are the position as of this date. "
                                    "Earlier sales are valued at that cost and do not move stock.")
        ok = st.form_submit_button("Save", type="primary")
    if ok and comun.intentar(db.guardar_config, {"tasa_impuesto": tasa, "fecha_cierre": cierre.isoformat() if cierre_on else "",
                                                 "inventario_inicio": inicio.isoformat()}, ok="Settings saved."):
        st.rerun()


def _socios(cfg) -> None:
    with st.form("cfg_socios"):
        c1, c2 = st.columns(2)
        n1, p1 = c1.text_input("Partner 1", cfg["socio1"]), c1.number_input("Partner 1 ownership (%)", 0.0, 100.0, float(cfg["socio1_pct"]))
        n2, p2 = c2.text_input("Partner 2", cfg["socio2"]), c2.number_input("Partner 2 ownership (%)", 0.0, 100.0, float(cfg["socio2_pct"]))
        ok = st.form_submit_button("Save", type="primary")
    if ok:
        if abs(p1 + p2 - 100) > 0.01:
            st.error("The percentages must add up to 100.")
        elif comun.intentar(db.guardar_config, {"socio1": n1, "socio1_pct": p1, "socio2": n2, "socio2_pct": p2}, ok="Partners saved."):
            st.rerun()


def _usuarios() -> None:
    u = db.crudo_usuarios()
    u = u[u["codigo"].astype(str).str.strip() != ""][["codigo", "nombre", "rol", "activo"]].copy()
    u["activo"] = u["activo"].astype(str).str.upper().ne("NO")
    u["rol"] = u["rol"].map(normalizar_rol)
    st.caption("admin: everything · accountant: records and views · read: view only. New users start as read.")
    edit = st.data_editor(u, hide_index=True, width="stretch", key="usr_ed", disabled=["codigo", "nombre"],
                          column_config={"rol": st.column_config.SelectboxColumn("Role", options=ROLES, required=True),
                                         "activo": st.column_config.CheckboxColumn("Active")})
    if st.button("Save user changes", type="primary"):
        cambios = edit.merge(u, on="codigo", suffixes=("", "_antes"))
        cambios = cambios[(cambios["rol"] != cambios["rol_antes"]) | (cambios["activo"] != cambios["activo_antes"])]
        activos_admin = ((edit["rol"] == "admin") & edit["activo"]).sum()
        if activos_admin < 1:
            st.error("At least one active administrator must remain.")
            return
        for r in cambios.itertuples():
            if not comun.intentar(db.modificar, "Usuarios", r.codigo, {"rol": r.rol, "activo": "SI" if r.activo else "NO"},
                                  ok="Users updated."):
                return
        st.rerun()


def _respaldo(L) -> None:
    st.write("Download a full copy of the database in Excel. Do it at every month-end close and before big changes.")
    hojas = {n: df for n, df in L["d"].items() if n not in ("Usuarios", "Auditoria")}
    hojas["Journal"] = L["j"]
    st.download_button("Download backup (Excel)", exports.a_excel(hojas), f"vusax_backup_{date.today():%Y%m%d}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def ajustes() -> None:
    comun.flash()
    if not db.es_admin():
        st.title("Settings")
        st.warning("Only administrators can open this section.")
        return
    L = db.libro()
    st.title("Settings")
    t = st.tabs(["Company", "Taxes, closing and inventory", "Partners", "Users", "Backup", "Audit log"])
    with t[0]:
        _empresa(L["cfg"], L["coa"])
    with t[1]:
        _impuestos(L["cfg"])
    with t[2]:
        _socios(L["cfg"])
    with t[3]:
        _usuarios()
    with t[4]:
        _respaldo(L)
    with t[5]:
        a = db.leer_auditoria()
        comun.tabla(a) if len(a) else st.info("No activity recorded yet.")
