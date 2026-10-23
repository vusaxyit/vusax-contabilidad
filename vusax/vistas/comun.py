"""Piezas de interfaz compartidas por todas las pantallas."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from .. import db, exports


def usd(x) -> str:
    x = float(x or 0)
    return f"-${abs(x):,.2f}" if x < 0 else f"${x:,.2f}"


def fecha_txt(t) -> str:
    return "" if pd.isna(t) else pd.Timestamp(t).strftime("%Y-%m-%d")


def flash() -> None:
    msg = st.session_state.pop("_flash", None)
    if msg:
        st.success(msg)


def intentar(fn, *args, ok: str = "Saved.", **kwargs):
    """Ejecuta una escritura y muestra el error en pantalla si falla. Devuelve True si salio bien."""
    try:
        fn(*args, **kwargs)
    except (db.PermisoError, ValueError, KeyError) as e:
        st.error(str(e).strip("'\""))
        return False
    except Exception as e:  # red, cuota de Google, etc.
        st.error(f"The operation could not be completed: {e}")
        return False
    st.session_state["_flash"] = ok
    return True


def solo_lectura() -> bool:
    """True (y avisa) si el usuario no puede escribir."""
    if db.puede_escribir():
        return False
    st.info("Your role is read-only: you can see everything, but not record or change data.")
    return True


def cuentas_opciones(coa: pd.DataFrame, tipos=None, subtipos=None, solo_activas=True) -> dict[str, str]:
    c = coa
    if tipos:
        c = c[c["tipo"].isin(tipos)]
    if subtipos:
        c = c[c["subtipo"].isin(subtipos)]
    if solo_activas:
        c = c[c["activa"].astype(str).str.upper() != "NO"]
    return {r.codigo: f"{r.codigo} · {r.nombre}" for r in c.sort_values("codigo").itertuples()}


def selector_cuenta(etiqueta: str, opciones: dict[str, str], key: str, defecto: str | None = None) -> str:
    claves = list(opciones)
    if not claves:
        st.warning(f"No accounts available for '{etiqueta}'. Check the chart of accounts.")
        return ""
    idx = claves.index(defecto) if defecto in claves else 0
    return st.selectbox(etiqueta, claves, index=idx, format_func=lambda k: opciones[k], key=key)


def periodo(key: str, defecto: str = "This year") -> tuple[pd.Timestamp, pd.Timestamp]:
    hoy = date.today()
    inicio_mes = hoy.replace(day=1)
    trimestre = hoy.replace(month=3 * ((hoy.month - 1) // 3) + 1, day=1)
    opciones = {
        "This month": (inicio_mes, hoy),
        "Last month": ((inicio_mes - timedelta(days=1)).replace(day=1), inicio_mes - timedelta(days=1)),
        "This quarter": (trimestre, hoy),
        "This year": (hoy.replace(month=1, day=1), hoy),
        "Last year": (date(hoy.year - 1, 1, 1), date(hoy.year - 1, 12, 31)),
        "Last 12 months": (hoy - timedelta(days=365), hoy),
        "Custom": (hoy.replace(month=1, day=1), hoy),
    }
    nombres = list(opciones)
    c1, c2, c3 = st.columns([2, 2, 2])
    sel = c1.selectbox("Period", nombres, index=nombres.index(defecto), key=f"{key}_p")
    d0, d1 = opciones[sel]
    if sel == "Custom":
        d0 = c2.date_input("From", d0, key=f"{key}_d")
        d1 = c3.date_input("To", d1, key=f"{key}_h")
    else:
        c2.caption(f"From **{d0:%Y-%m-%d}**")
        c3.caption(f"To **{d1:%Y-%m-%d}**")
    return pd.Timestamp(d0), pd.Timestamp(d1)


ETIQUETAS = {
    "num": "No.", "sku": "SKU", "id": "ID", "codigo": "Code", "nombre": "Name", "fecha": "Date",
    "descripcion": "Description", "categoria": "Category", "direccion": "Address", "telefono": "Phone",
    "ciudad": "City", "estado": "Status", "estado_us": "State", "zip": "ZIP", "tipo": "Type", "subtipo": "Subtype",
    "activo": "Active", "activa": "Active", "notas": "Notes", "cliente": "Customer", "proveedor": "Vendor",
    "canal": "Channel", "cantidad": "Qty", "costo": "Cost", "precio": "Price", "stock": "Stock",
    "monto": "Amount", "total": "Total", "pagado": "Paid", "saldo": "Balance", "vence": "Due",
    "terminos": "Terms", "memo": "Memo", "tercero": "Payee", "origen": "Source", "ref": "Ref",
    "debito": "Debit", "credito": "Credit", "cuenta": "Account", "contrapartida": "Offset account",
    "comisiones": "Referral fees", "tarifas": "Fulfillment fees", "envio": "Shipping", "motivo": "Reason",
    "impuesto": "Sales tax", "palabra": "Keyword", "asiento": "Entry", "existencias": "On hand",
    "valor": "Value", "unidades": "Units", "ingresos": "Revenue", "cargos": "Fees", "margen": "Margin",
    "socio": "Partner", "seccion": "Section", "concepto": "Item", "mes": "Month", "usuario": "User",
    "accion": "Action", "hoja": "Sheet", "clave": "Key", "detalle": "Detail", "valor_config": "Value",
    "dias_vencido": "Days overdue", "id_orden": "Order", "impuesto_pct": "Tax %",
    "stock_min": "Min. stock", "costo_prom": "Avg. cost", "margen_pct": "Margin %",
    "participacion_pct": "Ownership %", "fecha_extracto": "Statement date",
    "saldo_extracto": "Statement balance", "ingreso_bruto": "Gross revenue", "precio_unit": "Unit price",
    "costo_unit": "Unit cost", "aplica_tipo": "Applies to", "aplica_id": "Document",
    "id_cliente": "Customer ID", "id_proveedor": "Vendor ID", "resale_cert": "Resale cert.",
    "exento_impuesto": "Tax exempt", "es_1099": "1099", "metodo": "Method", "cuenta_nombre": "Account",
    "contrapartida_nombre": "Offset", "cuenta_gasto": "Expense account", "cuenta_pago": "Paid from",
    "cuenta_cobro": "Deposit to", "impuesto_cobrado": "Sales tax collected", "fecha_hora": "Timestamp",
    "apertura_qty": "Opening qty", "apertura_costo": "Opening cost", "capital_inicial": "Opening capital",
    "aportes": "Contributions", "utilidad_asignada": "Allocated profit", "retiros": "Draws",
    "capital_final": "Ending capital", "ventas_brutas": "Gross sales",
    "ventas_marketplace": "Marketplace sales", "ventas_directas": "Direct sales",
    "ventas_facturas_gravables": "Taxable invoice sales", "ventas_facturas_exentas": "Exempt invoice sales",
    "impuesto_pagado": "Tax remitted", "saldo_deudor": "Debit balance", "saldo_acreedor": "Credit balance",
    "utilidad": "Profit", "gastos": "Expenses", "existencias_min": "Min. stock",
}


def etiqueta(col: str) -> str:
    return ETIQUETAS.get(col, col.replace("_", " ").capitalize())


def tabla(df: pd.DataFrame, dinero=(), pct=(), fechas=(), enteros=(), altura=None, key=None, **extra):
    cfg = {}
    for c in df.columns:
        if c in dinero:
            cfg[c] = st.column_config.NumberColumn(etiqueta(c), format="dollar")
        elif c in pct:
            cfg[c] = st.column_config.NumberColumn(etiqueta(c), format="%.1f%%")
        elif c in fechas:
            cfg[c] = st.column_config.DateColumn(etiqueta(c), format="YYYY-MM-DD")
        elif c in enteros:
            cfg[c] = st.column_config.NumberColumn(etiqueta(c), format="%d")
        else:
            cfg[c] = st.column_config.Column(etiqueta(c))
    if altura:
        extra["height"] = altura
    if key:
        extra["key"] = key
    st.dataframe(df, hide_index=True, width="stretch", column_config=cfg, **extra)


def descargas(hojas: dict[str, pd.DataFrame], nombre: str, key: str) -> None:
    c1, c2, _ = st.columns([1, 1, 4])
    c1.download_button("Excel", exports.a_excel(hojas), f"{nombre}.xlsx", key=f"{key}_x",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    primero = next(iter(hojas.values()))
    c2.download_button("CSV", exports.a_csv(primero), f"{nombre}.csv", mime="text/csv", key=f"{key}_c")


def catalogo(hoja: str, campos: list[tuple], key: str, d: dict, etiqueta: str, columna_nombre: str) -> None:
    """Formulario de alta y edicion para Clientes, Proveedores y Productos.

    campos: (columna, etiqueta, tipo) con tipo 'text', 'num', 'sino' o una lista de opciones.
    """
    from ..config import CLAVES
    df = d[hoja]
    ck = CLAVES[hoja]
    nuevo = f"(new {etiqueta})"
    ids = df[ck].astype(str).tolist()
    nombres = {r[ck]: f"{r[columna_nombre]} ({r[ck]})" if ck != columna_nombre else str(r[ck])
               for _, r in df.iterrows()}
    sel = st.selectbox(f"Edit or create {etiqueta}", [nuevo] + ids,
                       format_func=lambda v: v if v == nuevo else nombres.get(v, v), key=f"{key}_sel")
    rec = df[df[ck].astype(str) == sel].iloc[0] if sel != nuevo else None
    with st.form(f"{key}_form_{sel}"):
        valores: dict = {}
        cols = st.columns(2)
        for i, (col, lab, tipo) in enumerate(campos):
            w = cols[i % 2]
            actual = "" if rec is None else rec[col]
            if tipo == "num":
                valores[col] = w.number_input(lab, value=float(actual or 0), step=0.01, format="%.2f")
            elif tipo == "sino":
                por_defecto = rec is None and col == "activo"
                valores[col] = w.checkbox(lab, value=por_defecto or str(actual).strip().upper() in ("SI", "SÍ", "TRUE", "1"))
            elif isinstance(tipo, list):
                opts = tipo if actual in tipo else tipo + ([actual] if actual else [])
                valores[col] = w.selectbox(lab, opts, index=opts.index(actual) if actual in opts else 0)
            else:
                valores[col] = w.text_input(lab, value=str(actual), disabled=(col == ck and rec is not None))
        ok = st.form_submit_button("Save", type="primary")
    if ok:
        datos = {k: ("SI" if v is True else "NO" if v is False else v) for k, v in valores.items()}
        if not str(datos.get(columna_nombre, "")).strip():
            st.error("The name is required.")
        elif rec is None:
            if hoja == "Productos" and (not str(datos["sku"]).strip() or str(datos["sku"]).strip() in ids):
                st.error("The SKU is required and cannot be repeated.")
            elif intentar(db.guardar, hoja, datos, ok=f"{etiqueta.capitalize()} saved."):
                st.rerun()
        else:
            datos.pop(ck, None)
            if intentar(db.modificar, hoja, sel, datos, ok=f"{etiqueta.capitalize()} updated."):
                st.rerun()
