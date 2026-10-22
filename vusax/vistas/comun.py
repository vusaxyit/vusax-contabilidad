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


def intentar(fn, *args, ok: str = "Guardado.", **kwargs):
    """Ejecuta una escritura y muestra el error en pantalla si falla. Devuelve True si salio bien."""
    try:
        fn(*args, **kwargs)
    except (db.PermisoError, ValueError, KeyError) as e:
        st.error(str(e).strip("'\""))
        return False
    except Exception as e:  # red, cuota de Google, etc.
        st.error(f"No se pudo completar la operación: {e}")
        return False
    st.session_state["_flash"] = ok
    return True


def solo_lectura() -> bool:
    """True (y avisa) si el usuario no puede escribir."""
    if db.puede_escribir():
        return False
    st.info("Tu rol es de solo lectura: puedes consultar todo, pero no registrar ni cambiar datos.")
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
        st.warning(f"No hay cuentas disponibles para '{etiqueta}'. Revisa el plan de cuentas.")
        return ""
    idx = claves.index(defecto) if defecto in claves else 0
    return st.selectbox(etiqueta, claves, index=idx, format_func=lambda k: opciones[k], key=key)


def periodo(key: str, defecto: str = "Este año") -> tuple[pd.Timestamp, pd.Timestamp]:
    hoy = date.today()
    inicio_mes = hoy.replace(day=1)
    trimestre = hoy.replace(month=3 * ((hoy.month - 1) // 3) + 1, day=1)
    opciones = {
        "Este mes": (inicio_mes, hoy),
        "Mes pasado": ((inicio_mes - timedelta(days=1)).replace(day=1), inicio_mes - timedelta(days=1)),
        "Este trimestre": (trimestre, hoy),
        "Este año": (hoy.replace(month=1, day=1), hoy),
        "Año pasado": (date(hoy.year - 1, 1, 1), date(hoy.year - 1, 12, 31)),
        "Últimos 12 meses": (hoy - timedelta(days=365), hoy),
        "Personalizado": (hoy.replace(month=1, day=1), hoy),
    }
    nombres = list(opciones)
    c1, c2, c3 = st.columns([2, 2, 2])
    sel = c1.selectbox("Periodo", nombres, index=nombres.index(defecto), key=f"{key}_p")
    d0, d1 = opciones[sel]
    if sel == "Personalizado":
        d0 = c2.date_input("Desde", d0, key=f"{key}_d")
        d1 = c3.date_input("Hasta", d1, key=f"{key}_h")
    else:
        c2.caption(f"Desde **{d0:%Y-%m-%d}**")
        c3.caption(f"Hasta **{d1:%Y-%m-%d}**")
    return pd.Timestamp(d0), pd.Timestamp(d1)


ETIQUETAS = {"num": "N.º", "sku": "SKU", "id": "ID", "codigo": "Código", "descripcion": "Descripción",
             "categoria": "Categoría", "direccion": "Dirección", "telefono": "Teléfono", "dias_vencido": "Días vencido",
             "id_orden": "Orden", "impuesto_pct": "Impuesto %", "stock_min": "Stock mínimo", "costo_prom": "Costo promedio",
             "margen_pct": "Margen %", "participacion_pct": "Participación %", "fecha_extracto": "Fecha del extracto",
             "saldo_extracto": "Saldo del extracto", "ingreso_bruto": "Ingreso bruto", "precio_unit": "Precio unitario",
             "costo_unit": "Costo unitario", "aplica_tipo": "Aplica a", "aplica_id": "Documento", "id_cliente": "ID cliente",
             "id_proveedor": "ID proveedor", "resale_cert": "Cert. reventa", "exento_impuesto": "Exento", "zip": "ZIP",
             "es_1099": "1099", "metodo": "Método", "cuenta_nombre": "Cuenta", "contrapartida_nombre": "Contraparte"}


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
    nuevo = f"(nuevo {etiqueta})"
    ids = df[ck].astype(str).tolist()
    nombres = {r[ck]: f"{r[columna_nombre]} ({r[ck]})" if ck != columna_nombre else str(r[ck])
               for _, r in df.iterrows()}
    sel = st.selectbox(f"Editar o crear {etiqueta}", [nuevo] + ids,
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
        ok = st.form_submit_button("Guardar", type="primary")
    if ok:
        datos = {k: ("SI" if v is True else "NO" if v is False else v) for k, v in valores.items()}
        if not str(datos.get(columna_nombre, "")).strip():
            st.error("El nombre es obligatorio.")
        elif rec is None:
            if hoja == "Productos" and (not str(datos["sku"]).strip() or str(datos["sku"]).strip() in ids):
                st.error("El SKU es obligatorio y no puede repetirse.")
            elif intentar(db.guardar, hoja, datos, ok=f"{etiqueta.capitalize()} guardado."):
                st.rerun()
        else:
            datos.pop(ck, None)
            if intentar(db.modificar, hoja, sel, datos, ok=f"{etiqueta.capitalize()} actualizado."):
                st.rerun()
