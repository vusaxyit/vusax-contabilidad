"""
VUSAX LLC - Sistema Contable en la nube
Sitio web con login. Base unica: Google Sheets (gspread).
Despliegue: Streamlit Community Cloud (gratis).
Acceso desde cualquier dispositivo por navegador.
"""

import hashlib
import secrets as pysecrets
from datetime import date

import pandas as pd
import streamlit as st

# Estructura de la base. Si una hoja no existe, la app la crea sola.
REQUIRED_SHEETS = {
    "Usuarios": ["codigo", "nombre", "salt", "hash", "rol"],
    "Productos": ["sku", "nombre", "categoria", "canal", "costo", "precio", "stock", "stock_min"],
    "Clientes": ["id_cliente", "nombre", "email", "telefono", "direccion", "ciudad", "estado", "zip", "tipo"],
    "Ingresos": ["fecha", "canal", "id_orden", "sku", "cantidad", "ingreso_bruto", "comisiones", "tarifas", "envio"],
    "Gastos": ["fecha", "categoria", "proveedor", "descripcion", "monto", "metodo"],
    "Invoices": ["num", "fecha", "id_cliente", "cliente", "estado", "impuesto"],
    "Invoice_Items": ["num", "sku", "descripcion", "cantidad", "precio_unit"],
}

# ──────────────────────────── CONEXION A GOOGLE SHEETS ────────────────────────────

def secrets_ok():
    return "gcp_service_account" in st.secrets and "app" in st.secrets

@st.cache_resource(show_spinner=False)
def get_sheet():
    import gspread
    gc = gspread.service_account_from_dict(dict(st.secrets["gcp_service_account"]))
    sh = gc.open_by_url(st.secrets["app"]["sheet_url"])
    # Crear hojas faltantes con sus encabezados
    existentes = [w.title for w in sh.worksheets()]
    for nombre, cols in REQUIRED_SHEETS.items():
        if nombre not in existentes:
            ws = sh.add_worksheet(title=nombre, rows=1000, cols=max(10, len(cols)))
            ws.append_row(cols)
    return sh

@st.cache_data(ttl=30, show_spinner=False)
def leer(nombre):
    sh = get_sheet()
    ws = sh.worksheet(nombre)
    registros = ws.get_all_records()
    df = pd.DataFrame(registros)
    if df.empty:
        df = pd.DataFrame(columns=REQUIRED_SHEETS[nombre])
    return df

def agregar(nombre, fila_dict):
    sh = get_sheet()
    ws = sh.worksheet(nombre)
    cols = REQUIRED_SHEETS[nombre]
    ws.append_row([fila_dict.get(c, "") for c in cols], value_input_option="USER_ENTERED")
    leer.clear()

# ──────────────────────────── LOGICA PURA (COGS) ────────────────────────────

def calcular_ingresos(df_ing, df_prod):
    """Agrega columnas neto, cogs y margen. Funcion pura, sin red."""
    if df_ing.empty:
        return df_ing
    for col in ["ingreso_bruto", "comisiones", "tarifas", "envio", "cantidad"]:
        df_ing[col] = pd.to_numeric(df_ing.get(col), errors="coerce").fillna(0)
    costos = {}
    if not df_prod.empty:
        df_prod["costo"] = pd.to_numeric(df_prod.get("costo"), errors="coerce").fillna(0)
        costos = dict(zip(df_prod["sku"], df_prod["costo"]))
    df_ing["neto"] = df_ing["ingreso_bruto"] - df_ing["comisiones"] - df_ing["tarifas"] - df_ing["envio"]
    df_ing["cogs"] = df_ing.apply(lambda r: r["cantidad"] * costos.get(r["sku"], 0), axis=1)
    df_ing["margen"] = df_ing["neto"] - df_ing["cogs"]
    return df_ing

# ──────────────────────────── SEGURIDAD ────────────────────────────

def hash_password(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000).hex()

def crear_usuario(codigo, nombre, password):
    salt = pysecrets.token_hex(16)
    agregar("Usuarios", {
        "codigo": codigo, "nombre": nombre,
        "salt": salt, "hash": hash_password(password, salt), "rol": "admin",
    })

def verificar_login(codigo, password):
    df = leer("Usuarios")
    if df.empty:
        return None
    fila = df[df["codigo"].astype(str) == str(codigo)]
    if fila.empty:
        return None
    fila = fila.iloc[0]
    if hash_password(password, str(fila["salt"])) == str(fila["hash"]):
        return {"codigo": fila["codigo"], "nombre": fila["nombre"], "rol": fila["rol"]}
    return None

def codigo_registro_valido(codigo):
    return codigo == st.secrets["app"].get("signup_code", "")

# ──────────────────────────── PANTALLAS DE ACCESO ────────────────────────────

def pantalla_acceso():
    st.title("VUSAX LLC")
    tab_login, tab_registro = st.tabs(["Iniciar sesion", "Crear usuario"])

    with tab_login:
        with st.form("login"):
            codigo = st.text_input("Codigo de usuario")
            password = st.text_input("Contrasena", type="password")
            ok = st.form_submit_button("Entrar")
        if ok:
            user = verificar_login(codigo, password)
            if user:
                st.session_state.user = user
                st.rerun()
            else:
                st.error("Codigo o contrasena incorrectos.")

    with tab_registro:
        st.caption("Para crear un usuario necesitas el codigo de registro de la empresa.")
        with st.form("registro"):
            reg = st.text_input("Codigo de registro")
            codigo = st.text_input("Nuevo codigo de usuario")
            nombre = st.text_input("Nombre")
            p1 = st.text_input("Contrasena", type="password")
            p2 = st.text_input("Repite la contrasena", type="password")
            ok = st.form_submit_button("Crear usuario")
        if ok:
            if not codigo_registro_valido(reg):
                st.error("Codigo de registro invalido.")
            elif not codigo or not p1:
                st.error("Codigo y contrasena son obligatorios.")
            elif p1 != p2:
                st.error("Las contrasenas no coinciden.")
            elif len(p1) < 6:
                st.error("Usa al menos 6 caracteres.")
            else:
                df = leer("Usuarios")
                if not df.empty and (df["codigo"].astype(str) == str(codigo)).any():
                    st.error("Ese codigo de usuario ya existe.")
                else:
                    crear_usuario(codigo, nombre, p1)
                    st.success("Usuario creado. Ya puedes iniciar sesion.")

# ──────────────────────────── MODULOS ────────────────────────────

def pagina_dashboard():
    import plotly.express as px
    st.header("Dashboard financiero")
    ing = calcular_ingresos(leer("Ingresos"), leer("Productos"))
    gas = leer("Gastos")
    gas_monto = pd.to_numeric(gas.get("monto"), errors="coerce").fillna(0) if not gas.empty else pd.Series([0])

    ventas = ing["ingreso_bruto"].sum() if not ing.empty else 0
    cogs = ing["cogs"].sum() if not ing.empty else 0
    margen = ing["margen"].sum() if not ing.empty else 0
    gastos = gas_monto.sum()
    beneficio = margen - gastos

    a, b, c = st.columns(3)
    a.metric("Ventas totales", f"${ventas:,.2f}")
    b.metric("COGS", f"${cogs:,.2f}")
    c.metric("Margen bruto", f"${margen:,.2f}")
    d, e, f = st.columns(3)
    d.metric("Gastos operativos", f"${gastos:,.2f}")
    e.metric("Beneficio neto real", f"${beneficio:,.2f}")
    f.metric("Margen %", f"{(margen/ventas*100) if ventas else 0:,.1f}%")

    if not ing.empty:
        por_canal = ing.groupby("canal")[["ingreso_bruto", "margen"]].sum().reset_index()
        st.plotly_chart(px.bar(por_canal, x="canal", y="margen", title="Margen por canal"),
                        use_container_width=True)
        st.plotly_chart(px.pie(por_canal, names="canal", values="ingreso_bruto",
                        title="Ventas por canal"), use_container_width=True)
    else:
        st.info("Aun no hay ingresos. Registra una venta para ver los graficos.")

def pagina_productos():
    st.header("Productos e inventario")
    with st.expander("Agregar producto", expanded=False):
        with st.form("nuevo_producto"):
            col1, col2 = st.columns(2)
            sku = col1.text_input("SKU")
            nombre = col2.text_input("Nombre")
            categoria = col1.text_input("Categoria")
            canal = col2.selectbox("Canal principal", ["Amazon FBA", "Walmart", "TikTok Shop", "Otro"])
            costo = col1.number_input("Costo unitario", min_value=0.0, step=0.01)
            precio = col2.number_input("Precio de venta", min_value=0.0, step=0.01)
            stock = col1.number_input("Stock actual", min_value=0, step=1)
            stock_min = col2.number_input("Stock minimo", min_value=0, step=1)
            ok = st.form_submit_button("Guardar")
        if ok and sku and nombre:
            agregar("Productos", {"sku": sku, "nombre": nombre, "categoria": categoria,
                    "canal": canal, "costo": costo, "precio": precio,
                    "stock": int(stock), "stock_min": int(stock_min)})
            st.success(f"Producto {sku} guardado.")
            st.rerun()
    df = leer("Productos")
    st.dataframe(df, use_container_width=True) if not df.empty else st.info("Sin productos todavia.")

def pagina_ingresos():
    st.header("Ingresos multicanal")
    prod = leer("Productos")
    skus = prod["sku"].tolist() if not prod.empty else []
    with st.expander("Registrar venta", expanded=True):
        with st.form("nueva_venta"):
            col1, col2 = st.columns(2)
            fecha = col1.date_input("Fecha", value=date.today())
            canal = col2.selectbox("Canal", ["Amazon FBA", "Walmart", "TikTok Shop", "Directo"])
            id_orden = col1.text_input("ID de orden")
            sku = col2.selectbox("SKU", skus) if skus else col2.text_input("SKU")
            cantidad = col1.number_input("Cantidad", min_value=1, step=1)
            bruto = col2.number_input("Ingreso bruto", min_value=0.0, step=0.01)
            comisiones = col1.number_input("Comisiones", min_value=0.0, step=0.01)
            tarifas = col2.number_input("Tarifas fulfillment", min_value=0.0, step=0.01)
            envio = col1.number_input("Envio", min_value=0.0, step=0.01)
            ok = st.form_submit_button("Registrar")
        if ok:
            agregar("Ingresos", {"fecha": fecha.isoformat(), "canal": canal, "id_orden": id_orden,
                    "sku": sku, "cantidad": int(cantidad), "ingreso_bruto": bruto,
                    "comisiones": comisiones, "tarifas": tarifas, "envio": envio})
            st.success("Venta registrada. COGS y margen calculados.")
            st.rerun()
    df = calcular_ingresos(leer("Ingresos"), prod)
    st.dataframe(df, use_container_width=True) if not df.empty else st.info("Sin ventas todavia.")

def pagina_gastos():
    st.header("Gastos operativos")
    with st.expander("Registrar gasto", expanded=True):
        with st.form("nuevo_gasto"):
            col1, col2 = st.columns(2)
            fecha = col1.date_input("Fecha", value=date.today())
            categoria = col2.text_input("Categoria")
            proveedor = col1.text_input("Proveedor")
            metodo = col2.selectbox("Metodo de pago", ["Tarjeta", "Transferencia", "Efectivo", "Otro"])
            descripcion = st.text_input("Descripcion")
            monto = st.number_input("Monto", min_value=0.0, step=0.01)
            ok = st.form_submit_button("Registrar")
        if ok:
            agregar("Gastos", {"fecha": fecha.isoformat(), "categoria": categoria,
                    "proveedor": proveedor, "descripcion": descripcion, "monto": monto, "metodo": metodo})
            st.success("Gasto registrado.")
            st.rerun()
    df = leer("Gastos")
    st.dataframe(df, use_container_width=True) if not df.empty else st.info("Sin gastos todavia.")

def pagina_facturas():
    st.header("Facturas")
    prod = leer("Productos")
    with st.expander("Crear linea de factura", expanded=True):
        with st.form("nueva_invoice"):
            col1, col2 = st.columns(2)
            num = col1.text_input("Numero de factura", value="INV-1001")
            fecha = col2.date_input("Fecha", value=date.today())
            cliente = col1.text_input("Cliente")
            estado = col2.selectbox("Estado", ["Borrador", "Enviada", "Pagada"])
            sku = col1.selectbox("Producto", prod["sku"].tolist()) if not prod.empty else col1.text_input("SKU")
            cantidad = col2.number_input("Cantidad", min_value=1, step=1)
            ok = st.form_submit_button("Guardar")
        if ok and not prod.empty:
            fila = prod[prod["sku"] == sku].iloc[0]
            agregar("Invoices", {"num": num, "fecha": fecha.isoformat(), "id_cliente": "",
                    "cliente": cliente, "estado": estado, "impuesto": 0})
            agregar("Invoice_Items", {"num": num, "sku": sku, "descripcion": fila["nombre"],
                    "cantidad": int(cantidad), "precio_unit": float(pd.to_numeric(fila["precio"], errors="coerce") or 0)})
            st.success(f"Linea agregada a {num}.")
            st.rerun()
    items = leer("Invoice_Items")
    if not items.empty:
        items["cantidad"] = pd.to_numeric(items["cantidad"], errors="coerce").fillna(0)
        items["precio_unit"] = pd.to_numeric(items["precio_unit"], errors="coerce").fillna(0)
        items["subtotal"] = items["cantidad"] * items["precio_unit"]
        st.dataframe(items, use_container_width=True)
        st.metric("Total facturado", f"${items['subtotal'].sum():,.2f}")
    else:
        st.info("Sin facturas todavia.")

# ──────────────────────────── APP PRINCIPAL ────────────────────────────

def pantalla_config_faltante():
    st.title("VUSAX LLC")
    st.error("Falta configurar las credenciales (secrets).")
    st.markdown(
        "La app necesita tu cuenta de servicio de Google y el enlace de la hoja. "
        "Sigue la guia de despliegue para llenar los secrets en Streamlit Cloud, "
        "o el archivo `.streamlit/secrets.toml` si pruebas en local."
    )

def main():
    st.set_page_config(page_title="VUSAX LLC Contabilidad", page_icon="📊", layout="wide")

    if not secrets_ok():
        pantalla_config_faltante()
        return

    if "user" not in st.session_state:
        pantalla_acceso()
        return

    user = st.session_state.user
    st.sidebar.title("VUSAX LLC")
    st.sidebar.caption(f"Sesion: {user.get('nombre') or user.get('codigo')}")
    pagina = st.sidebar.radio("Menu", ["Dashboard", "Productos", "Ingresos", "Gastos", "Facturas"])
    if st.sidebar.button("Cerrar sesion"):
        del st.session_state.user
        st.rerun()

    {"Dashboard": pagina_dashboard, "Productos": pagina_productos, "Ingresos": pagina_ingresos,
     "Gastos": pagina_gastos, "Facturas": pagina_facturas}[pagina]()

if __name__ == "__main__":
    main()
