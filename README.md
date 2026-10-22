# VUSAX LLC: sistema contable

Contabilidad de partida doble sobre Google Sheets, con interfaz en Streamlit.

## Qué incluye

| Área | Funciones |
|---|---|
| Panel | Ingresos, utilidad, efectivo, por cobrar y por pagar, comparación con el periodo anterior, alertas |
| Ventas | Facturas con varias líneas, impuesto de ventas, clientes exentos por reventa, cobros parciales, PDF, ventas de marketplace con importación CSV |
| Gastos y compras | Gastos por cuenta, facturas de proveedores con pagos parciales, compras que entran al inventario |
| Banco | Movimientos, aportes y retiros de socios, transferencias, importación de extractos CSV con reglas, conciliación |
| Inventario | Costo promedio ponderado, existencias, mínimos, valuación, ajustes de merma |
| Contabilidad | Plan de cuentas editable, asientos manuales, libro mayor, balanza, revisión de datos |
| Reportes | Estado de resultados (con columnas por mes), balance general, flujo de efectivo, antigüedad de cuentas por cobrar y pagar, rentabilidad por canal y producto, impuesto de ventas para el DR-15, capital de socios |
| Ajustes | Empresa, tasa de impuesto, cierre de periodo, socios y porcentajes, usuarios y roles, respaldo en Excel, auditoría |

## Cómo funciona

El libro diario no se guarda: se calcula desde las hojas de documentos (Ingresos, Gastos, Invoices, Facturas_Prov, Transacciones, Ajustes_Inv, Asientos). Por eso no hay asientos huérfanos ni descuadres al corregir un dato. Anular un documento lo saca del libro de inmediato.

Separación entre negocio y finanzas personales: los aportes y retiros de socios van a cuentas de capital y nunca pasan por la utilidad. Un gasto personal se registra con la cuenta "Retiros del socio".

## Antes de publicar esta versión

1. En Google Sheets, usa Archivo > Hacer una copia de la hoja `VUSAX_DB`.
2. Publica la rama en GitHub. Al primer arranque la app migra la base sola:
   - agrega las columnas nuevas al final de cada hoja, sin mover tus datos;
   - asigna un id a cada registro antiguo;
   - crea las hojas nuevas, el plan de cuentas y la configuración;
   - fija la fecha de inicio del inventario en el día del primer arranque, porque el stock de `Productos` es el stock actual.
3. Los secretos no cambian (`gcp_service_account`, `app.sheet_url`, `app.signup_code`).
4. Entra, abre Contabilidad > Revisión de datos y corrige lo que aparezca.
5. Carga los saldos iniciales de bancos y tarjetas con un asiento manual (débito a la cuenta bancaria, crédito a "Saldos iniciales de apertura").

## Roles

- admin: todo, incluidos Ajustes y usuarios.
- contador: registra y consulta.
- lectura: solo consulta. Es el rol de los usuarios nuevos; el primero que se registra queda como admin.

## Seguridad

Contraseñas con PBKDF2 de 600 000 iteraciones (los hashes antiguos se mejoran solos al iniciar sesión), bloqueo tras 5 intentos fallidos, cierre de sesión por inactividad, escritura sin interpretar fórmulas en Sheets y bitácora de cada cambio.

## Límites conocidos

- Google Sheets permite unas 60 lecturas y escrituras por minuto por usuario. Para este volumen alcanza. Si el negocio crece a decenas de miles de movimientos al mes, conviene migrar a Postgres; `vusax/db.py` es el único módulo que habría que reemplazar.
- No hay conexión automática con bancos ni con los reportes de liquidación de Amazon: se importan por CSV.
- No incluye nómina ni presentación de 1099, 1065 o DR-15. El reporte de impuesto de ventas y el de capital de socios son la base de trabajo para tu contador.
- La tasa de impuesto por defecto (6.5 %) es un valor inicial. Confírmala para tu condado.

## Desarrollo

```
pip install -r requirements-dev.txt
pytest                                  # pruebas sin conexión a internet
VUSAX_DEMO=1 streamlit run app.py       # modo demo: usuario demo, contraseña demo-1234
```
