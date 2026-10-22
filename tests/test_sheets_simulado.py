"""Valida SheetsBackend contra un Google Sheets simulado (rangos A1, lotes, recorte de celdas vacias)."""

import re
from types import SimpleNamespace

import pytest

from vusax import db
from vusax.config import SCHEMAS


def _col(letras: str) -> int:
    n = 0
    for ch in letras:
        n = n * 26 + ord(ch) - 64
    return n


class FakeWS:
    def __init__(self, title, sid, cols, filas=None):
        self.title, self.id, self.col_count, self.g = title, sid, cols, filas or []

    def col_values(self, i):
        out = [(r[i - 1] if len(r) >= i else "") for r in self.g]
        while out and out[-1] == "":
            out.pop()
        return [str(v) for v in out]

    def append_rows(self, values, value_input_option=None, insert_data_option=None, table_range=None):
        assert value_input_option == "RAW"
        self.g.extend([list(v) for v in values])


class FakeSH:
    def __init__(self, hojas):
        self.hojas = hojas
        self.sig = 100
        self.llamadas = 0

    def worksheets(self):
        return list(self.hojas.values())

    def worksheet(self, n):
        return self.hojas[n]

    def batch_update(self, body):
        self.llamadas += 1
        for rq in body["requests"]:
            if "addSheet" in rq:
                p = rq["addSheet"]["properties"]
                self.sig += 1
                self.hojas[p["title"]] = FakeWS(p["title"], self.sig, p["gridProperties"]["columnCount"])
            elif "updateSheetProperties" in rq:
                p = rq["updateSheetProperties"]["properties"]
                ws = next(w for w in self.hojas.values() if w.id == p["sheetId"])
                ws.col_count = p["gridProperties"]["columnCount"]
            elif "deleteDimension" in rq:
                r = rq["deleteDimension"]["range"]
                ws = next(w for w in self.hojas.values() if w.id == r["sheetId"])
                del ws.g[r["startIndex"]:r["endIndex"]]

    def values_batch_get(self, ranges, params=None):
        self.llamadas += 1
        out = []
        for rg in ranges:
            n, _, resto = rg.partition("!")
            g = self.hojas[n].g
            filas = g[:1] if resto == "1:1" else g
            filas = [list(r) for r in filas]
            for r in filas:
                while r and r[-1] == "":
                    r.pop()
            while filas and not filas[-1]:
                filas.pop()
            out.append({"range": rg, **({"values": filas} if filas else {})})
        return {"valueRanges": out}

    def values_batch_update(self, body):
        self.llamadas += 1
        assert body["valueInputOption"] == "RAW"
        for item in body["data"]:
            n, _, a1 = item["range"].partition("!")
            m = re.fullmatch(r"([A-Z]+)(\d+)", a1)
            c0, r0 = _col(m.group(1)), int(m.group(2))
            ws = self.hojas[n]
            for di, fila in enumerate(item["values"]):
                while len(ws.g) < r0 + di:
                    ws.g.append([])
                row = ws.g[r0 + di - 1]
                for dj, v in enumerate(fila):
                    while len(row) < c0 + dj:
                        row.append("")
                    assert c0 + dj <= ws.col_count, f"{n}: escribe fuera de la cuadricula ({c0 + dj} > {ws.col_count})"
                    row[c0 + dj - 1] = v


def _hoja_vieja():
    return FakeSH({
        "Productos": FakeWS("Productos", 1, 10, [["sku", "nombre", "categoria", "canal", "costo", "precio", "stock", "stock_min"],
                                                 ["P1", "Perfume", "Belleza", "Amazon FBA", "10", "25", "30", "5"]]),
        "Ingresos": FakeWS("Ingresos", 2, 10, [["fecha", "canal", "id_orden", "sku", "cantidad", "ingreso_bruto", "comisiones", "tarifas", "envio"],
                                               ["2026-09-03", "Amazon FBA", "A1", "P1", "2", "60", "9", "5", "0"],
                                               ["2026-09-04", "eBay", "E1", "P1", "1", "30", "4", "0", "3"]]),
        "Invoice_Items": FakeWS("Invoice_Items", 3, 10, [["num", "sku", "descripcion", "cantidad", "precio_unit"],
                                                         ["INV-1001", "P1", "Perfume", "3", "25"]]),
    })


@pytest.fixture()
def sheets():
    sh = _hoja_vieja()
    b = db.SheetsBackend.__new__(db.SheetsBackend)
    b.sh, b.enc, b._ws = sh, {}, {}
    return b, sh


def test_migracion_sobre_hoja_vieja(sheets):
    b, sh = sheets
    b.asegurar_esquema(SCHEMAS)
    assert set(SCHEMAS) <= set(sh.hojas)
    # Las columnas viejas conservan su posicion y las nuevas se agregan al final
    assert sh.hojas["Ingresos"].g[0][:9] == ["fecha", "canal", "id_orden", "sku", "cantidad", "ingreso_bruto", "comisiones", "tarifas", "envio"]
    assert sh.hojas["Ingresos"].g[0][9:] == [c for c in SCHEMAS["Ingresos"] if c not in sh.hojas["Ingresos"].g[0][:9]]
    db._migrar(b)
    ing = b.leer_todo(["Ingresos"])["Ingresos"]
    ic = ing[0].index("id")
    assert [r[ic] for r in ing[1:]][0].startswith("ING-")
    assert len(b.leer_todo(["Cuentas"])["Cuentas"]) > 30
    assert sh.hojas["Productos"].g[1][:3] == ["P1", "Perfume", "Belleza"]  # datos intactos
    antes = sh.llamadas
    b.asegurar_esquema(SCHEMAS)  # idempotente: no cambia nada
    assert sh.hojas["Ingresos"].g[0] == b.enc["Ingresos"]


def test_agregar_actualizar_borrar(sheets):
    b, sh = sheets
    b.asegurar_esquema(SCHEMAS)
    db._migrar(b)
    b.agregar("Gastos", [{"id": "GAS-1", "fecha": "2026-10-01", "monto": 10.5, "categoria": "x"},
                         {"id": "GAS-2", "fecha": "2026-10-02", "monto": 20, "categoria": "y"}])
    g = b.leer_todo(["Gastos"])["Gastos"]
    assert g[1][g[0].index("monto")] == 10.5
    assert b.actualizar("Gastos", "id", "GAS-2", {"anulado": "SI", "monto": 25}) == 1
    g = b.leer_todo(["Gastos"])["Gastos"]
    assert g[2][g[0].index("anulado")] == "SI" and g[2][g[0].index("monto")] == 25
    assert b.actualizar("Gastos", "id", "NO-EXISTE", {"anulado": "SI"}) == 0
    b.agregar("Asientos", [{"id": f"ASI-{i}", "asiento": "AJ-1", "fecha": "2026-10-01", "cuenta": "6900"} for i in range(3)])
    assert b.borrar("Asientos", "asiento", "AJ-1") == 3
    assert len(b.leer_todo(["Asientos"])["Asientos"]) == 1  # solo el encabezado


def test_misma_migracion_que_el_respaldo_en_memoria(sheets):
    b, sh = sheets
    m = db.MemoryBackend({n: db._a_df(v) for n, v in b.leer_todo(["Productos", "Ingresos", "Invoice_Items"]).items()})
    for x in (b, m):
        x.asegurar_esquema(SCHEMAS)
    db._migrar(m)
    db._migrar(b)
    for hoja in ("Productos", "Ingresos", "Invoice_Items", "Config"):
        va, vb = b.leer_todo([hoja])[hoja], m.leer_todo([hoja])[hoja]
        assert [r[:len(va[0])] for r in va[:1]] == [r[:len(va[0])] for r in vb[:1]]
        assert len(va) == len(vb)
