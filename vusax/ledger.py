"""Motor contable: convierte los documentos (ventas, gastos, facturas, banco...) en un
libro diario de partida doble. Todo es funcion pura sobre DataFrames, sin red ni Streamlit,
asi que se puede probar sin conexion.

El diario NO se guarda: se recalcula desde los documentos. Eso evita asientos huerfanos,
descuadres por ediciones y pasos de "contabilizar" que puedan fallar a medias.
"""

from __future__ import annotations

import re
from datetime import date

import pandas as pd

from .config import (
    CANAL_CUENTAS, CANALES_MARKETPLACE, CUENTA_AP, CUENTA_APERTURA, CUENTA_AR, CUENTA_COGS,
    CUENTA_GASTO_DEFECTO, CUENTA_IMPUESTO, CUENTA_INV, CUENTA_MERMA, CUENTA_SUSPENSO,
    CUENTA_TARJETA, CUENTA_VENTAS_B2B, FECHAS, NUMERICAS, PALABRAS_GASTO, SCHEMAS,
)

SI = {"SI", "SÍ", "S", "TRUE", "1", "YES", "Y", "X"}
COLUMNAS_DIARIO = ["fecha", "ref", "origen", "cuenta", "debito", "credito", "memo", "tercero"]
CODIGOS = {
    "Cuentas": ["codigo"], "Gastos": ["cuenta_gasto", "cuenta_pago"], "Ingresos": ["cuenta_cobro"],
    "Bill_Items": ["cuenta"], "Transacciones": ["cuenta", "contrapartida"], "Asientos": ["cuenta"],
    "Conciliaciones": ["cuenta"], "Reglas": ["cuenta"],
}
ESTADOS_EMITIDA = {"enviada", "enviado", "pagada", "pagado", "emitida"}


# ───────────────────────────── Conversion de datos crudos ─────────────────────────────

def num(s: pd.Series) -> pd.Series:
    """Texto de Sheets ('$1,234.50', '(10)') a numero. Vacio o invalido = 0."""
    t = s.astype(str).str.strip().str.replace(r"[\$,\s]", "", regex=True)
    t = t.str.replace(r"^\((.*)\)$", r"-\1", regex=True)
    return pd.to_numeric(t, errors="coerce").fillna(0.0).astype(float)


def parse_fecha(s: pd.Series) -> pd.Series:
    """Acepta ISO, formato local de Sheets (10/22/2026) y numeros seriales de Excel."""
    s = s.astype(object)
    n = pd.to_numeric(s, errors="coerce")
    texto = s.where(n.isna(), None)
    f = pd.to_datetime(texto, errors="coerce", format="mixed")
    serial = pd.to_datetime(n.where(n > 20000), unit="D", origin="1899-12-30", errors="coerce")
    return f.fillna(serial).dt.normalize()


def es_si(s: pd.Series) -> pd.Series:
    return s.astype(str).str.strip().str.upper().isin(SI)


def si(v) -> bool:
    return str(v).strip().upper() in SI


def codigo(v) -> str:
    t = str(v).strip()
    return t[:-2] if re.fullmatch(r"\d+\.0", t) else t


def preparar(raw: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Garantiza todas las hojas y columnas, descarta filas vacias y tipa numeros y fechas."""
    d: dict[str, pd.DataFrame] = {}
    for nombre, cols in SCHEMAS.items():
        df = raw.get(nombre)
        df = pd.DataFrame(columns=cols) if df is None else df.copy()
        for c in cols:
            if c not in df.columns:
                df[c] = ""
        df = df[cols].fillna("").astype(object)
        if len(df):
            vacias = df.astype(str).apply(lambda col: col.str.strip()).eq("").all(axis=1)
            df = df[~vacias]
        d[nombre] = df.reset_index(drop=True)
    for nombre, cols in NUMERICAS.items():
        for c in cols:
            d[nombre][c] = num(d[nombre][c])
    for nombre, cols in FECHAS.items():
        for c in cols:
            d[nombre][c] = parse_fecha(d[nombre][c])
    for nombre, cols in CODIGOS.items():
        for c in cols:
            d[nombre][c] = d[nombre][c].map(codigo)
    for nombre in ("Ingresos", "Gastos", "Invoices", "Facturas_Prov", "Transacciones", "Ajustes_Inv", "Asientos"):
        d[nombre]["anulado"] = es_si(d[nombre]["anulado"])
    # El formulario antiguo repetia el encabezado por cada linea: nos quedamos con el primero.
    d["Invoices"] = d["Invoices"].drop_duplicates("num", keep="first").reset_index(drop=True)
    return d


def leer_config(df: pd.DataFrame) -> dict[str, str]:
    from .config import CONFIG_DEFECTO
    cfg = dict(CONFIG_DEFECTO)
    for r in df.itertuples():
        if str(r.clave).strip():
            cfg[str(r.clave).strip()] = str(r.valor).strip()
    return cfg


# ───────────────────────────── Reglas de cuentas ─────────────────────────────

def cuentas_canal(canal: str) -> tuple[str, str | None]:
    k = str(canal).strip().lower()
    if k in CANAL_CUENTAS:
        return CANAL_CUENTAS[k]
    for clave, v in CANAL_CUENTAS.items():
        if clave.split()[0] in k and k:
            return v
    return ("4090", None)


def es_marketplace(canal: str) -> bool:
    k = str(canal).strip().lower()
    return any(m.split()[0] in k for m in CANALES_MARKETPLACE) and bool(k)


def mapear_categoria(categoria: str) -> str:
    t = str(categoria).strip().lower()
    if re.fullmatch(r"\d{4}", t):
        return t
    for patron, cuenta in PALABRAS_GASTO:
        if re.search(patron, t):
            return cuenta
    return CUENTA_GASTO_DEFECTO


# ───────────────────────────── Costo de inventario (promedio ponderado) ─────────────────────────────

_ORDEN = {"compra": 0, "ajuste": 1, "venta": 2}


def costear(eventos: list[dict], productos: pd.DataFrame, inicio: pd.Timestamp):
    """Procesa compras, ajustes y ventas en orden cronologico con costo promedio movil.

    productos.stock y productos.costo son la posicion de apertura al `inicio`. Los eventos
    anteriores a esa fecha se valoran a costo estandar y no mueven existencias.
    Devuelve (eventos con 'valor', estado por sku, valor de apertura).
    """
    est: dict[str, dict] = {}
    for p in productos.itertuples():
        sku = str(p.sku).strip()
        if sku:
            est[sku] = {"qty": float(p.stock), "avg": float(p.costo), "std": float(p.costo),
                        "q0": float(p.stock), "c0": float(p.costo)}
    out = []
    for e in sorted(eventos, key=lambda e: (e["fecha"], _ORDEN[e["tipo"]], e["seq"])):
        e = dict(e)
        s = est.setdefault(e["sku"], {"qty": 0.0, "avg": 0.0, "std": 0.0, "q0": 0.0, "c0": 0.0})
        previo = e["fecha"] < inicio
        q = e["qty"]
        if e["tipo"] == "compra":
            e["valor"] = round(q * e["costo"], 2)
            if not previo:
                base = max(s["qty"], 0.0)
                total = base + q
                s["avg"] = (base * s["avg"] + q * e["costo"]) / total if total > 0 else e["costo"]
                s["qty"] += q
        else:
            unit = s["std"] if previo else (s["avg"] or s["std"])
            e["valor"] = round(q * unit, 2)
            if not previo:
                s["qty"] += q if e["tipo"] == "ajuste" else -q
        out.append(e)
    apertura = round(sum(s["q0"] * s["c0"] for s in est.values()), 2)
    return out, est, apertura


# ───────────────────────────── Libro diario ─────────────────────────────

def construir_diario(d: dict[str, pd.DataFrame], cfg: dict[str, str]):
    """Devuelve (diario, estado de inventario, eventos de inventario)."""
    filas: list[tuple] = []
    eventos: list[dict] = []
    seq = [0]

    def L(ref, origen, fecha, cuenta, deb=0.0, cred=0.0, memo="", tercero=""):
        neto = round(float(deb) - float(cred), 2)
        if neto == 0 or not cuenta:
            return
        filas.append((fecha, ref, origen, str(cuenta), neto if neto > 0 else 0.0,
                      -neto if neto < 0 else 0.0, str(memo), str(tercero)))

    def evento(tipo, fecha, sku, qty, costo=0.0, ref="", ingreso=0.0, canal="", cargos=0.0):
        sku = str(sku).strip()
        if not sku or qty == 0:
            return
        seq[0] += 1
        eventos.append({"fecha": fecha, "tipo": tipo, "sku": sku, "qty": float(qty), "costo": float(costo),
                        "ref": ref, "ingreso": float(ingreso), "canal": canal, "cargos": float(cargos),
                        "seq": seq[0]})

    banco = cfg["banco_defecto"]

    # Ventas de marketplace y canales directos
    for r in d["Ingresos"].itertuples():
        if r.anulado or pd.isna(r.fecha):
            continue
        ref = f"ING:{r.id}"
        ventas, cobro = cuentas_canal(r.canal)
        cobro = r.cuenta_cobro or cobro or banco
        bruto, com, tar, env = (round(x, 2) for x in (r.ingreso_bruto, r.comisiones, r.tarifas, r.envio))
        impuesto = 0.0 if es_marketplace(r.canal) else round(r.impuesto_cobrado, 2)
        memo = f"{r.canal} {r.id_orden}".strip()
        L(ref, "Venta", r.fecha, cobro, deb=bruto - com - tar - env + impuesto, memo=memo)
        L(ref, "Venta", r.fecha, "6010", deb=com, memo=memo)
        L(ref, "Venta", r.fecha, "6020", deb=tar, memo=memo)
        L(ref, "Venta", r.fecha, "6030", deb=env, memo=memo)
        L(ref, "Venta", r.fecha, ventas, cred=bruto, memo=memo)
        L(ref, "Venta", r.fecha, CUENTA_IMPUESTO, cred=impuesto, memo=memo)
        evento("venta", r.fecha, r.sku, r.cantidad, ref=ref, ingreso=bruto, canal=str(r.canal),
               cargos=com + tar + env)

    # Gastos (tarjeta, efectivo o banco)
    for r in d["Gastos"].itertuples():
        if r.anulado or pd.isna(r.fecha):
            continue
        ref = f"GAS:{r.id}"
        gasto = r.cuenta_gasto or mapear_categoria(r.categoria)
        pago = r.cuenta_pago or (CUENTA_TARJETA if str(r.metodo).strip().lower().startswith("tarjeta") else banco)
        monto = round(r.monto, 2)
        L(ref, "Gasto", r.fecha, gasto, deb=monto, memo=r.descripcion or r.categoria, tercero=r.proveedor)
        L(ref, "Gasto", r.fecha, pago, cred=monto, memo=r.descripcion or r.categoria, tercero=r.proveedor)

    # Facturas de venta emitidas
    items = d["Invoice_Items"].copy()
    items["monto"] = (items["cantidad"] * items["precio_unit"]).round(2)
    por_factura = {n: g for n, g in items.groupby("num")}
    for r in d["Invoices"].itertuples():
        if r.anulado or pd.isna(r.fecha) or str(r.estado).strip().lower() not in ESTADOS_EMITIDA:
            continue
        g = por_factura.get(r.num)
        if g is None:
            continue
        ref = f"FAC:{r.num}"
        sub, imp = round(g["monto"].sum(), 2), round(r.impuesto, 2)
        L(ref, "Factura", r.fecha, CUENTA_AR, deb=sub + imp, memo=r.num, tercero=r.cliente)
        L(ref, "Factura", r.fecha, CUENTA_VENTAS_B2B, cred=sub, memo=r.num, tercero=r.cliente)
        L(ref, "Factura", r.fecha, CUENTA_IMPUESTO, cred=imp, memo=r.num, tercero=r.cliente)
        for it in g.itertuples():
            evento("venta", r.fecha, it.sku, it.cantidad, ref=ref, ingreso=it.monto, canal="Facturas B2B")

    # Facturas de proveedor
    bi = d["Bill_Items"].copy()
    bi["monto"] = (bi["cantidad"] * bi["costo_unit"]).round(2)
    por_bill = {n: g for n, g in bi.groupby("id_bill")}
    for r in d["Facturas_Prov"].itertuples():
        if r.anulado or pd.isna(r.fecha):
            continue
        g = por_bill.get(r.id)
        if g is None:
            continue
        ref = f"BIL:{r.id}"
        memo = f"{r.proveedor} {r.num}".strip()
        for it in g.itertuples():
            if str(it.sku).strip():
                L(ref, "Compra", r.fecha, CUENTA_INV, deb=it.monto, memo=memo, tercero=r.proveedor)
                evento("compra", r.fecha, it.sku, it.cantidad, costo=it.costo_unit, ref=ref)
            else:
                L(ref, "Compra", r.fecha, it.cuenta or CUENTA_GASTO_DEFECTO, deb=it.monto, memo=it.descripcion or memo,
                  tercero=r.proveedor)
        L(ref, "Compra", r.fecha, CUENTA_AP, cred=round(g["monto"].sum(), 2), memo=memo, tercero=r.proveedor)

    # Registro bancario
    for r in d["Transacciones"].itertuples():
        if r.anulado or pd.isna(r.fecha) or r.monto == 0:
            continue
        ref = f"TRX:{r.id}"
        contra = r.contrapartida or CUENTA_SUSPENSO
        m = round(r.monto, 2)
        L(ref, "Banco", r.fecha, r.cuenta, deb=m, memo=r.descripcion, tercero=r.tercero)
        L(ref, "Banco", r.fecha, contra, cred=m, memo=r.descripcion, tercero=r.tercero)

    # Ajustes de inventario
    for r in d["Ajustes_Inv"].itertuples():
        if r.anulado or pd.isna(r.fecha):
            continue
        evento("ajuste", r.fecha, r.sku, r.cantidad, ref=f"AJU:{r.id}")

    # Asientos manuales
    for r in d["Asientos"].itertuples():
        if r.anulado or pd.isna(r.fecha):
            continue
        L(f"ASI:{r.asiento}", "Asiento manual", r.fecha, r.cuenta, deb=r.debito, cred=r.credito, memo=r.memo)

    # Costos de inventario
    inicio = pd.Timestamp(cfg.get("inventario_inicio") or "2000-01-01")
    prod = d["Productos"]
    ev, est, apertura = costear(eventos, prod, inicio)
    neto_previo = 0.0
    for e in ev:
        v = e["valor"]
        if e["fecha"] < inicio:
            neto_previo += v if e["tipo"] in ("compra", "ajuste") else -v
        if e["tipo"] == "venta":
            L(e["ref"], "Costo", e["fecha"], CUENTA_COGS, deb=v, memo=e["sku"])
            L(e["ref"], "Costo", e["fecha"], CUENTA_INV, cred=v, memo=e["sku"])
        elif e["tipo"] == "ajuste":
            L(e["ref"], "Ajuste", e["fecha"], CUENTA_MERMA, deb=-v, memo=e["sku"])
            L(e["ref"], "Ajuste", e["fecha"], CUENTA_INV, deb=v, memo=e["sku"])
    plug = round(apertura - neto_previo, 2)
    L("INV:APERTURA", "Apertura", inicio, CUENTA_INV, deb=plug, memo="Existencias iniciales")
    L("INV:APERTURA", "Apertura", inicio, CUENTA_APERTURA, cred=plug, memo="Existencias iniciales")

    diario = pd.DataFrame(filas, columns=COLUMNAS_DIARIO)
    diario["fecha"] = pd.to_datetime(diario["fecha"])
    diario = diario.sort_values(["fecha", "ref"], kind="stable").reset_index(drop=True)

    ev_df = pd.DataFrame(ev, columns=["fecha", "tipo", "sku", "qty", "costo", "ref", "ingreso", "canal",
                                      "cargos", "seq", "valor"])
    filas_inv = []
    nombres = prod.set_index("sku")[["nombre", "categoria", "precio", "stock_min", "activo"]].to_dict("index")
    for sku, s in est.items():
        info = nombres.get(sku, {})
        filas_inv.append({
            "sku": sku, "nombre": info.get("nombre", "(no esta en Productos)"),
            "categoria": info.get("categoria", ""), "precio": info.get("precio", 0.0),
            "stock_min": info.get("stock_min", 0.0), "activo": info.get("activo", ""),
            "apertura_qty": s["q0"], "apertura_costo": s["c0"], "existencias": round(s["qty"], 4),
            "costo_prom": round(s["avg"], 4), "valor": round(max(s["qty"], 0) * s["avg"], 2),
        })
    inv_df = pd.DataFrame(filas_inv, columns=["sku", "nombre", "categoria", "precio", "stock_min", "activo",
                                              "apertura_qty", "apertura_costo", "existencias", "costo_prom", "valor"])
    return diario, inv_df, ev_df


# ───────────────────────────── Cuentas por cobrar y por pagar ─────────────────────────────

def _estado_doc(total, pagado, vence, al):
    saldo = round(total - pagado, 2)
    if saldo <= 0.005:
        return "Pagada"
    if pd.notna(vence) and vence < al:
        return "Vencida"
    return "Parcial" if pagado > 0.005 else "Abierta"


def cuentas_por_cobrar(d: dict[str, pd.DataFrame], al: pd.Timestamp) -> pd.DataFrame:
    items = d["Invoice_Items"]
    totales = (items["cantidad"] * items["precio_unit"]).round(2).groupby(items["num"]).sum()
    tx = d["Transacciones"]
    tx = tx[(~tx["anulado"]) & (tx["aplica_tipo"].str.upper() == "FAC") & (tx["fecha"] <= al)]
    pagos = tx.groupby("aplica_id")["monto"].sum()
    filas = []
    for r in d["Invoices"].itertuples():
        if r.anulado or pd.isna(r.fecha) or r.fecha > al or str(r.estado).strip().lower() not in ESTADOS_EMITIDA:
            continue
        total = round(totales.get(r.num, 0.0) + r.impuesto, 2)
        pagado = round(float(pagos.get(r.num, 0.0)), 2)
        vence = r.vence if pd.notna(r.vence) else r.fecha + pd.Timedelta(days=int(r.terminos or 0))
        filas.append({"num": r.num, "cliente": r.cliente, "fecha": r.fecha, "vence": vence, "total": total,
                      "pagado": pagado, "saldo": round(total - pagado, 2),
                      "dias_vencido": (al - vence).days, "estado": _estado_doc(total, pagado, vence, al)})
    return pd.DataFrame(filas, columns=["num", "cliente", "fecha", "vence", "total", "pagado", "saldo",
                                        "dias_vencido", "estado"])


def cuentas_por_pagar(d: dict[str, pd.DataFrame], al: pd.Timestamp) -> pd.DataFrame:
    bi = d["Bill_Items"]
    totales = (bi["cantidad"] * bi["costo_unit"]).round(2).groupby(bi["id_bill"]).sum()
    tx = d["Transacciones"]
    tx = tx[(~tx["anulado"]) & (tx["aplica_tipo"].str.upper() == "BILL") & (tx["fecha"] <= al)]
    pagos = -tx.groupby("aplica_id")["monto"].sum()
    terminos = d["Proveedores"].set_index("id_proveedor")["terminos"].to_dict()
    filas = []
    for r in d["Facturas_Prov"].itertuples():
        if r.anulado or pd.isna(r.fecha) or r.fecha > al:
            continue
        total = round(float(totales.get(r.id, 0.0)), 2)
        pagado = round(float(pagos.get(r.id, 0.0)), 2)
        vence = r.vence if pd.notna(r.vence) else r.fecha + pd.Timedelta(days=int(terminos.get(r.id_proveedor, 30) or 30))
        filas.append({"id": r.id, "num": r.num, "proveedor": r.proveedor, "fecha": r.fecha, "vence": vence,
                      "total": total, "pagado": pagado, "saldo": round(total - pagado, 2),
                      "dias_vencido": (al - vence).days, "estado": _estado_doc(total, pagado, vence, al)})
    return pd.DataFrame(filas, columns=["id", "num", "proveedor", "fecha", "vence", "total", "pagado", "saldo",
                                        "dias_vencido", "estado"])


def siguiente_numero(prefijo: str, existentes: list[str]) -> str:
    mayor = 1000
    for n in existentes:
        m = re.search(r"(\d+)\s*$", str(n))
        if m and str(n).startswith(prefijo):
            mayor = max(mayor, int(m.group(1)))
    return f"{prefijo}{mayor + 1}"


def hoy() -> pd.Timestamp:
    return pd.Timestamp(date.today())
