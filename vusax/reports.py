"""Estados financieros y reportes. Funciones puras sobre el libro diario."""

from __future__ import annotations

import pandas as pd

from .config import (CUENTA_IMPUESTO, CUENTA_INV, CUENTA_SUSPENSO, PLAN_CUENTAS, SUB_BANCO,
                     TIPO_ACTIVO, TIPO_CAPITAL, TIPO_COSTO, TIPO_GASTO, TIPO_INGRESO, TIPO_PASIVO)
from .ledger import ESTADOS_EMITIDA, ESTADOS_PAGADA, cuentas_por_cobrar, es_marketplace

DEBITO_NORMAL = {TIPO_ACTIVO, TIPO_COSTO, TIPO_GASTO}
TIPOS_RESULTADO = {TIPO_INGRESO: "Income", TIPO_COSTO: "Cost of Sales", TIPO_GASTO: "Expenses"}


def plan_df(d: dict[str, pd.DataFrame]) -> pd.DataFrame:
    c = d["Cuentas"][["codigo", "nombre", "tipo", "subtipo", "activa"]].copy()
    return c[c["codigo"] != ""].drop_duplicates("codigo").reset_index(drop=True)


def _rango(j: pd.DataFrame, desde=None, hasta=None) -> pd.DataFrame:
    if desde is not None:
        j = j[j["fecha"] >= pd.Timestamp(desde)]
    if hasta is not None:
        j = j[j["fecha"] <= pd.Timestamp(hasta)]
    return j


def saldos(j: pd.DataFrame, coa: pd.DataFrame, desde=None, hasta=None) -> pd.DataFrame:
    """Saldo por cuenta con signo natural (positivo = lado normal de la cuenta)."""
    g = _rango(j, desde, hasta).groupby("cuenta")[["debito", "credito"]].sum().reset_index()
    s = coa.merge(g, left_on="codigo", right_on="cuenta", how="outer")
    s["codigo"] = s["codigo"].fillna(s["cuenta"])
    s["nombre"] = s["nombre"].fillna("(undefined account)")
    s["tipo"] = s["tipo"].fillna(TIPO_ACTIVO)
    s[["debito", "credito"]] = s[["debito", "credito"]].fillna(0.0)
    deb = s["tipo"].isin(DEBITO_NORMAL)
    s["saldo"] = (s["debito"] - s["credito"]).where(deb, s["credito"] - s["debito"]).round(2)
    return s[["codigo", "nombre", "tipo", "subtipo", "debito", "credito", "saldo"]].sort_values("codigo").reset_index(drop=True)


def utilidad(j: pd.DataFrame, coa: pd.DataFrame, desde=None, hasta=None) -> float:
    s = saldos(j, coa, desde, hasta)
    ing = s.loc[s["tipo"] == TIPO_INGRESO, "saldo"].sum()
    return round(float(ing - s.loc[s["tipo"].isin([TIPO_COSTO, TIPO_GASTO]), "saldo"].sum()), 2)


def estado_resultados(j, coa, desde, hasta):
    s = saldos(j, coa, desde, hasta)
    s = s[s["tipo"].isin(TIPOS_RESULTADO) & (s["saldo"].abs() > 0.004)]
    det = s.assign(seccion=s["tipo"].map(TIPOS_RESULTADO))[["seccion", "codigo", "nombre", "saldo"]]
    det = det.rename(columns={"saldo": "monto"})
    t = {k: round(float(det.loc[det["seccion"] == v, "monto"].sum()), 2) for k, v in
         {"ingresos": "Income", "costo": "Cost of Sales", "gastos": "Expenses"}.items()}
    t["utilidad_bruta"] = round(t["ingresos"] - t["costo"], 2)
    t["utilidad_neta"] = round(t["utilidad_bruta"] - t["gastos"], 2)
    return det.reset_index(drop=True), t


def serie_mensual(j, coa, desde, hasta) -> pd.DataFrame:
    x = _rango(j, desde, hasta).merge(coa[["codigo", "tipo"]], left_on="cuenta", right_on="codigo", how="left")
    x = x[x["tipo"].isin(TIPOS_RESULTADO)].copy()
    x["mes"] = x["fecha"].dt.to_period("M").astype(str)
    x["monto"] = (x["credito"] - x["debito"]).where(x["tipo"] == TIPO_INGRESO, x["debito"] - x["credito"])
    p = x.pivot_table(index="mes", columns="tipo", values="monto", aggfunc="sum", fill_value=0.0)
    for c in (TIPO_INGRESO, TIPO_COSTO, TIPO_GASTO):
        if c not in p:
            p[c] = 0.0
    p = p.rename(columns={TIPO_INGRESO: "ingresos", TIPO_COSTO: "costo", TIPO_GASTO: "gastos"})[["ingresos", "costo", "gastos"]]
    p["utilidad"] = p["ingresos"] - p["costo"] - p["gastos"]
    return p.round(2).reset_index()


def resultados_mensual(j, coa, desde, hasta) -> pd.DataFrame:
    """Estado de resultados con una columna por mes."""
    x = _rango(j, desde, hasta).merge(coa[["codigo", "nombre", "tipo"]], left_on="cuenta", right_on="codigo", how="left")
    x = x[x["tipo"].isin(TIPOS_RESULTADO)].copy()
    if x.empty:
        return pd.DataFrame(columns=["seccion", "codigo", "nombre"])
    x["mes"] = x["fecha"].dt.to_period("M").astype(str)
    x["monto"] = (x["credito"] - x["debito"]).where(x["tipo"] == TIPO_INGRESO, x["debito"] - x["credito"])
    x["seccion"] = x["tipo"].map(TIPOS_RESULTADO)
    p = x.pivot_table(index=["seccion", "codigo", "nombre"], columns="mes", values="monto", aggfunc="sum", fill_value=0.0)
    p["Total"] = p.sum(axis=1)
    return p.round(2).reset_index()


def balance_general(j, coa, al, inicio_ejercicio):
    s = saldos(j, coa, hasta=al)
    s = s[s["saldo"].abs() > 0.004]
    filas = []
    for tipo, titulo in ((TIPO_ACTIVO, "Assets"), (TIPO_PASIVO, "Liabilities"), (TIPO_CAPITAL, "Equity")):
        for r in s[s["tipo"] == tipo].itertuples():
            filas.append((titulo, r.codigo, r.nombre, r.saldo))
    ini = pd.Timestamp(inicio_ejercicio)
    previo = utilidad(j, coa, hasta=ini - pd.Timedelta(days=1))
    actual = utilidad(j, coa, desde=ini, hasta=al)
    filas.append(("Equity", "", "Retained Earnings (prior years)", previo))
    filas.append(("Equity", "", "Net Income (current year)", actual))
    det = pd.DataFrame(filas, columns=["seccion", "codigo", "nombre", "monto"])
    tot = {k: round(float(det.loc[det["seccion"] == v, "monto"].sum()), 2)
           for k, v in {"activos": "Assets", "pasivos": "Liabilities", "capital": "Equity"}.items()}
    tot["pasivo_capital"] = round(tot["pasivos"] + tot["capital"], 2)
    tot["cuadra"] = abs(tot["activos"] - tot["pasivo_capital"]) < 0.01
    return det[det["monto"].abs() > 0.004].reset_index(drop=True), tot


def balanza(j, coa, al) -> pd.DataFrame:
    s = saldos(j, coa, hasta=al)
    s = s[(s["debito"] > 0) | (s["credito"] > 0)].copy()
    neto = (s["debito"] - s["credito"]).round(2)
    s["saldo_deudor"] = neto.where(neto > 0, 0.0)
    s["saldo_acreedor"] = (-neto).where(neto < 0, 0.0)
    return s[["codigo", "nombre", "tipo", "debito", "credito", "saldo_deudor", "saldo_acreedor"]].reset_index(drop=True)


def libro_mayor(j, coa, cuenta, desde, hasta) -> pd.DataFrame:
    tipo = coa.loc[coa["codigo"] == cuenta, "tipo"]
    deb = (tipo.iloc[0] in DEBITO_NORMAL) if len(tipo) else True
    sg = 1 if deb else -1
    x = j[j["cuenta"] == cuenta]
    ap = round(sg * float((x[x["fecha"] < pd.Timestamp(desde)]["debito"] - x[x["fecha"] < pd.Timestamp(desde)]["credito"]).sum()), 2)
    m = _rango(x, desde, hasta).copy()
    m["saldo"] = ap + (sg * (m["debito"] - m["credito"])).cumsum()
    apertura = pd.DataFrame([{"fecha": pd.NaT, "ref": "", "origen": "", "memo": "Opening balance", "tercero": "",
                              "debito": 0.0, "credito": 0.0, "saldo": ap}])
    return pd.concat([apertura, m[["fecha", "ref", "origen", "memo", "tercero", "debito", "credito", "saldo"]]],
                     ignore_index=True)


def flujo_efectivo(j, coa, desde, hasta):
    """Estado de flujo de efectivo (metodo indirecto). Efectivo = cuentas de subtipo Bank."""
    ini = pd.Timestamp(desde) - pd.Timedelta(days=1)
    b0 = saldos(j, coa, hasta=ini).set_index("codigo")
    b1 = saldos(j, coa, hasta=hasta).set_index("codigo")
    delta = (b1["saldo"] - b0["saldo"].reindex(b1.index).fillna(0.0)).round(2)
    meta = b1[["nombre", "tipo", "subtipo"]]
    ops, fin = [], []
    for cod, dv in delta.items():
        if abs(dv) < 0.005:
            continue
        nombre, tipo, sub = meta.loc[cod]
        if tipo == TIPO_ACTIVO and sub != SUB_BANCO:
            ops.append((f"Change in {nombre}", -dv))
        elif tipo == TIPO_PASIVO:
            ops.append((f"Change in {nombre}", dv))
        elif tipo == TIPO_CAPITAL:
            fin.append((nombre, dv))
    ni = utilidad(j, coa, desde, hasta)
    bancos = b1.index[b1["subtipo"] == SUB_BANCO]
    inicio_ef = round(float(b0["saldo"].reindex(bancos).fillna(0.0).sum()), 2)
    fin_ef = round(float(b1.loc[bancos, "saldo"].sum()), 2)
    total_ops = round(ni + sum(v for _, v in ops), 2)
    total_fin = round(sum(v for _, v in fin), 2)
    filas = [("Operating", "Net income", ni)] + [("Operating", n, round(v, 2)) for n, v in ops]
    filas += [("Financing", n, round(v, 2)) for n, v in fin]
    det = pd.DataFrame(filas, columns=["seccion", "concepto", "monto"])
    t = {"operacion": total_ops, "financiamiento": total_fin, "cambio": round(total_ops + total_fin, 2),
         "efectivo_inicial": inicio_ef, "efectivo_final": fin_ef,
         "cuadra": abs(total_ops + total_fin - (fin_ef - inicio_ef)) < 0.01}
    return det, t


def antiguedad(abiertas: pd.DataFrame, columna: str) -> pd.DataFrame:
    """Antiguedad de saldos por cliente o proveedor."""
    cubetas = ["Current", "1-30", "31-60", "61-90", "Over 90"]
    a = abiertas[abiertas["saldo"] > 0.004].copy()
    if a.empty:
        return pd.DataFrame(columns=[columna] + cubetas + ["Total"])
    a["cubeta"] = pd.cut(a["dias_vencido"], [-10**6, 0, 30, 60, 90, 10**6], labels=cubetas)
    p = a.pivot_table(index=columna, columns="cubeta", values="saldo", aggfunc="sum", fill_value=0.0, observed=False)
    for c in cubetas:
        if c not in p:
            p[c] = 0.0
    p = p[cubetas]
    p["Total"] = p.sum(axis=1)
    p.loc["TOTAL"] = p.sum()
    return p.round(2).reset_index()


def rentabilidad(ev: pd.DataFrame, por: str) -> pd.DataFrame:
    v = ev[ev["tipo"] == "venta"]
    if v.empty:
        return pd.DataFrame(columns=[por, "unidades", "ingresos", "cargos", "costo", "margen", "margen_pct"])
    g = v.groupby(por).agg(unidades=("qty", "sum"), ingresos=("ingreso", "sum"), cargos=("cargos", "sum"),
                           costo=("valor", "sum")).reset_index()
    g["margen"] = g["ingresos"] - g["cargos"] - g["costo"]
    g["margen_pct"] = (g["margen"] / g["ingresos"].where(g["ingresos"] != 0) * 100).fillna(0.0)
    return g.sort_values("margen", ascending=False).round(2).reset_index(drop=True)


def impuesto_ventas(d, j, coa, desde, hasta) -> pd.DataFrame:
    """Resumen mensual para preparar el DR-15. Es una ayuda de trabajo, no la declaracion."""
    desde, hasta = pd.Timestamp(desde), pd.Timestamp(hasta)
    filas: dict[str, dict] = {}

    def fila(mes):
        return filas.setdefault(mes, {"mes": mes, "ventas_marketplace": 0.0, "ventas_directas": 0.0,
                                      "ventas_facturas_gravables": 0.0, "ventas_facturas_exentas": 0.0,
                                      "impuesto_cobrado": 0.0, "impuesto_pagado": 0.0})

    ing = d["Ingresos"]
    ing = ing[(~ing["anulado"]) & ing["fecha"].between(desde, hasta)]
    for r in ing.itertuples():
        f = fila(r.fecha.strftime("%Y-%m"))
        if es_marketplace(r.canal):
            f["ventas_marketplace"] += r.ingreso_bruto
        else:
            f["ventas_directas"] += r.ingreso_bruto
            f["impuesto_cobrado"] += r.impuesto_cobrado
    totales = (d["Invoice_Items"]["cantidad"] * d["Invoice_Items"]["precio_unit"]).round(2).groupby(d["Invoice_Items"]["num"]).sum()
    inv = d["Invoices"]
    inv = inv[(~inv["anulado"]) & inv["estado"].str.lower().isin(ESTADOS_EMITIDA)
              & inv["fecha"].between(desde, hasta)]
    for r in inv.itertuples():
        f = fila(r.fecha.strftime("%Y-%m"))
        sub = float(totales.get(r.num, 0.0))
        if r.impuesto > 0:
            f["ventas_facturas_gravables"] += sub
            f["impuesto_cobrado"] += r.impuesto
        else:
            f["ventas_facturas_exentas"] += sub
    tx = j[(j["cuenta"] == CUENTA_IMPUESTO) & (j["origen"] == "Bank") & j["fecha"].between(desde, hasta)]
    for r in tx.itertuples():
        fila(r.fecha.strftime("%Y-%m"))["impuesto_pagado"] += r.debito - r.credito
    cols = ["mes", "ventas_marketplace", "ventas_directas", "ventas_facturas_gravables", "ventas_facturas_exentas",
            "impuesto_cobrado", "impuesto_pagado"]
    df = pd.DataFrame(list(filas.values()), columns=cols).sort_values("mes").reset_index(drop=True)
    if df.empty:
        return df
    df.insert(1, "ventas_brutas", df[["ventas_marketplace", "ventas_directas", "ventas_facturas_gravables",
                                       "ventas_facturas_exentas"]].sum(axis=1))
    return df.round(2)


def capital_socios(j, coa, cfg, desde, hasta) -> pd.DataFrame:
    desde, hasta = pd.Timestamp(desde), pd.Timestamp(hasta)
    previo_fin = desde - pd.Timedelta(days=1)
    socios = [(cfg["socio1"], float(cfg["socio1_pct"]), "3010", "3110"),
              (cfg["socio2"], float(cfg["socio2_pct"]), "3020", "3120")]
    util_prev, util_per = utilidad(j, coa, hasta=previo_fin), utilidad(j, coa, desde, hasta)

    def mov(cuenta, desde=None, hasta=None):
        x = _rango(j[j["cuenta"] == cuenta], desde, hasta)
        return float(x["credito"].sum() - x["debito"].sum())

    filas = []
    for nombre, pct, cap, ret in socios:
        k = pct / 100
        inicial = mov(cap, hasta=previo_fin) + mov(ret, hasta=previo_fin) + k * util_prev
        aportes, retiros, util = mov(cap, desde, hasta), -mov(ret, desde, hasta), k * util_per
        filas.append({"socio": nombre, "participacion_pct": pct, "capital_inicial": inicial, "aportes": aportes,
                      "utilidad_asignada": util, "retiros": retiros,
                      "capital_final": inicial + aportes + util - retiros})
    df = pd.DataFrame(filas)
    sin = round(mov("3950", hasta=hasta), 2)
    if abs(sin) > 0.004:
        df.loc[len(df)] = {"socio": "Unallocated opening balances", "participacion_pct": 0.0, "capital_inicial": sin,
                           "aportes": 0.0, "utilidad_asignada": 0.0, "retiros": 0.0, "capital_final": sin}
    df.loc[len(df)] = {"socio": "TOTAL", **{c: df[c].sum() for c in df.columns if c not in ("socio",)}}
    df.loc[df["socio"] == "TOTAL", "participacion_pct"] = df.loc[df["socio"] != "TOTAL", "participacion_pct"].sum()
    return df.round(2)


# ───────────────────────────── Revision de datos ─────────────────────────────

def revision_datos(d, j, coa, inv, al) -> list[tuple[str, str]]:
    """Lista (severidad, mensaje) con problemas que distorsionan los numeros."""
    out: list[tuple[str, str]] = []
    nuevos = lambda sev, n, txt: out.append((sev, f"{n} {txt}")) if n else None

    # Asientos desbalanceados
    por_ref = j.groupby("ref")[["debito", "credito"]].sum()
    malos = por_ref[(por_ref["debito"] - por_ref["credito"]).abs() > 0.01]
    nuevos("alto", len(malos), "unbalanced entries (check the manual journal entries: " + ", ".join(malos.index[:5]) + ")")

    codigos = set(coa["codigo"])
    sin_cuenta = sorted(set(j["cuenta"]) - codigos)
    nuevos("alto", len(sin_cuenta), "accounts used that are not in the chart of accounts: " + ", ".join(sin_cuenta[:8]))

    for hoja, col in (("Ingresos", "fecha"), ("Gastos", "fecha"), ("Invoices", "fecha"), ("Facturas_Prov", "fecha"),
                      ("Transacciones", "fecha")):
        df = d[hoja]
        n = int((~df["anulado"] & df[col].isna()).sum())
        nuevos("alto", n, f"records in {hoja} with no valid date (they are left out of every report)")

    inv_h = d["Invoices"]
    legado = inv_h[inv_h["estado"].str.lower().isin(ESTADOS_PAGADA) & (~inv_h["anulado"])]
    if len(legado):
        ar = cuentas_por_cobrar(d, al)
        sin_pago = ar[(ar["estado"] != "Paid") & ar["num"].isin(legado["num"])]
        nuevos("medio", len(sin_pago), "invoices marked Paid with no payment recorded in Bank (still shown as receivable)")
    huerfanos = set(d["Invoice_Items"]["num"]) - set(inv_h["num"])
    nuevos("medio", len(huerfanos), "invoice numbers with line items but no header")

    skus = set(d["Productos"]["sku"])
    for hoja, col in (("Ingresos", "sku"), ("Invoice_Items", "sku"), ("Bill_Items", "sku")):
        usados = {s for s in d[hoja][col].astype(str).str.strip() if s} - skus
        nuevos("medio", len(usados), f"SKUs in {hoja} that do not exist in Productos: " + ", ".join(sorted(usados)[:5]))

    neg = inv[inv["existencias"] < 0]
    nuevos("medio", len(neg), "products with negative stock (purchases are missing): " + ", ".join(neg["sku"].head(5)))

    x = j[j["cuenta"] == CUENTA_SUSPENSO]
    susp = float(x["debito"].sum() - x["credito"].sum())
    if abs(susp) > 0.004:
        out.append(("medio", f"${abs(susp):,.2f} sitting in 'Uncategorized Asset' (account {CUENTA_SUSPENSO})"))

    sin_cat = d["Gastos"][(~d["Gastos"]["anulado"]) & (d["Gastos"]["cuenta_gasto"] == "")]
    nuevos("bajo", len(sin_cat), "expenses with no account assigned (classified by keyword; better to set it)")

    bal, tot = balance_general(j, coa, al, pd.Timestamp(al).replace(month=1, day=1))
    if not tot["cuadra"]:
        out.append(("alto", f"The balance sheet is out of balance by ${abs(tot['activos'] - tot['pasivo_capital']):,.2f}"))

    val_inv = float(inv["valor"].sum())
    gl_inv = float(saldos(j, coa, hasta=al).set_index("codigo")["saldo"].get(CUENTA_INV, 0.0))
    if abs(val_inv - gl_inv) > 1:
        out.append(("bajo", f"Inventory valued at ${val_inv:,.2f} vs general ledger ${gl_inv:,.2f} (difference from negative stock or dates)"))
    return out


def sembrar_plan() -> pd.DataFrame:
    return pd.DataFrame(PLAN_CUENTAS, columns=["codigo", "nombre", "tipo", "subtipo"]).assign(activa="SI")
