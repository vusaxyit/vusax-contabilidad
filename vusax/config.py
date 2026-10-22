"""Esquemas de las hojas, plan de cuentas inicial y constantes del negocio."""

from __future__ import annotations

# Cada hoja de Google Sheets es una tabla. Las columnas existentes se conservan;
# las nuevas se agregan al final al arrancar la app (migracion automatica).
SCHEMAS: dict[str, list[str]] = {
    "Config": ["clave", "valor"],
    "Usuarios": ["codigo", "nombre", "salt", "hash", "rol", "iter", "activo"],
    "Cuentas": ["codigo", "nombre", "tipo", "subtipo", "activa"],
    "Productos": ["sku", "nombre", "categoria", "canal", "costo", "precio", "stock", "stock_min", "activo"],
    "Clientes": ["id_cliente", "nombre", "email", "telefono", "direccion", "ciudad", "estado", "zip",
                 "tipo", "exento_impuesto", "resale_cert", "terminos", "notas", "activo"],
    "Proveedores": ["id_proveedor", "nombre", "email", "telefono", "direccion", "terminos",
                    "es_1099", "notas", "activo"],
    "Ingresos": ["id", "fecha", "canal", "id_orden", "sku", "cantidad", "ingreso_bruto", "comisiones",
                 "tarifas", "envio", "impuesto_cobrado", "cuenta_cobro", "anulado"],
    "Gastos": ["id", "fecha", "categoria", "proveedor", "descripcion", "monto", "metodo",
               "cuenta_gasto", "cuenta_pago", "anulado"],
    "Invoices": ["num", "fecha", "id_cliente", "cliente", "estado", "impuesto", "vence", "terminos",
                 "notas", "impuesto_pct", "anulado"],
    "Invoice_Items": ["id", "num", "sku", "descripcion", "cantidad", "precio_unit"],
    "Facturas_Prov": ["id", "num", "fecha", "vence", "id_proveedor", "proveedor", "notas", "anulado"],
    "Bill_Items": ["id", "id_bill", "sku", "descripcion", "cuenta", "cantidad", "costo_unit"],
    "Transacciones": ["id", "fecha", "cuenta", "descripcion", "monto", "contrapartida", "tercero",
                      "aplica_tipo", "aplica_id", "anulado"],
    "Ajustes_Inv": ["id", "fecha", "sku", "cantidad", "motivo", "anulado"],
    "Asientos": ["id", "asiento", "fecha", "cuenta", "debito", "credito", "memo", "anulado"],
    "Conciliaciones": ["id", "cuenta", "ref", "fecha_extracto", "saldo_extracto"],
    "Reglas": ["id", "palabra", "cuenta"],
    "Auditoria": ["fecha_hora", "usuario", "accion", "hoja", "clave", "detalle"],
}

# Columna que identifica cada registro (para editar, anular y auditar).
CLAVES: dict[str, str] = {
    "Config": "clave", "Usuarios": "codigo", "Cuentas": "codigo", "Productos": "sku",
    "Clientes": "id_cliente", "Proveedores": "id_proveedor", "Invoices": "num",
    "Ingresos": "id", "Gastos": "id", "Invoice_Items": "id", "Facturas_Prov": "id",
    "Bill_Items": "id", "Transacciones": "id", "Ajustes_Inv": "id", "Asientos": "id",
    "Conciliaciones": "id", "Reglas": "id",
}

# Hojas cuya clave se genera sola (prefijo del identificador).
PREFIJOS: dict[str, str] = {
    "Ingresos": "ING", "Gastos": "GAS", "Invoice_Items": "ITM", "Facturas_Prov": "BIL",
    "Bill_Items": "BIT", "Transacciones": "TRX", "Ajustes_Inv": "AJU", "Asientos": "ASI",
    "Conciliaciones": "CON", "Reglas": "REG", "Clientes": "CLI", "Proveedores": "PRV",
}

# Hojas con fecha contable: respetan la fecha de cierre del periodo.
CON_FECHA = ["Ingresos", "Gastos", "Invoices", "Facturas_Prov", "Transacciones", "Ajustes_Inv", "Asientos"]

NUMERICAS: dict[str, list[str]] = {
    "Productos": ["costo", "precio", "stock", "stock_min"],
    "Ingresos": ["cantidad", "ingreso_bruto", "comisiones", "tarifas", "envio", "impuesto_cobrado"],
    "Gastos": ["monto"],
    "Invoices": ["impuesto", "impuesto_pct", "terminos"],
    "Invoice_Items": ["cantidad", "precio_unit"],
    "Bill_Items": ["cantidad", "costo_unit"],
    "Transacciones": ["monto"],
    "Ajustes_Inv": ["cantidad"],
    "Asientos": ["debito", "credito"],
    "Clientes": ["terminos"],
    "Proveedores": ["terminos"],
    "Conciliaciones": ["saldo_extracto"],
}

FECHAS: dict[str, list[str]] = {
    "Ingresos": ["fecha"], "Gastos": ["fecha"], "Invoices": ["fecha", "vence"],
    "Facturas_Prov": ["fecha", "vence"], "Transacciones": ["fecha"], "Ajustes_Inv": ["fecha"],
    "Asientos": ["fecha"], "Conciliaciones": ["fecha_extracto"],
}

# ───────────────────────────── Plan de cuentas ─────────────────────────────
# (codigo, nombre, tipo, subtipo). El usuario puede agregar cuentas desde la app.
# Los nombres siguen la nomenclatura de QuickBooks Online, que es la que espera un CPA.
TIPO_ACTIVO = "Asset"
TIPO_PASIVO = "Liability"
TIPO_CAPITAL = "Equity"
TIPO_INGRESO = "Income"
TIPO_COSTO = "Cost"
TIPO_GASTO = "Expense"

SUB_BANCO = "Bank"

PLAN_CUENTAS: list[tuple[str, str, str, str]] = [
    ("1010", "Bank of America (Operating)", TIPO_ACTIVO, SUB_BANCO),
    ("1020", "Chase (Operating)", TIPO_ACTIVO, SUB_BANCO),
    ("1050", "Amazon Pending Settlement", TIPO_ACTIVO, "Pending Settlement"),
    ("1060", "eBay Pending Settlement", TIPO_ACTIVO, "Pending Settlement"),
    ("1070", "Website Payment Processor Pending", TIPO_ACTIVO, "Pending Settlement"),
    ("1080", "Other Marketplaces Pending Settlement", TIPO_ACTIVO, "Pending Settlement"),
    ("1100", "Accounts Receivable", TIPO_ACTIVO, "Receivable"),
    ("1200", "Inventory Asset", TIPO_ACTIVO, "Inventory"),
    ("1900", "Uncategorized Asset", TIPO_ACTIVO, "Uncategorized"),
    ("2000", "Accounts Payable", TIPO_PASIVO, "Payable"),
    ("2100", "Business Credit Card", TIPO_PASIVO, "Credit Card"),
    ("2200", "Sales Tax Payable (FL DOR)", TIPO_PASIVO, "Taxes"),
    ("2400", "Other Liabilities", TIPO_PASIVO, "Other Liability"),
    ("3010", "Partner 1 Capital", TIPO_CAPITAL, "Partner Capital"),
    ("3020", "Partner 2 Capital", TIPO_CAPITAL, "Partner Capital"),
    ("3110", "Partner 1 Draws", TIPO_CAPITAL, "Partner Draws"),
    ("3120", "Partner 2 Draws", TIPO_CAPITAL, "Partner Draws"),
    ("3950", "Opening Balance Equity", TIPO_CAPITAL, "Opening"),
    ("4000", "Amazon FBA Sales", TIPO_INGRESO, "Sales"),
    ("4010", "eBay Sales", TIPO_INGRESO, "Sales"),
    ("4020", "Walmart Sales", TIPO_INGRESO, "Sales"),
    ("4030", "Website Sales", TIPO_INGRESO, "Sales"),
    ("4040", "Direct & B2B Sales (WhatsApp, Invoices)", TIPO_INGRESO, "Sales"),
    ("4050", "TikTok Shop Sales", TIPO_INGRESO, "Sales"),
    ("4090", "Other Sales", TIPO_INGRESO, "Sales"),
    ("5000", "Cost of Goods Sold", TIPO_COSTO, "COGS"),
    ("5900", "Inventory Shrinkage & Adjustments", TIPO_COSTO, "COGS"),
    ("6010", "Marketplace Referral Fees", TIPO_GASTO, "Operating"),
    ("6020", "Fulfillment Fees (FBA)", TIPO_GASTO, "Operating"),
    ("6030", "Outbound Shipping", TIPO_GASTO, "Operating"),
    ("6100", "Advertising & Marketing", TIPO_GASTO, "Operating"),
    ("6200", "Software & Subscriptions", TIPO_GASTO, "Operating"),
    ("6300", "Professional Services (Accounting, Legal)", TIPO_GASTO, "Operating"),
    ("6400", "Bank & Processor Fees", TIPO_GASTO, "Operating"),
    ("6500", "Licenses, Registrations & Fees", TIPO_GASTO, "Operating"),
    ("6600", "Insurance", TIPO_GASTO, "Operating"),
    ("6700", "Storage & Rent", TIPO_GASTO, "Operating"),
    ("6800", "Supplies & Packaging", TIPO_GASTO, "Operating"),
    ("6850", "Travel & Meals", TIPO_GASTO, "Operating"),
    ("6900", "Miscellaneous Expense", TIPO_GASTO, "Operating"),
    ("6950", "Interest Paid", TIPO_GASTO, "Other"),
]

# Subtipos que ofrece el editor del plan de cuentas.
SUBTIPOS = ["Bank", "Pending Settlement", "Receivable", "Inventory", "Uncategorized", "Other Asset",
            "Payable", "Credit Card", "Taxes", "Other Liability", "Partner Capital", "Partner Draws",
            "Opening", "Sales", "COGS", "Operating", "Other"]

CUENTA_AR = "1100"
CUENTA_AP = "2000"
CUENTA_INV = "1200"
CUENTA_IMPUESTO = "2200"
CUENTA_COGS = "5000"
CUENTA_MERMA = "5900"
CUENTA_TARJETA = "2100"
CUENTA_VENTAS_B2B = "4040"
CUENTA_APERTURA = "3950"
CUENTA_SUSPENSO = "1900"
CUENTA_GASTO_DEFECTO = "6900"

# canal -> (cuenta de ventas, cuenta donde se cobra). None = banco por defecto.
# Se conservan las claves en español ("sitio web", "directo") para que los registros
# cargados con la version anterior sigan clasificandose igual.
CANAL_CUENTAS: dict[str, tuple[str, str | None]] = {
    "amazon fba": ("4000", "1050"),
    "ebay": ("4010", "1060"),
    "walmart": ("4020", "1080"),
    "website": ("4030", "1070"),
    "sitio web": ("4030", "1070"),
    "whatsapp": ("4040", None),
    "direct": ("4040", None),
    "directo": ("4040", None),
    "tiktok shop": ("4050", "1080"),
}
# Canales donde la plataforma cobra y remite el impuesto de ventas (marketplace facilitator).
CANALES_MARKETPLACE = {"amazon fba", "ebay", "walmart", "tiktok shop"}

# Palabras clave para clasificar gastos que solo traen texto de categoria.
# Se mantienen las palabras en español porque los registros ya cargados las usan,
# y se agregan las inglesas para lo que se capture de ahora en adelante.
PALABRAS_GASTO: list[tuple[str, str]] = [
    (r"publicidad|ads|marketing|anuncio|advertis", "6100"),
    (r"software|suscrip|app|saas|subscription", "6200"),
    (r"contab|legal|abogado|profesional|cpa|accounting|attorney|professional", "6300"),
    (r"banco|bank|fee bancario|stripe|paypal|comision bancaria|processor fee", "6400"),
    (r"licencia|registro|sunbiz|annual report|permiso|cuota|licen|registration|permit", "6500"),
    (r"seguro|insurance", "6600"),
    (r"almacen|storage|alquiler|renta|rent|warehouse", "6700"),
    (r"empaque|suministro|caja|etiqueta|packaging|supplies|label", "6800"),
    (r"viaje|comida|restaurante|gasolina|hotel|travel|meal|fuel", "6850"),
    (r"envio|shipping|flete|ups|fedex|usps|freight|delivery", "6030"),
    (r"referral|comision|commission", "6010"),
    (r"fba|fulfil", "6020"),
    (r"interes|interest", "6950"),
]

CONFIG_DEFECTO: dict[str, str] = {
    "empresa": "VUSAX LLC",
    "direccion_empresa": "Fort Myers, FL",
    "email_empresa": "",
    "tasa_impuesto": "6.5",
    "fecha_cierre": "",
    "inventario_inicio": "2000-01-01",
    "banco_defecto": "1010",
    "socio1": "Yitsenia",
    "socio1_pct": "50",
    "socio2": "Azael Garcia",
    "socio2_pct": "50",
    "canales": "Amazon FBA,eBay,Website,WhatsApp,Walmart,TikTok Shop,Direct",
    "terminos_defecto": "30",
    "prefijo_factura": "INV-",
}

ROLES = ["read", "accountant", "admin"]
# Roles guardados por la version en español. Se traducen al leer la hoja Usuarios.
ROLES_LEGADO = {"lectura": "read", "contador": "accountant", "admin": "admin"}
