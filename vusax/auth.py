"""Inicio de sesion, registro y control de intentos."""

from __future__ import annotations

import hashlib
import hmac
import secrets as pysecrets
import time

import streamlit as st

from . import db

ITER_ACTUAL = 600_000
ITER_LEGADO = 100_000          # usuarios creados con la version anterior
MAX_INTENTOS, VENTANA = 5, 600  # 5 fallos en 10 minutos bloquean al codigo 10 minutos
INACTIVIDAD = 3600             # la sesion se cierra tras 1 hora sin uso


def hash_password(password: str, salt: str, iteraciones: int = ITER_ACTUAL) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), iteraciones).hex()


@st.cache_resource
def _intentos() -> dict[str, list[float]]:
    return {}


def _bloqueado(codigo: str) -> bool:
    ahora = time.time()
    recientes = [t for t in _intentos().get(codigo, []) if ahora - t < VENTANA]
    _intentos()[codigo] = recientes
    return len(recientes) >= MAX_INTENTOS


def verificar_login(codigo: str, password: str):
    """Devuelve (usuario | None, mensaje de error)."""
    codigo = codigo.strip()
    if _bloqueado(codigo):
        return None, "Demasiados intentos. Espera 10 minutos e intenta de nuevo."
    df = db.crudo_usuarios()
    fila = df[df["codigo"].astype(str).str.strip() == codigo] if len(df) else df
    if fila.empty:
        _intentos().setdefault(codigo, []).append(time.time())
        return None, "Código o contraseña incorrectos."
    f = fila.iloc[0]
    iteraciones = int(float(f["iter"])) if str(f["iter"]).strip() else ITER_LEGADO
    esperado = hash_password(password, str(f["salt"]), iteraciones)
    if not hmac.compare_digest(esperado, str(f["hash"])):
        _intentos().setdefault(codigo, []).append(time.time())
        return None, "Código o contraseña incorrectos."
    if str(f["activo"]).strip().upper() == "NO":
        return None, "Este usuario está desactivado. Habla con un administrador."
    if iteraciones != ITER_ACTUAL:  # actualiza el hash a la fuerza actual
        salt = pysecrets.token_hex(16)
        db.modificar("Usuarios", codigo, {"salt": salt, "hash": hash_password(password, salt),
                                          "iter": ITER_ACTUAL}, forzar=True, accion="mejorar hash")
    rol = str(f["rol"]).strip().lower()
    return {"codigo": codigo, "nombre": f["nombre"], "rol": rol if rol in ("admin", "contador", "lectura") else "lectura"}, ""


def crear_usuario(codigo: str, nombre: str, password: str) -> str:
    """El primer usuario es administrador; los siguientes entran como solo lectura."""
    df = db.crudo_usuarios()
    rol = "admin" if df.empty or not (df["codigo"].astype(str).str.strip() != "").any() else "lectura"
    salt = pysecrets.token_hex(16)
    db.guardar("Usuarios", {"codigo": codigo.strip(), "nombre": nombre.strip(), "salt": salt,
                            "hash": hash_password(password, salt), "rol": rol, "iter": ITER_ACTUAL,
                            "activo": "SI"}, forzar=True, detalle=f"rol inicial {rol}")
    return rol


def pantalla_acceso() -> None:
    st.title("VUSAX LLC")
    if db.modo_demo():
        st.info("Modo demostración: datos de ejemplo en memoria. Usuario `demo`, contraseña `demo-1234`.")
    t1, t2 = st.tabs(["Iniciar sesión", "Crear usuario"])
    with t1:
        with st.form("login"):
            codigo = st.text_input("Código de usuario")
            password = st.text_input("Contraseña", type="password")
            ok = st.form_submit_button("Entrar", type="primary")
        if ok:
            user, error = verificar_login(codigo, password)
            if user:
                st.session_state.user = user
                st.session_state.ultimo = time.time()
                st.rerun()
            st.error(error)
    with t2:
        st.caption("Necesitas el código de registro de la empresa. Los usuarios nuevos entran en modo "
                   "lectura hasta que un administrador les asigne otro rol.")
        with st.form("registro"):
            reg = st.text_input("Código de registro")
            codigo = st.text_input("Nuevo código de usuario")
            nombre = st.text_input("Nombre")
            p1 = st.text_input("Contraseña (mínimo 10 caracteres)", type="password")
            p2 = st.text_input("Repite la contraseña", type="password")
            ok = st.form_submit_button("Crear usuario")
        if ok:
            esperado = str(db.secreto("app", "signup_code", defecto="") or "")
            df = db.crudo_usuarios()
            if not esperado or not hmac.compare_digest(reg, esperado):
                st.error("Código de registro inválido.")
            elif not codigo.strip() or not p1:
                st.error("Código y contraseña son obligatorios.")
            elif p1 != p2:
                st.error("Las contraseñas no coinciden.")
            elif len(p1) < 10:
                st.error("Usa al menos 10 caracteres.")
            elif len(df) and (df["codigo"].astype(str).str.strip() == codigo.strip()).any():
                st.error("Ese código de usuario ya existe.")
            else:
                rol = crear_usuario(codigo, nombre, p1)
                st.success(f"Usuario creado con rol '{rol}'. Ya puedes iniciar sesión.")


def sesion_vigente() -> bool:
    if "user" not in st.session_state:
        return False
    if time.time() - st.session_state.get("ultimo", time.time()) > INACTIVIDAD:
        del st.session_state["user"]
        st.session_state["aviso"] = "Tu sesión se cerró por inactividad."
        return False
    st.session_state.ultimo = time.time()
    return True


def sembrar_demo() -> None:
    """En modo demo crea el usuario `demo` si no existe."""
    df = db.crudo_usuarios()
    if db.modo_demo() and (df.empty or not (df["codigo"].astype(str) == "demo").any()):
        salt = pysecrets.token_hex(16)
        db.guardar("Usuarios", {"codigo": "demo", "nombre": "Demo", "salt": salt,
                                "hash": hash_password("demo-1234", salt), "rol": "admin",
                                "iter": ITER_ACTUAL, "activo": "SI"}, forzar=True)
