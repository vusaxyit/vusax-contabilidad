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
    st.error("Credentials (secrets) are not configured.")
    st.markdown(
        "The app needs the Google service account (`gcp_service_account`) and, under `[app]`, "
        "`sheet_url` and `signup_code`. Set them in Streamlit Cloud (Settings > Secrets) or in "
        "`.streamlit/secrets.toml` when running on your computer."
    )


def main() -> None:
    st.set_page_config(page_title="VUSAX LLC Accounting", page_icon=":material/account_balance:", layout="wide")
    if not db.configurado():
        pantalla_config_faltante()
        return
    try:
        db.backend()
    except Exception as e:
        st.title("VUSAX LLC")
        st.error("I could not connect to the Google Sheets database.")
        st.caption(f"Technical detail: {e}")
        st.markdown("Check that the spreadsheet is shared with the service account email (editor permission) "
                    "and that `sheet_url` in the secrets is correct.")
        return
    auth.sembrar_demo()

    if not auth.sesion_vigente():
        if st.session_state.pop("aviso", None):
            st.warning("Your session timed out. Please sign in again.")
        auth.pantalla_acceso()
        return

    user = st.session_state.user
    paginas = {
        "": [st.Page(panel, title="Dashboard", icon=":material/dashboard:", url_path="panel", default=True)],
        "Operations": [
            st.Page(ventas, title="Sales", icon=":material/point_of_sale:", url_path="ventas"),
            st.Page(gastos, title="Expenses & Purchases", icon=":material/receipt_long:", url_path="gastos"),
            st.Page(banco, title="Banking", icon=":material/account_balance:", url_path="banco"),
            st.Page(inventario, title="Inventory", icon=":material/inventory_2:", url_path="inventario"),
        ],
        "Accounting": [
            st.Page(reportes, title="Reports", icon=":material/monitoring:", url_path="reportes"),
            st.Page(contabilidad, title="Accounting", icon=":material/menu_book:", url_path="contabilidad"),
        ],
    }
    if user["rol"] == "admin":
        paginas["Administration"] = [st.Page(ajustes, title="Settings", icon=":material/settings:", url_path="ajustes")]
    nav = st.navigation(paginas)

    with st.sidebar:
        st.caption(f"{user.get('nombre') or user['codigo']} · {user['rol']}")
        if st.button("Refresh data", icon=":material/refresh:"):
            db.refrescar()
            st.rerun()
        if st.button("Sign out", icon=":material/logout:"):
            del st.session_state["user"]
            st.rerun()
    nav.run()


if __name__ == "__main__":
    main()
