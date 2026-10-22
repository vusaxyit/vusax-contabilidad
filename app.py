"""
VUSAX LLC - Sistema contable en la nube.

Contabilidad de partida doble, facturación, cuentas por cobrar y pagar, banco con conciliación,
inventario con costo promedio, estados financieros e impuesto de ventas de Florida.
Base de datos: Google Sheets. Despliegue: Streamlit Community Cloud.
Para probar sin credenciales: VUSAX_DEMO=1 streamlit run app.py
"""

import streamlit as st

from vusax import auth, db
from vusax.vistas.ajustes import ajustes
from vusax.vistas.banco import banco
from vusax.vistas.contabilidad import contabilidad
from vusax.vistas.gastos import gastos
from vusax.vistas.inventario import inventario
from vusax.vistas.panel import panel
from vusax.vistas.reportes import reportes
from vusax.vistas.ventas import ventas


def pantalla_config_faltante() -> None:
    st.title("VUSAX LLC")
    st.error("Falta configurar las credenciales (secrets).")
    st.markdown(
        "La app necesita la cuenta de servicio de Google (`gcp_service_account`) y, en `[app]`, "
        "`sheet_url` y `signup_code`. Configúralos en Streamlit Cloud (Settings > Secrets) o en "
        "`.streamlit/secrets.toml` si pruebas en tu computadora."
    )


def main() -> None:
    st.set_page_config(page_title="VUSAX LLC Contabilidad", page_icon=":material/account_balance:", layout="wide")
    if not db.configurado():
        pantalla_config_faltante()
        return
    try:
        db.backend()
    except Exception as e:
        st.title("VUSAX LLC")
        st.error("No pude conectarme a la base de datos de Google Sheets.")
        st.caption(f"Detalle técnico: {e}")
        st.markdown("Revisa que la hoja esté compartida con el correo de la cuenta de servicio (permiso de editor) "
                    "y que `sheet_url` en los secrets sea correcto.")
        return
    auth.sembrar_demo()

    if not auth.sesion_vigente():
        if st.session_state.pop("aviso", None):
            st.warning("Tu sesión se cerró por inactividad. Vuelve a entrar.")
        auth.pantalla_acceso()
        return

    user = st.session_state.user
    paginas = {
        "": [st.Page(panel, title="Panel", icon=":material/dashboard:", url_path="panel", default=True)],
        "Operación": [
            st.Page(ventas, title="Ventas", icon=":material/point_of_sale:", url_path="ventas"),
            st.Page(gastos, title="Gastos y compras", icon=":material/receipt_long:", url_path="gastos"),
            st.Page(banco, title="Banco", icon=":material/account_balance:", url_path="banco"),
            st.Page(inventario, title="Inventario", icon=":material/inventory_2:", url_path="inventario"),
        ],
        "Contabilidad": [
            st.Page(reportes, title="Reportes", icon=":material/monitoring:", url_path="reportes"),
            st.Page(contabilidad, title="Contabilidad", icon=":material/menu_book:", url_path="contabilidad"),
        ],
    }
    if user["rol"] == "admin":
        paginas["Administración"] = [st.Page(ajustes, title="Ajustes", icon=":material/settings:", url_path="ajustes")]
    nav = st.navigation(paginas)

    with st.sidebar:
        st.caption(f"{user.get('nombre') or user['codigo']} · {user['rol']}")
        if st.button("Actualizar datos", icon=":material/refresh:"):
            db.refrescar()
            st.rerun()
        if st.button("Cerrar sesión", icon=":material/logout:"):
            del st.session_state["user"]
            st.rerun()
    nav.run()


if __name__ == "__main__":
    main()
