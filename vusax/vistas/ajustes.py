"""Ajustes (solo administradores): empresa, impuestos, cierre, socios, usuarios, respaldo y auditoría."""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from .. import db, exports
from . import comun


def _empresa(cfg, coa) -> None:
    bancos = comun.cuentas_opciones(coa, subtipos=["Banco"])
    with st.form("cfg_empresa"):
        c1, c2 = st.columns(2)
        empresa = c1.text_input("Nombre de la empresa", cfg["empresa"])
        direccion = c2.text_input("Dirección", cfg["direccion_empresa"])
        email = c1.text_input("Email para facturas", cfg["email_empresa"])
        prefijo = c2.text_input("Prefijo de facturas", cfg["prefijo_factura"])
        banco = c1.selectbox("Cuenta bancaria por defecto", list(bancos), format_func=lambda k: bancos[k],
                             index=list(bancos).index(cfg["banco_defecto"]) if cfg["banco_defecto"] in bancos else 0)
        plazo = c2.number_input("Plazo de pago por defecto (días)", 0, 365, int(float(cfg["terminos_defecto"])))
        canales = st.text_input("Canales de venta (separados por coma)", cfg["canales"])
        ok = st.form_submit_button("Guardar", type="primary")
    if ok and comun.intentar(db.guardar_config, {
            "empresa": empresa, "direccion_empresa": direccion, "email_empresa": email, "prefijo_factura": prefijo,
            "banco_defecto": banco, "terminos_defecto": plazo, "canales": canales}, ok="Configuración guardada."):
        st.rerun()


def _impuestos(cfg) -> None:
    with st.form("cfg_imp"):
        tasa = st.number_input("Tasa de impuesto de ventas por defecto (%)", 0.0, 20.0, float(cfg["tasa_impuesto"]), step=0.1,
                               help="Es la tasa combinada estatal y del condado. Verifica la tuya en el DR-15 del Departamento de Ingresos de Florida.")
        cierre_on = st.checkbox("Bloquear periodos cerrados", value=bool(cfg["fecha_cierre"]))
        cierre = st.date_input("No permitir registros con fecha hasta", pd.Timestamp(cfg["fecha_cierre"]).date()
                               if cfg["fecha_cierre"] else date.today().replace(day=1))
        inicio = st.date_input("Fecha de inicio del inventario", pd.Timestamp(cfg["inventario_inicio"]).date(),
                               help="Las existencias y costos de la hoja Productos son la posición a esta fecha. "
                                    "Las ventas anteriores se valoran a ese costo y no mueven existencias.")
        ok = st.form_submit_button("Guardar", type="primary")
    if ok and comun.intentar(db.guardar_config, {"tasa_impuesto": tasa, "fecha_cierre": cierre.isoformat() if cierre_on else "",
                                                 "inventario_inicio": inicio.isoformat()}, ok="Configuración guardada."):
        st.rerun()


def _socios(cfg) -> None:
    with st.form("cfg_socios"):
        c1, c2 = st.columns(2)
        n1, p1 = c1.text_input("Socio 1", cfg["socio1"]), c1.number_input("Participación socio 1 (%)", 0.0, 100.0, float(cfg["socio1_pct"]))
        n2, p2 = c2.text_input("Socio 2", cfg["socio2"]), c2.number_input("Participación socio 2 (%)", 0.0, 100.0, float(cfg["socio2_pct"]))
        ok = st.form_submit_button("Guardar", type="primary")
    if ok:
        if abs(p1 + p2 - 100) > 0.01:
            st.error("Los porcentajes deben sumar 100.")
        elif comun.intentar(db.guardar_config, {"socio1": n1, "socio1_pct": p1, "socio2": n2, "socio2_pct": p2}, ok="Socios guardados."):
            st.rerun()


def _usuarios() -> None:
    u = db.crudo_usuarios()
    u = u[u["codigo"].astype(str).str.strip() != ""][["codigo", "nombre", "rol", "activo"]].copy()
    u["activo"] = u["activo"].astype(str).str.upper().ne("NO")
    u["rol"] = u["rol"].astype(str).str.lower().where(u["rol"].astype(str).str.lower().isin(["admin", "contador", "lectura"]), "lectura")
    st.caption("admin: todo · contador: registra y consulta · lectura: solo consulta. Los usuarios nuevos entran como lectura.")
    edit = st.data_editor(u, hide_index=True, width="stretch", key="usr_ed", disabled=["codigo", "nombre"],
                          column_config={"rol": st.column_config.SelectboxColumn("Rol", options=["lectura", "contador", "admin"], required=True),
                                         "activo": st.column_config.CheckboxColumn("Activo")})
    if st.button("Guardar cambios de usuarios", type="primary"):
        cambios = edit.merge(u, on="codigo", suffixes=("", "_antes"))
        cambios = cambios[(cambios["rol"] != cambios["rol_antes"]) | (cambios["activo"] != cambios["activo_antes"])]
        activos_admin = ((edit["rol"] == "admin") & edit["activo"]).sum()
        if activos_admin < 1:
            st.error("Debe quedar al menos un administrador activo.")
            return
        for r in cambios.itertuples():
            if not comun.intentar(db.modificar, "Usuarios", r.codigo, {"rol": r.rol, "activo": "SI" if r.activo else "NO"},
                                  ok="Usuarios actualizados."):
                return
        st.rerun()


def _respaldo(L) -> None:
    st.write("Descarga una copia completa de la base en Excel. Se recomienda hacerlo al cerrar cada mes y antes de cambios grandes.")
    hojas = {n: df for n, df in L["d"].items() if n not in ("Usuarios", "Auditoria")}
    hojas["Diario"] = L["j"]
    st.download_button("Descargar respaldo (Excel)", exports.a_excel(hojas), f"respaldo_vusax_{date.today():%Y%m%d}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def ajustes() -> None:
    comun.flash()
    if not db.es_admin():
        st.title("Ajustes")
        st.warning("Solo los administradores pueden entrar a esta sección.")
        return
    L = db.libro()
    st.title("Ajustes")
    t = st.tabs(["Empresa", "Impuestos, cierre e inventario", "Socios", "Usuarios", "Respaldo", "Auditoría"])
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
        comun.tabla(a) if len(a) else st.info("Sin actividad registrada todavía.")
