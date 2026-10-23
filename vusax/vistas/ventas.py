"""Ventas: facturas a clientes, ventas de marketplace, clientes y cobros."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from .. import db, exports, ledger
from ..config import SUB_BANCO
from . import comun
from .comun import usd

# Estados que se guardan en la hoja Invoices.
EST_BORRADOR, EST_ENVIADA = "Draft", "Sent"


def _s(v) -> str:
    return "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v).strip()


def _f(v) -> float:
    return 0.0 if v is None or pd.isna(v) else float(v)


def _facturas_df(d: dict) -> pd.DataFrame:
    items = d["Invoice_Items"]
    totales = (items["cantidad"] * items["precio_unit"]).round(2).groupby(items["num"]).sum()
    ar = ledger.cuentas_por_cobrar(d, ledger.hoy()).set_index("num")
    filas = []
    for r in d["Invoices"].itertuples():
        sub = round(float(totales.get(r.num, 0.0)), 2)
        total = round(sub + r.impuesto, 2)
        if r.anulado:
            estado, pagado, saldo = "Void", 0.0, 0.0
        elif str(r.estado).strip().lower() in ("draft", "borrador"):
            estado, pagado, saldo = EST_BORRADOR, 0.0, total
        elif r.num in ar.index:
            estado, pagado, saldo = ar.loc[r.num, "estado"], ar.loc[r.num, "pagado"], ar.loc[r.num, "saldo"]
        else:
            estado, pagado, saldo = EST_ENVIADA, 0.0, total
        filas.append({"num": r.num, "cliente": r.cliente, "fecha": r.fecha, "vence": r.vence, "subtotal": sub,
                      "impuesto": r.impuesto, "total": total, "pagado": pagado, "saldo": saldo, "estado": estado})
    cols = ["num", "cliente", "fecha", "vence", "subtotal", "impuesto", "total", "pagado", "saldo", "estado"]
    return pd.DataFrame(filas, columns=cols).sort_values("fecha", ascending=False).reset_index(drop=True)


def _lineas_limpias(df: pd.DataFrame, prod: pd.DataFrame) -> list[dict]:
    precios = prod.set_index("sku")["precio"].to_dict()
    nombres = prod.set_index("sku")["nombre"].to_dict()
    out = []
    for r in df.to_dict("records"):
        sku, desc = _s(r.get("sku")), _s(r.get("descripcion"))
        cant = _f(r.get("cantidad"))
        precio = _f(r.get("precio_unit")) or float(precios.get(sku, 0.0))
        if not sku and not desc and precio == 0:
            continue
        out.append({"sku": sku, "descripcion": desc or nombres.get(sku, ""), "cantidad": cant, "precio_unit": precio})
    return out


# ───────────────────────────── Facturas ─────────────────────────────

def _nueva_factura(d, cfg, coa) -> None:
    prod = d["Productos"]
    prod = prod[prod["activo"].astype(str).str.upper() != "NO"]
    clientes = d["Clientes"][d["Clientes"]["activo"].astype(str).str.upper() != "NO"]
    n = st.session_state.setdefault("fac_n", 0)
    nuevo = "(new customer)"
    c1, c2, c3 = st.columns(3)
    sel = c1.selectbox("Customer", [nuevo] + clientes["id_cliente"].tolist(), key=f"fac_cli_{n}",
                       format_func=lambda v: v if v == nuevo else clientes.set_index("id_cliente").loc[v, "nombre"])
    rec = clientes[clientes["id_cliente"] == sel].iloc[0] if sel != nuevo else None
    nombre_nuevo = c1.text_input("New customer name", key=f"fac_nn_{n}") if rec is None else ""
    fecha = c2.date_input("Date", date.today(), key=f"fac_f_{n}")
    term_def = int(rec["terminos"]) if rec is not None and rec["terminos"] else int(float(cfg["terminos_defecto"]))
    terminos = c3.number_input("Payment terms (days)", min_value=0, value=term_def, step=1, key=f"fac_t_{n}_{sel}")
    exento_def = rec is not None and str(rec["exento_impuesto"]).upper() in ("SI", "SÍ", "YES")
    e1, e2 = st.columns(2)
    exento = e1.checkbox("Tax exempt customer (resale certificate)", value=exento_def, key=f"fac_ex_{n}_{sel}")
    tasa = e2.number_input("Sales tax %", 0.0, 20.0, 0.0 if exento else float(cfg["tasa_impuesto"]),
                           step=0.1, key=f"fac_tasa_{n}_{exento}")

    base = pd.DataFrame([{"sku": None, "descripcion": "", "cantidad": 1.0, "precio_unit": 0.0}])
    lineas = st.data_editor(
        base, num_rows="dynamic", key=f"fac_l_{n}", width="stretch",
        column_config={
            "sku": st.column_config.SelectboxColumn("SKU", options=prod["sku"].tolist(), required=False),
            "descripcion": st.column_config.TextColumn("Description (if blank, uses the product name)"),
            "cantidad": st.column_config.NumberColumn("Qty", min_value=0.0, step=1.0),
            "precio_unit": st.column_config.NumberColumn("Price (0 uses the catalog price)", format="dollar", min_value=0.0),
        })
    filas = _lineas_limpias(lineas, prod)
    sub = round(sum(round(f["cantidad"] * f["precio_unit"], 2) for f in filas), 2)
    imp = round(sub * tasa / 100, 2)
    a, b, c = st.columns(3)
    a.metric("Subtotal", usd(sub))
    b.metric("Sales tax", usd(imp))
    c.metric("Total", usd(sub + imp))
    notas = st.text_input("Notes for the customer", key=f"fac_nt_{n}")

    def guardar(estado: str):
        if not filas or sub <= 0:
            st.error("Add at least one line with quantity and price.")
            return
        if rec is None and not nombre_nuevo.strip():
            st.error("Enter the new customer's name.")
            return
        try:
            if rec is None:
                id_cli = db.guardar("Clientes", {"nombre": nombre_nuevo.strip(), "terminos": terminos,
                                                 "exento_impuesto": "SI" if exento else "NO", "activo": "SI"})[0]
                nombre = nombre_nuevo.strip()
            else:
                id_cli, nombre = sel, rec["nombre"]
            num = ledger.siguiente_numero(cfg["prefijo_factura"], d["Invoices"]["num"].tolist())
            db.guardar("Invoices", {"num": num, "fecha": fecha, "id_cliente": id_cli, "cliente": nombre,
                                    "estado": estado, "impuesto": imp, "vence": fecha + timedelta(days=int(terminos)),
                                    "terminos": terminos, "notas": notas, "impuesto_pct": tasa})
            db.guardar("Invoice_Items", [{"num": num, **f} for f in filas])
        except Exception as e:
            st.error(str(e))
            return
        st.session_state["fac_n"] = n + 1
        st.session_state["_flash"] = f"Invoice {num} saved as {estado.lower()}."
        st.rerun()

    g1, g2, _ = st.columns([1, 1, 3])
    if g1.button("Save draft", key=f"fac_b_{n}"):
        guardar(EST_BORRADOR)
    if g2.button("Save and issue", type="primary", key=f"fac_e_{n}"):
        guardar(EST_ENVIADA)


def _detalle_factura(d, cfg, coa, fac: pd.DataFrame) -> None:
    if fac.empty:
        return
    num = st.selectbox("View invoice", fac["num"].tolist(), key="fac_ver")
    f = fac[fac["num"] == num].iloc[0]
    enc = d["Invoices"][d["Invoices"]["num"] == num].iloc[0]
    items = d["Invoice_Items"][d["Invoice_Items"]["num"] == num]
    tx = d["Transacciones"]
    pagos = tx[(~tx["anulado"]) & (tx["aplica_tipo"].str.upper() == "FAC") & (tx["aplica_id"] == num)]
    with st.container(border=True):
        a, b, c, e = st.columns(4)
        a.metric("Status", f["estado"])
        b.metric("Total", usd(f["total"]))
        c.metric("Paid", usd(f["pagado"]))
        e.metric("Balance", usd(f["saldo"] if f["estado"] not in ("Void",) else 0))
        comun.tabla(items[["sku", "descripcion", "cantidad", "precio_unit"]], dinero=["precio_unit"])
        if len(pagos):
            st.markdown("**Payments received**")
            comun.tabla(pagos[["id", "fecha", "cuenta", "monto", "descripcion"]], dinero=["monto"], fechas=["fecha"])
        cliente = d["Clientes"][d["Clientes"]["id_cliente"] == enc["id_cliente"]]
        pdf = exports.factura_pdf(cfg, {"num": num, "fecha": comun.fecha_txt(enc["fecha"]), "vence": comun.fecha_txt(enc["vence"]),
                                        "cliente": enc["cliente"], "impuesto": enc["impuesto"],
                                        "impuesto_pct": enc["impuesto_pct"], "notas": enc["notas"]},
                                  cliente.iloc[0].to_dict() if len(cliente) else {}, items, float(f["pagado"]))
        st.download_button("Download PDF", pdf, f"{num}.pdf", mime="application/pdf", key=f"pdf_{num}")

    if not db.puede_escribir() or f["estado"] == "Void":
        return
    if f["estado"] == EST_BORRADOR:
        c1, c2, _ = st.columns([1, 1, 3])
        if c1.button("Issue invoice", type="primary", key=f"emi_{num}"):
            if comun.intentar(db.modificar, "Invoices", num, {"estado": EST_ENVIADA}, accion="emitir", ok=f"{num} issued."):
                st.rerun()
        if c2.button("Delete draft", key=f"del_{num}"):
            if comun.intentar(db.anular, "Invoices", num, ok=f"{num} deleted."):
                st.rerun()
        return
    if f["saldo"] > 0.004:
        with st.form(f"cobro_{num}"):
            st.markdown("**Record payment**")
            x1, x2, x3 = st.columns(3)
            fc = x1.date_input("Payment date", date.today())
            monto = x2.number_input("Amount", min_value=0.01, value=float(f["saldo"]), step=0.01)
            bancos = comun.cuentas_opciones(coa, subtipos=[SUB_BANCO])
            banco = x3.selectbox("Deposited to", list(bancos), format_func=lambda k: bancos[k],
                                 index=list(bancos).index(cfg["banco_defecto"]) if cfg["banco_defecto"] in bancos else 0)
            ok = st.form_submit_button("Record payment", type="primary")
        if ok:
            if monto > f["saldo"] + 0.005:
                st.error("The payment cannot exceed the invoice balance.")
            elif comun.intentar(db.guardar, "Transacciones", {
                    "fecha": fc, "cuenta": banco, "descripcion": f"Payment {num}", "monto": monto, "contrapartida": "1100",
                    "tercero": f["cliente"], "aplica_tipo": "FAC", "aplica_id": num}, ok=f"Payment of {usd(monto)} recorded."):
                st.rerun()
    c1, c2 = st.columns(2)
    if len(pagos):
        pid = c1.selectbox("Void a payment", pagos["id"].tolist(), key=f"apago_{num}")
        if c1.button("Void payment", key=f"bapago_{num}"):
            if comun.intentar(db.anular, "Transacciones", pid, ok="Payment voided."):
                st.rerun()
    elif c2.button("Void invoice", key=f"anu_{num}"):
        if comun.intentar(db.anular, "Invoices", num, ok=f"{num} voided."):
            st.rerun()


def _tab_facturas(d, cfg, coa) -> None:
    fac = _facturas_df(d)
    if len(fac):
        v = fac[~fac["estado"].isin(["Void", EST_BORRADOR])]
        a, b, c = st.columns(3)
        a.metric("Receivable", usd(v["saldo"].sum()))
        b.metric("Overdue", usd(v.loc[v["estado"] == "Overdue", "saldo"].sum()))
        c.metric("Collected (all time)", usd(v["pagado"].sum()))
        filtro = st.multiselect("Status", sorted(fac["estado"].unique()), default=[e for e in fac["estado"].unique() if e != "Void"])
        comun.tabla(fac[fac["estado"].isin(filtro)], dinero=["subtotal", "impuesto", "total", "pagado", "saldo"],
                    fechas=["fecha", "vence"])
    else:
        st.info("No invoices yet.")
    if not comun.solo_lectura():
        with st.expander("New invoice", expanded=not len(fac)):
            _nueva_factura(d, cfg, coa)
    _detalle_factura(d, cfg, coa, fac)


# ───────────────────────────── Ventas de marketplace ─────────────────────────────

SINONIMOS = {"date": "fecha", "order": "id_orden", "order_id": "id_orden", "orden": "id_orden", "channel": "canal",
             "quantity": "cantidad", "qty": "cantidad", "gross": "ingreso_bruto", "ventas": "ingreso_bruto",
             "bruto": "ingreso_bruto", "fees": "comisiones", "referral_fee": "comisiones", "comision": "comisiones",
             "fulfillment": "tarifas", "shipping": "envio", "tax": "impuesto_cobrado", "impuesto": "impuesto_cobrado"}
COLS_VENTA = ["fecha", "canal", "id_orden", "sku", "cantidad", "ingreso_bruto", "comisiones", "tarifas", "envio",
              "impuesto_cobrado"]


def _importar(d) -> None:
    plantilla = pd.DataFrame(columns=COLS_VENTA)
    st.download_button("Download CSV template", exports.a_csv(plantilla), "sales_template.csv", mime="text/csv")
    arch = st.file_uploader("Sales CSV", type="csv", key="imp_ventas")
    if not arch:
        return
    try:
        df = pd.read_csv(arch, dtype=str).fillna("")
    except Exception as e:
        st.error(f"I could not read the file: {e}")
        return
    df.columns = [SINONIMOS.get(c.strip().lower(), c.strip().lower()) for c in df.columns]
    faltan = [c for c in ("fecha", "canal", "ingreso_bruto") if c not in df.columns]
    if faltan:
        st.error("Required columns are missing: " + ", ".join(faltan))
        return
    for c in COLS_VENTA:
        if c not in df:
            df[c] = ""
    df["_fecha"] = ledger.parse_fecha(df["fecha"])
    for c in ("cantidad", "ingreso_bruto", "comisiones", "tarifas", "envio", "impuesto_cobrado"):
        df[c] = ledger.num(df[c])
    existentes = d["Ingresos"]
    claves = set(zip(existentes["canal"].str.lower(), existentes["id_orden"], existentes["sku"]))
    df["duplicada"] = [bool(o) and (c.lower(), o, s) in claves for c, o, s in zip(df["canal"], df["id_orden"], df["sku"])]
    malas = df["_fecha"].isna()
    st.write(f"{len(df)} rows read, {int(malas.sum())} with an invalid date, {int(df['duplicada'].sum())} already recorded.")
    buenas = df[~malas & ~df["duplicada"]]
    comun.tabla(buenas[COLS_VENTA].head(50))
    if len(buenas) and st.button(f"Import {len(buenas)} sales", type="primary", key="imp_go"):
        filas = [{**{c: r[c] for c in COLS_VENTA}, "fecha": r["_fecha"]} for _, r in buenas.iterrows()]
        if comun.intentar(db.guardar, "Ingresos", filas, ok=f"{len(filas)} sales imported.", detalle="importacion CSV"):
            st.rerun()


def _tab_ventas(d, cfg, coa) -> None:
    ing = d["Ingresos"]
    canales = [c.strip() for c in cfg["canales"].split(",") if c.strip()]
    if not comun.solo_lectura():
        with st.expander("Record sale", expanded=False):
            skus = [""] + d["Productos"]["sku"].tolist()
            cobro_op = {"": "Automatic, based on the channel"} | comun.cuentas_opciones(coa, subtipos=[SUB_BANCO, "Pending Settlement"])
            with st.form("nueva_venta"):
                c1, c2, c3 = st.columns(3)
                fecha = c1.date_input("Date", date.today())
                canal = c2.selectbox("Channel", canales)
                orden = c3.text_input("Order ID")
                sku = c1.selectbox("SKU", skus)
                cant = c2.number_input("Qty", min_value=0.0, value=1.0, step=1.0)
                bruto = c3.number_input("Gross revenue (before tax)", min_value=0.0, step=0.01)
                com = c1.number_input("Referral fee", min_value=0.0, step=0.01)
                tar = c2.number_input("Fulfillment fees", min_value=0.0, step=0.01)
                env = c3.number_input("Shipping paid", min_value=0.0, step=0.01)
                imp = c1.number_input("Sales tax collected (direct channels only)", min_value=0.0, step=0.01)
                cobro = c2.selectbox("Deposit account", list(cobro_op), format_func=lambda k: cobro_op[k])
                ok = st.form_submit_button("Record", type="primary")
            if ok:
                if bruto <= 0:
                    st.error("Gross revenue must be greater than zero.")
                elif comun.intentar(db.guardar, "Ingresos", {
                        "fecha": fecha, "canal": canal, "id_orden": orden, "sku": sku, "cantidad": cant,
                        "ingreso_bruto": bruto, "comisiones": com, "tarifas": tar, "envio": env,
                        "impuesto_cobrado": imp, "cuenta_cobro": cobro}, ok="Sale recorded."):
                    st.rerun()
        with st.expander("Import sales from CSV"):
            _importar(d)
    act = ing[~ing["anulado"]].copy()
    if act.empty:
        st.info("No sales yet.")
        return
    act["neto"] = act["ingreso_bruto"] - act["comisiones"] - act["tarifas"] - act["envio"]
    f1, f2 = st.columns(2)
    canal_f = f1.multiselect("Channel", sorted(act["canal"].unique()), default=sorted(act["canal"].unique()))
    texto = f2.text_input("Search by order or SKU")
    v = act[act["canal"].isin(canal_f)]
    if texto:
        v = v[v["id_orden"].str.contains(texto, case=False) | v["sku"].str.contains(texto, case=False)]
    v = v.sort_values("fecha", ascending=False)
    a, b, c = st.columns(3)
    a.metric("Gross sales", usd(v["ingreso_bruto"].sum()))
    b.metric("Referral and fulfillment fees", usd(v[["comisiones", "tarifas", "envio"]].sum().sum()))
    c.metric("Net before cost", usd(v["neto"].sum()))
    comun.tabla(v[["id", "fecha", "canal", "id_orden", "sku", "cantidad", "ingreso_bruto", "comisiones", "tarifas",
                   "envio", "neto"]].head(500), dinero=["ingreso_bruto", "comisiones", "tarifas", "envio", "neto"], fechas=["fecha"])
    if db.puede_escribir():
        sel = st.selectbox("Void a sale", [""] + v["id"].head(200).tolist(), key="anu_venta")
        if sel and st.button("Void sale", key="anu_venta_b"):
            if comun.intentar(db.anular, "Ingresos", sel, ok="Sale voided."):
                st.rerun()


# ───────────────────────────── Pantalla ─────────────────────────────

def ventas() -> None:
    comun.flash()
    L = db.libro()
    d, cfg, coa = L["d"], L["cfg"], L["coa"]
    st.title("Sales")
    t1, t2, t3 = st.tabs(["Invoices", "Marketplace and channel sales", "Customers"])
    with t1:
        _tab_facturas(d, cfg, coa)
    with t2:
        _tab_ventas(d, cfg, coa)
    with t3:
        if not comun.solo_lectura():
            comun.catalogo("Clientes", [
                ("nombre", "Name", "text"), ("email", "Email", "text"), ("telefono", "Phone", "text"),
                ("direccion", "Address", "text"), ("ciudad", "City", "text"), ("estado", "State", "text"),
                ("zip", "ZIP", "text"), ("tipo", "Type", "text"), ("exento_impuesto", "Tax exempt (resale)", "sino"),
                ("resale_cert", "Resale certificate number", "text"), ("terminos", "Payment terms (days)", "num"),
                ("notas", "Notes", "text"), ("activo", "Active", "sino")], "cli", d, "customer", "nombre")
        cl = d["Clientes"]
        if len(cl):
            # 'estado' aqui es el estado de EE.UU., no un status: se renombra para la tabla.
            comun.tabla(cl.drop(columns=["notas"]).rename(columns={"estado": "estado_us"}), enteros=["terminos"])
