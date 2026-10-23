"""Descargas: Excel, CSV y factura en PDF."""

from __future__ import annotations

import io
from pathlib import Path

import pandas as pd

# Logo de la empresa. Si el archivo no esta, el PDF sale solo con el nombre en texto.
LOGO = Path(__file__).resolve().parent / "assets" / "logo.png"
LOGO_MM = 25  # ancho del logo en el PDF


def a_excel(hojas: dict[str, pd.DataFrame]) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl", datetime_format="yyyy-mm-dd") as w:
        for nombre, df in hojas.items():
            df = df.copy()
            for c in df.columns:
                if pd.api.types.is_datetime64_any_dtype(df[c]):
                    df[c] = df[c].dt.tz_localize(None) if df[c].dt.tz is not None else df[c]
            hoja = nombre[:31]
            df.to_excel(w, sheet_name=hoja, index=False)
            ws = w.sheets[hoja]
            for i, c in enumerate(df.columns, start=1):
                ancho = max([len(str(c))] + [len(str(x)) for x in df[c].head(200)]) + 2
                ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = min(ancho, 48)
            ws.freeze_panes = "A2"
    return buf.getvalue()


def a_csv(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8-sig")


def _t(s) -> str:
    """Texto seguro para las fuentes base del PDF (latin-1)."""
    return str(s).replace("—", "-").replace("–", "-").encode("latin-1", "replace").decode("latin-1")


def factura_pdf(cfg: dict, enc: dict, cliente: dict, items: pd.DataFrame, pagos: float) -> bytes:
    from fpdf import FPDF

    pdf = FPDF(format="Letter")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # Encabezado: logo a la izquierda y los datos de la empresa al lado.
    y0 = pdf.get_y()
    izq = pdf.l_margin
    con_logo = LOGO.exists()
    if con_logo:
        pdf.image(str(LOGO), x=izq, y=y0, w=LOGO_MM)
        izq = pdf.l_margin + LOGO_MM + 5
    pdf.set_xy(izq, y0)
    pdf.set_font("Helvetica", "B", 20)
    pdf.cell(0, 10, _t(cfg.get("empresa", "VUSAX LLC")), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    for linea in (cfg.get("direccion_empresa", ""), cfg.get("email_empresa", "")):
        if linea:
            pdf.set_x(izq)
            pdf.cell(0, 5, _t(linea), new_x="LMARGIN", new_y="NEXT")
    if con_logo:  # que el texto que sigue nunca quede encima del logo
        pdf.set_y(max(pdf.get_y(), y0 + LOGO_MM))

    pdf.ln(4)
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 8, _t(f"INVOICE {enc['num']}"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 5, _t(f"Date: {enc['fecha']}     Due: {enc['vence']}"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 5, "Bill To:", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    for linea in (cliente.get("nombre", enc.get("cliente", "")), cliente.get("direccion", ""),
                  " ".join(x for x in (cliente.get("ciudad", ""), cliente.get("estado", ""), cliente.get("zip", "")) if x),
                  cliente.get("email", "")):
        if linea:
            pdf.cell(0, 5, _t(linea), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)

    anchos = (22, 88, 20, 30, 30)
    pdf.set_fill_color(235, 235, 235)
    pdf.set_font("Helvetica", "B", 9)
    for t, w in zip(("SKU", "Description", "Qty", "Price", "Amount"), anchos):
        pdf.cell(w, 7, t, border=1, fill=True, align="C")
    pdf.ln()
    pdf.set_font("Helvetica", "", 9)
    sub = 0.0
    for r in items.itertuples():
        imp = round(r.cantidad * r.precio_unit, 2)
        sub += imp
        pdf.cell(anchos[0], 6, _t(r.sku)[:12], border=1)
        pdf.cell(anchos[1], 6, _t(r.descripcion)[:55], border=1)
        pdf.cell(anchos[2], 6, f"{r.cantidad:g}", border=1, align="R")
        pdf.cell(anchos[3], 6, f"${r.precio_unit:,.2f}", border=1, align="R")
        pdf.cell(anchos[4], 6, f"${imp:,.2f}", border=1, align="R")
        pdf.ln()
    imp_total = float(enc.get("impuesto", 0.0))
    total = round(sub + imp_total, 2)
    pdf.ln(2)
    for etiqueta, valor, negrita in (("Subtotal", sub, False), (f"Sales Tax ({enc.get('impuesto_pct', 0):g}%)", imp_total, False),
                                     ("Total", total, True), ("Paid", pagos, False), ("Balance Due", total - pagos, True)):
        pdf.set_font("Helvetica", "B" if negrita else "", 10)
        pdf.cell(sum(anchos[:4]), 6, _t(etiqueta), align="R")
        pdf.cell(anchos[4], 6, f"${valor:,.2f}", align="R")
        pdf.ln()
    if enc.get("notas"):
        pdf.ln(5)
        pdf.set_font("Helvetica", "", 9)
        pdf.multi_cell(0, 5, _t(f"Notes: {enc['notas']}"))
    return bytes(pdf.output())
