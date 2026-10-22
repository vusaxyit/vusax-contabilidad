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
PLAN_CUENTAS: list[tuple[str, str, str, str]] = [
    ("1010", "Bank of America (operaciones)", "Activo", "Banco"),
    ("1020", "Chase (operaciones)", "Activo", "Banco"),
    ("1050", "Amazon por liquidar", "Activo", "Por liquidar"),
    ("1060", "eBay por liquidar", "Activo", "Por liquidar"),
    ("1070", "Procesador de pagos del sitio web por liquidar", "Activo", "Por liquidar"),
    ("1080", "Otros marketplaces por liquidar", "Activo", "Por liquidar"),
    ("1100", "Cuentas por cobrar", "Activo", "Por cobrar"),
    ("1200", "Inventario", "Activo", "Inventario"),
    ("1900", "Movimientos por clasificar", "Activo", "Por clasificar"),
    ("2000", "Cuentas por pagar", "Pasivo", "Por pagar"),
    ("2100", "Tarjeta de crédito del negocio", "Pasivo", "Tarjeta"),
    ("2200", "Impuesto de ventas por pagar (FL DOR)", "Pasivo", "Impuestos"),
    ("2400", "Otros pasivos", "Pasivo", "Otro pasivo"),
    ("3010", "Capital del socio 1", "Capital", "Capital socio"),
    ("3020", "Capital del socio 2", "Capital", "Capital socio"),
    ("3110", "Retiros del socio 1", "Capital", "Retiros socio"),
    ("3120", "Retiros del socio 2", "Capital", "Retiros socio"),
    ("3950", "Saldos iniciales de apertura", "Capital", "Apertura"),
    ("4000", "Ventas Amazon FBA", "Ingreso", "Ventas"),
    ("4010", "Ventas eBay", "Ingreso", "Ventas"),
    ("4020", "Ventas Walmart", "Ingreso", "Ventas"),
    ("4030", "Ventas sitio web", "Ingreso", "Ventas"),
    ("4040", "Ventas directas y B2B (WhatsApp, facturas)", "Ingreso", "Ventas"),
    ("4050", "Ventas TikTok Shop", "Ingreso", "Ventas"),
    ("4090", "Otras ventas", "Ingreso", "Ventas"),
    ("5000", "Costo de bienes vendidos", "Costo", "COGS"),
    ("5900", "Merma y ajustes de inventario", "Costo", "COGS"),
    ("6010", "Comisiones de marketplace (referral)", "Gasto", "Operativo"),
    ("6020", "Tarifas de fulfillment (FBA)", "Gasto", "Operativo"),
    ("6030", "Envíos de ventas", "Gasto", "Operativo"),
    ("6100", "Publicidad y marketing", "Gasto", "Operativo"),
    ("6200", "Software y suscripciones", "Gasto", "Operativo"),
    ("6300", "Servicios profesionales (contabilidad, legal)", "Gasto", "Operativo"),
    ("6400", "Cargos bancarios y de procesadores", "Gasto", "Operativo"),
    ("6500", "Licencias, registros y cuotas", "Gasto", "Operativo"),
    ("6600", "Seguros", "Gasto", "Operativo"),
    ("6700", "Almacenamiento y alquiler", "Gasto", "Operativo"),
    ("6800", "Suministros y empaque", "Gasto", "Operativo"),
    ("6850", "Viajes y comidas", "Gasto", "Operativo"),
    ("6900", "Gastos varios", "Gasto", "Operativo"),
    ("6950", "Intereses pagados", "Gasto", "Otros"),
]

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
CANAL_CUENTAS: dict[str, tuple[str, str | None]] = {
    "amazon fba": ("4000", "1050"),
    "ebay": ("4010", "1060"),
    "walmart": ("4020", "1080"),
    "sitio web": ("4030", "1070"),
    "whatsapp": ("4040", None),
    "directo": ("4040", None),
    "tiktok shop": ("4050", "1080"),
}
# Canales donde la plataforma cobra y remite el impuesto de ventas (marketplace facilitator).
CANALES_MARKETPLACE = {"amazon fba", "ebay", "walmart", "tiktok shop"}

# Palabras clave para clasificar gastos antiguos que solo traen texto de categoria.
PALABRAS_GASTO: list[tuple[str, str]] = [
    (r"publicidad|ads|marketing|anuncio", "6100"),
    (r"software|suscrip|app|saas", "6200"),
    (r"contab|legal|abogado|profesional|cpa", "6300"),
    (r"banco|bank|fee bancario|stripe|paypal|comision bancaria", "6400"),
    (r"licencia|registro|sunbiz|annual report|permiso|cuota", "6500"),
    (r"seguro|insurance", "6600"),
    (r"almacen|storage|alquiler|renta|rent", "6700"),
    (r"empaque|suministro|caja|etiqueta|packaging", "6800"),
    (r"viaje|comida|restaurante|gasolina|hotel", "6850"),
    (r"envio|shipping|flete|ups|fedex|usps", "6030"),
    (r"referral|comision", "6010"),
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
    "canales": "Amazon FBA,eBay,Sitio web,WhatsApp,Walmart,TikTok Shop,Directo",
    "terminos_defecto": "30",
    "prefijo_factura": "INV-",
}

ROLES = ["lectura", "contador", "admin"]
