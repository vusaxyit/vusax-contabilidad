"""Acceso a datos. Google Sheets es la base; hay un respaldo en memoria para demo y pruebas.

Mejoras frente a la version anterior:
- Una sola llamada a la API lee todas las hojas (antes habia una por hoja y por recarga).
- Migracion automatica: agrega columnas nuevas y asigna ids a registros antiguos sin tocar tus datos.
- Escritura 'RAW': el texto nunca se interpreta como formula ni cambia de formato.
- Permisos por rol, bitacora de auditoria y fecha de cierre de periodo.
"""

from __future__ import annotations

import os
import secrets as pysecrets
import time
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from . import ledger, reports
from .config import (CLAVES, CON_FECHA, CONFIG_DEFECTO, PLAN_CUENTAS, PREFIJOS, SCHEMAS)
from .demo import datos_demo_crudos

TZ = ZoneInfo("America/New_York")
HOJAS_DATOS = [n for n in SCHEMAS if n != "Auditoria"]


class PermisoError(Exception):
    pass


# ───────────────────────────── Respaldo en memoria (demo y pruebas) ─────────────────────────────

class MemoryBackend:
    def __init__(self, inicial: dict[str, pd.DataFrame] | None = None):
        self.t: dict[str, list[list]] = {}
        self.enc: dict[str, list[str]] = {}
        for n, df in (inicial or {}).items():
            self.t[n] = [list(df.columns)] + df.astype(str).values.tolist()

    def asegurar_esquema(self, esquemas):
        for n, cols in esquemas.items():
            if n not in self.t:
                self.t[n] = [list(cols)]
            head = self.t[n][0]
            for c in cols:
                if c not in head:
                    head.append(c)
                    for r in self.t[n][1:]:
                        r.append("")
            self.enc[n] = list(head)

    def leer_todo(self, nombres):
        return {n: [list(r) for r in self.t[n]] for n in nombres}

    def agregar(self, n, filas):
        for f in filas:
            self.t[n].append([f.get(c, "") for c in self.enc[n]])

    def escribir_celdas(self, n, celdas):
        for fila, col, valor in celdas:
            self.t[n][fila - 1][col] = valor

    def actualizar(self, n, col, valor, cambios) -> int:
        i = self.enc[n].index(col)
        cuenta = 0
        for r in self.t[n][1:]:
            if str(r[i]).strip() == str(valor).strip():
                for k, v in cambios.items():
                    r[self.enc[n].index(k)] = v
                cuenta += 1
        return cuenta

    def borrar(self, n, col, valor) -> int:
        i = self.enc[n].index(col)
        antes = len(self.t[n])
        self.t[n] = [self.t[n][0]] + [r for r in self.t[n][1:] if str(r[i]).strip() != str(valor).strip()]
        return antes - len(self.t[n])


# ───────────────────────────── Google Sheets ─────────────────────────────

def _reintentar(fn):
    def envoltura(*a, **k):
        import gspread
        for espera in (0, 2, 5, 12):
            time.sleep(espera)
            try:
                return fn(*a, **k)
            except gspread.exceptions.APIError as e:
                codigo = getattr(getattr(e, "response", None), "status_code", 0)
                if codigo not in (429, 500, 502, 503) or espera == 12:
                    raise
    return envoltura


class SheetsBackend:
    def __init__(self, credenciales: dict, url: str):
        import gspread
        self.sh = gspread.service_account_from_dict(credenciales).open_by_url(url)
        self.enc: dict[str, list[str]] = {}
        self._ws: dict = {}

    def _hoja(self, n):
        if n not in self._ws:
            self._ws[n] = self.sh.worksheet(n)
        return self._ws[n]

    @_reintentar
    def asegurar_esquema(self, esquemas):
        from gspread.utils import rowcol_to_a1
        hojas = {w.title: w for w in self.sh.worksheets()}
        nuevas = [n for n in esquemas if n not in hojas]
        if nuevas:
            self.sh.batch_update({"requests": [
                {"addSheet": {"properties": {"title": n, "gridProperties": {
                    "rowCount": 1000, "columnCount": max(12, len(esquemas[n]) + 2)}}}} for n in nuevas]})
            hojas = {w.title: w for w in self.sh.worksheets()}
        existentes = [n for n in esquemas if n not in nuevas]
        cabeceras: dict[str, list[str]] = {n: [] for n in nuevas}
        if existentes:
            res = self.sh.values_batch_get([f"{n}!1:1" for n in existentes])
            for n, vr in zip(existentes, res.get("valueRanges", [])):
                cabeceras[n] = [str(c).strip() for c in (vr.get("values") or [[]])[0]]
        datos, ajustes = [], []
        for n, cols in esquemas.items():
            head = cabeceras.get(n, [])
            faltan = [c for c in cols if c not in head]
            if faltan:
                datos.append({"range": f"{n}!{rowcol_to_a1(1, len(head) + 1)}", "values": [faltan]})
                if hojas[n].col_count < len(head) + len(faltan):
                    ajustes.append({"updateSheetProperties": {
                        "properties": {"sheetId": hojas[n].id,
                                       "gridProperties": {"columnCount": len(head) + len(faltan) + 2}},
                        "fields": "gridProperties.columnCount"}})
            self.enc[n] = head + faltan
        if ajustes:
            self.sh.batch_update({"requests": ajustes})
        if datos:
            self.sh.values_batch_update({"valueInputOption": "RAW", "data": datos})

    @_reintentar
    def leer_todo(self, nombres):
        res = self.sh.values_batch_get(list(nombres))
        return {n: vr.get("values", []) for n, vr in zip(nombres, res.get("valueRanges", []))}

    @_reintentar
    def agregar(self, n, filas):
        self._hoja(n).append_rows([[f.get(c, "") for c in self.enc[n]] for f in filas],
                                  value_input_option="RAW", insert_data_option="INSERT_ROWS", table_range="A1")

    @_reintentar
    def escribir_celdas(self, n, celdas):
        from gspread.utils import rowcol_to_a1
        self.sh.values_batch_update({"valueInputOption": "RAW", "data": [
            {"range": f"{n}!{rowcol_to_a1(f, c + 1)}", "values": [[v]]} for f, c, v in celdas]})

    def _filas(self, n, col, valor):
        i = self.enc[n].index(col) + 1
        valores = self._hoja(n).col_values(i)
        return [k + 1 for k, v in enumerate(valores) if k > 0 and str(v).strip() == str(valor).strip()]

    @_reintentar
    def actualizar(self, n, col, valor, cambios) -> int:
        from gspread.utils import rowcol_to_a1
        filas = self._filas(n, col, valor)
        datos = [{"range": f"{n}!{rowcol_to_a1(f, self.enc[n].index(k) + 1)}", "values": [[v]]}
                 for f in filas for k, v in cambios.items()]
        if datos:
            self.sh.values_batch_update({"valueInputOption": "RAW", "data": datos})
        return len(filas)

    @_reintentar
    def borrar(self, n, col, valor) -> int:
        filas = self._filas(n, col, valor)
        if filas:
            sid = self._hoja(n).id
            self.sh.batch_update({"requests": [
                {"deleteDimension": {"range": {"sheetId": sid, "dimension": "ROWS",
                                               "startIndex": f - 1, "endIndex": f}}} for f in sorted(filas, reverse=True)]})
        return len(filas)


# ───────────────────────────── Arranque, migracion y semillas ─────────────────────────────

def secreto(*ruta, defecto=None):
    try:
        v = st.secrets
        for k in ruta:
            v = v[k]
        return v
    except Exception:
        return defecto


def modo_demo() -> bool:
    return bool(os.environ.get("VUSAX_DEMO")) or secreto("app", "modo") == "demo"


def configurado() -> bool:
    return modo_demo() or (secreto("gcp_service_account") is not None and secreto("app", "sheet_url") is not None)


def nuevo_id(prefijo: str) -> str:
    return f"{prefijo}-{pysecrets.token_hex(4).upper()}"


def _a_df(values) -> pd.DataFrame:
    if not values:
        return pd.DataFrame()
    head = [str(h).strip() for h in values[0]]
    filas = [(list(r) + [""] * len(head))[:len(head)] for r in values[1:]]
    return pd.DataFrame(filas, columns=head, dtype=object)


def _migrar(b) -> None:
    """Asigna ids a registros antiguos y siembra Config y plan de cuentas. Es idempotente."""
    datos = b.leer_todo(HOJAS_DATOS)
    celdas: dict[str, list[tuple]] = {}
    for n, pref in PREFIJOS.items():
        v = datos.get(n) or []
        if len(v) < 2:
            continue
        head = [str(h).strip() for h in v[0]]
        if CLAVES[n] not in head:
            continue
        ic = head.index(CLAVES[n])
        for k, fila in enumerate(v[1:], start=2):
            fila = list(fila) + [""] * (len(head) - len(fila))
            if not str(fila[ic]).strip() and any(str(x).strip() for x in fila):
                celdas.setdefault(n, []).append((k, ic, nuevo_id(pref)))
    for n, c in celdas.items():
        b.escribir_celdas(n, c)

    cfg_actual = {str(r[0]).strip() for r in (datos.get("Config") or [])[1:] if r}
    hay_historia = len(datos.get("Ingresos") or []) > 1 or len(datos.get("Invoice_Items") or []) > 1
    faltan = []
    for k, v in CONFIG_DEFECTO.items():
        if k not in cfg_actual:
            if k == "inventario_inicio" and hay_historia:
                v = date.today().isoformat()  # el stock actual de Productos se toma como apertura de hoy
            faltan.append({"clave": k, "valor": v})
    if faltan:
        b.agregar("Config", faltan)
    if len(datos.get("Cuentas") or []) < 2:
        b.agregar("Cuentas", [{"codigo": c, "nombre": n, "tipo": t, "subtipo": s, "activa": "SI"}
                              for c, n, t, s in PLAN_CUENTAS])


@st.cache_resource(show_spinner="Conectando con la base de datos...")
def backend():
    if modo_demo():
        b = MemoryBackend(datos_demo_crudos())
    else:
        b = SheetsBackend(dict(st.secrets["gcp_service_account"]), st.secrets["app"]["sheet_url"])
    b.asegurar_esquema(SCHEMAS)
    _migrar(b)
    return b


# ───────────────────────────── Lectura (con cache) ─────────────────────────────

@st.cache_data(ttl=45, show_spinner=False)
def _crudo() -> dict[str, pd.DataFrame]:
    return {n: _a_df(v) for n, v in backend().leer_todo(HOJAS_DATOS).items()}


@st.cache_data(ttl=45, show_spinner="Calculando libro contable...")
def libro() -> dict:
    d = ledger.preparar(_crudo())
    cfg = ledger.leer_config(d["Config"])
    j, inv, ev = ledger.construir_diario(d, cfg)
    return {"d": d, "cfg": cfg, "j": j, "inv": inv, "ev": ev, "coa": reports.plan_df(d)}


def crudo_usuarios() -> pd.DataFrame:
    return _crudo()["Usuarios"]


def leer_auditoria(limite: int = 500) -> pd.DataFrame:
    df = _a_df(backend().leer_todo(["Auditoria"])["Auditoria"])
    return df.tail(limite).iloc[::-1].reset_index(drop=True) if len(df) else df


def refrescar() -> None:
    _crudo.clear()
    libro.clear()


# ───────────────────────────── Sesion y permisos ─────────────────────────────

def usuario() -> dict:
    return st.session_state.get("user") or {}


def puede_escribir() -> bool:
    return usuario().get("rol") in ("contador", "admin")


def es_admin() -> bool:
    return usuario().get("rol") == "admin"


def _exigir_escritura(forzar: bool):
    if not forzar and not puede_escribir():
        raise PermisoError("Tu rol es de solo lectura. Pide a un administrador que te cambie a 'contador'.")


def _plano(v):
    if isinstance(v, (pd.Timestamp, datetime, date)):
        return pd.Timestamp(v).strftime("%Y-%m-%d") if not pd.isna(v) else ""
    if isinstance(v, bool):
        return "SI" if v else "NO"
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    if hasattr(v, "item"):
        return v.item()
    return v


def _validar_cierre(hoja: str, fechas: list) -> None:
    if hoja not in CON_FECHA:
        return
    cierre = libro()["cfg"].get("fecha_cierre", "").strip()
    if not cierre:
        return
    limite = pd.Timestamp(cierre)
    for f in fechas:
        t = pd.to_datetime(f, errors="coerce")
        if pd.notna(t) and t <= limite:
            raise ValueError(f"El periodo hasta {limite:%Y-%m-%d} está cerrado. "
                             "Un administrador puede cambiar la fecha de cierre en Ajustes.")


def auditar(accion: str, hoja: str, clave: str = "", detalle: str = "") -> None:
    try:
        backend().agregar("Auditoria", [{"fecha_hora": datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S"),
                                         "usuario": usuario().get("codigo", "sistema"), "accion": accion,
                                         "hoja": hoja, "clave": clave, "detalle": detalle[:300]}])
    except Exception:
        pass  # la bitacora nunca debe impedir guardar un registro


# ───────────────────────────── Escritura ─────────────────────────────

def guardar(hoja: str, filas, *, forzar: bool = False, detalle: str = "") -> list[str]:
    """Agrega uno o varios registros. Devuelve las claves creadas."""
    _exigir_escritura(forzar)
    filas = [dict(f) for f in ([filas] if isinstance(filas, dict) else filas)]
    if not filas:
        return []
    _validar_cierre(hoja, [f.get("fecha") for f in filas])
    clave, pref = CLAVES.get(hoja), PREFIJOS.get(hoja)
    for f in filas:
        for k in list(f):
            f[k] = _plano(f[k])
        if pref and clave and not str(f.get(clave, "")).strip():
            f[clave] = nuevo_id(pref)
    backend().agregar(hoja, filas)
    claves = [str(f.get(clave, "")) for f in filas]
    auditar("crear", hoja, claves[0] if len(claves) == 1 else f"{len(claves)} registros", detalle)
    refrescar()
    return claves


def modificar(hoja: str, valor, cambios: dict, *, col: str | None = None, forzar: bool = False,
              accion: str = "editar", detalle: str = "") -> int:
    """Cambia campos de los registros cuya columna `col` (por defecto la clave) vale `valor`."""
    _exigir_escritura(forzar)
    col = col or CLAVES[hoja]
    cambios = {k: _plano(v) for k, v in cambios.items()}
    if hoja in CON_FECHA:
        df = libro()["d"][hoja]
        previas = df.loc[df[col].astype(str) == str(valor), "fecha"].tolist() if "fecha" in df else []
        _validar_cierre(hoja, previas + [cambios.get("fecha")])
    n = backend().actualizar(hoja, col, valor, cambios)
    if n == 0:
        raise KeyError(f"No se encontró {valor} en {hoja}.")
    auditar(accion, hoja, str(valor), detalle or ", ".join(cambios))
    refrescar()
    return n


def anular(hoja: str, valor, *, col: str | None = None, detalle: str = "") -> int:
    return modificar(hoja, valor, {"anulado": "SI"}, col=col, accion="anular", detalle=detalle)


def reemplazar(hoja: str, col: str, valor, filas: list[dict]) -> None:
    """Sustituye las lineas de un documento en borrador (borra y vuelve a escribir)."""
    _exigir_escritura(False)
    backend().borrar(hoja, col, valor)
    if filas:
        clave, pref = CLAVES.get(hoja), PREFIJOS.get(hoja)
        filas = [{k: _plano(v) for k, v in f.items()} for f in filas]
        for f in filas:
            if pref and clave and not str(f.get(clave, "")).strip():
                f[clave] = nuevo_id(pref)
        backend().agregar(hoja, filas)
    auditar("reemplazar lineas", hoja, str(valor), f"{len(filas)} lineas")
    refrescar()


def eliminar(hoja: str, col: str, valor) -> int:
    """Borra filas de catalogos auxiliares (por ejemplo reglas). No se usa en documentos contables."""
    _exigir_escritura(False)
    n = backend().borrar(hoja, col, valor)
    auditar("eliminar", hoja, str(valor))
    refrescar()
    return n


def guardar_config(valores: dict[str, str]) -> None:
    if not es_admin():
        raise PermisoError("Solo un administrador puede cambiar la configuración.")
    actuales = set(libro()["d"]["Config"]["clave"])
    nuevos = []
    for k, v in valores.items():
        if k in actuales:
            backend().actualizar("Config", "clave", k, {"valor": str(v)})
        else:
            nuevos.append({"clave": k, "valor": str(v)})
    if nuevos:
        backend().agregar("Config", nuevos)
    auditar("config", "Config", "", ", ".join(valores))
    refrescar()
