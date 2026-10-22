"""Inicio de sesion, registro y control de intentos."""

from __future__ import annotations

import hashlib
import hmac
import secrets as pysecrets
import time

import streamlit as st

from . import db
from .config import ROLES, ROLES_LEGADO

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
        return None, "Too many attempts. Wait 10 minutes and try again."
    df = db.crudo_usuarios()
    fila = df[df["codigo"].astype(str).str.strip() == codigo] if len(df) else df
    if fila.empty:
        _intentos().setdefault(codigo, []).append(time.time())
        return None, "Incorrect user code or password."
    f = fila.iloc[0]
    iteraciones = int(float(f["iter"])) if str(f["iter"]).strip() else ITER_LEGADO
    esperado = hash_password(password, str(f["salt"]), iteraciones)
    if not hmac.compare_digest(esperado, str(f["hash"])):
        _intentos().setdefault(codigo, []).append(time.time())
        return None, "Incorrect user code or password."
    if str(f["activo"]).strip().upper() == "NO":
        return None, "This user is deactivated. Talk to an administrator."
    if iteraciones != ITER_ACTUAL:  # actualiza el hash a la fuerza actual
        salt = pysecrets.token_hex(16)
        db.modificar("Usuarios", codigo, {"salt": salt, "hash": hash_password(password, salt),
                                          "iter": ITER_ACTUAL}, forzar=True, accion="mejorar hash")
    return {"codigo": codigo, "nombre": f["nombre"], "rol": normalizar_rol(f["rol"])}, ""


def normalizar_rol(valor) -> str:
    """Traduce los roles guardados por la version en español y descarta los desconocidos."""
    rol = str(valor).strip().lower()
    rol = ROLES_LEGADO.get(rol, rol)
    return rol if rol in ROLES else "read"


def crear_usuario(codigo: str, nombre: str, password: str) -> str:
    """El primer usuario es administrador; los siguientes entran como solo lectura."""
    df = db.crudo_usuarios()
    rol = "admin" if df.empty or not (df["codigo"].astype(str).str.strip() != "").any() else "read"
    salt = pysecrets.token_hex(16)
    db.guardar("Usuarios", {"codigo": codigo.strip(), "nombre": nombre.strip(), "salt": salt,
                            "hash": hash_password(password, salt), "rol": rol, "iter": ITER_ACTUAL,
                            "activo": "SI"}, forzar=True, detalle=f"rol inicial {rol}")
    return rol


def pantalla_acceso() -> None:
    st.title("VUSAX LLC")
    if db.modo_demo():
        st.info("Demo mode: sample data held in memory. User `demo`, password `demo-1234`.")
    t1, t2 = st.tabs(["Sign in", "Create user"])
    with t1:
        with st.form("login"):
            codigo = st.text_input("User code")
            password = st.text_input("Password", type="password")
            ok = st.form_submit_button("Sign in", type="primary")
        if ok:
            user, error = verificar_login(codigo, password)
            if user:
                st.session_state.user = user
                st.session_state.ultimo = time.time()
                st.rerun()
            st.error(error)
    with t2:
        st.caption("You need the company signup code. New users start with read-only access "
                   "until an administrator gives them another role.")
        with st.form("registro"):
            reg = st.text_input("Signup code")
            codigo = st.text_input("New user code")
            nombre = st.text_input("Name")
            p1 = st.text_input("Password (at least 10 characters)", type="password")
            p2 = st.text_input("Repeat the password", type="password")
            ok = st.form_submit_button("Create user")
        if ok:
            esperado = str(db.secreto("app", "signup_code", defecto="") or "")
            df = db.crudo_usuarios()
            if not esperado or not hmac.compare_digest(reg, esperado):
                st.error("Invalid signup code.")
            elif not codigo.strip() or not p1:
                st.error("User code and password are required.")
            elif p1 != p2:
                st.error("The passwords do not match.")
            elif len(p1) < 10:
                st.error("Use at least 10 characters.")
            elif len(df) and (df["codigo"].astype(str).str.strip() == codigo.strip()).any():
                st.error("That user code already exists.")
            else:
                rol = crear_usuario(codigo, nombre, p1)
                st.success(f"User created with role '{rol}'. You can sign in now.")


def sesion_vigente() -> bool:
    if "user" not in st.session_state:
        return False
    if time.time() - st.session_state.get("ultimo", time.time()) > INACTIVIDAD:
        del st.session_state["user"]
        st.session_state["aviso"] = "Your session timed out."
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
