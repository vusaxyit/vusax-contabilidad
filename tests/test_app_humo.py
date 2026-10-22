"""Prueba de humo: arranca la app en modo demo y recorre cada pantalla sin errores."""

import os
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

os.environ["VUSAX_DEMO"] = "1"
RAIZ = Path(__file__).resolve().parent.parent
PAGINAS = ["panel", "ventas", "gastos", "banco", "inventario", "reportes", "contabilidad", "ajustes"]


def _app() -> AppTest:
    return AppTest.from_file(str(RAIZ / "app.py"), default_timeout=90)


def test_login_incorrecto():
    at = _app().run()
    at.text_input[0].set_value("demo")
    at.text_input[1].set_value("mala")
    at.button[0].click()
    at.run()
    assert any("incorrectos" in e.value for e in at.error)


def test_login_correcto_y_panel():
    at = _app().run()
    at.text_input[0].set_value("demo")
    at.text_input[1].set_value("demo-1234")
    at.button[0].click()
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("VUSAX" in t.value for t in at.title)
    assert len(at.metric) >= 8


def _pantalla(nombre: str, rol: str = "admin"):
    import streamlit as st
    from vusax import auth, db
    st.session_state["user"] = {"codigo": "t", "nombre": "T", "rol": rol}
    from vusax.vistas import ajustes, banco, contabilidad, gastos, inventario, panel, reportes, ventas
    getattr(locals()[nombre], nombre)()


@pytest.mark.parametrize("pagina", PAGINAS)
def test_pantallas_sin_errores(pagina):
    at = AppTest.from_function(_pantalla, args=(pagina,), default_timeout=90).run()
    assert not at.exception, [e.value for e in at.exception]


@pytest.mark.parametrize("pagina", PAGINAS)
def test_pantallas_solo_lectura(pagina):
    at = AppTest.from_function(_pantalla, args=(pagina, "lectura"), default_timeout=90).run()
    assert not at.exception, [e.value for e in at.exception]


def test_todos_los_reportes():
    from vusax.vistas.reportes import REPORTES
    at = AppTest.from_function(_pantalla, args=("reportes",), default_timeout=90).run()
    for nombre in REPORTES:
        at.selectbox[0].set_value(nombre).run()
        assert not at.exception, (nombre, [e.value for e in at.exception])


def test_registrar_gasto_desde_el_formulario():
    from vusax import db
    antes = len(db.libro()["d"]["Gastos"])
    at = AppTest.from_function(_pantalla, args=("gastos",), default_timeout=90).run()
    monto = next(w for w in at.number_input if w.label == "Monto")
    monto.set_value(42.5)
    next(w for w in at.text_input if w.label == "Proveedor").set_value("Prueba SA")
    next(b for b in at.button if b.label == "Registrar gasto").click()
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    g = db.libro()["d"]["Gastos"]
    assert len(g) == antes + 1
    assert g.iloc[-1]["monto"] == 42.5 and g.iloc[-1]["cuenta_gasto"] == "6900"


def test_solo_lectura_no_puede_guardar():
    from vusax import db
    antes = len(db.libro()["d"]["Gastos"])
    at = AppTest.from_function(_pantalla, args=("gastos", "lectura"), default_timeout=90).run()
    assert not [b for b in at.button if b.label == "Registrar gasto"]
    assert len(db.libro()["d"]["Gastos"]) == antes
