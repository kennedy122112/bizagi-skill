# Changelog

## 0.2.0 — 2026-10-26

### Nuevo
- **Eventos adjuntos** (boundary) al borde de una actividad: `timer`, `messageCatch`, `signalCatch`, `conditional` y `errorCatch`, interrumpibles o no (`"interrupting": false`).
- **Artefactos**: `dataObject`, `dataStore` y `annotation`, enlazados con `associations` (entradas y salidas).
- `doc` incluye las columnas *Entradas* y *Salidas*, y una línea de excepción por cada evento adjunto.
- Nuevo ejemplo: `examples/atencion-reclamos.json`.
- `--version`.

### Layout
- Los flujos rectos que atravesarían otro nodo lo rodean por debajo.
- Las etiquetas de eventos, compuertas y flujos se escriben como `BPMNLabel`, y Bizagi las respeta.
- Los eventos adjuntos se ordenan para que sus flujos no se crucen.
- Los pools externos van arriba cuando conversan con los carriles superiores.

### Compatibilidad con Bizagi
- Los datos se escriben como Bizagi los exporta: `dataObject` directo y asociaciones dirigidas. Así se evitan el objeto duplicado y el error de importación del almacén de datos.
- Las expresiones ya no llevan `xsi:type`: Bizagi agrega el suyo y su exportación quedaba con el atributo duplicado.
- El lector tolera ese `xsi:type` duplicado en exportaciones existentes, y lee `dataObject` con o sin referencia.

## 0.1.0

- Versión inicial: `generate`, `read`, `validate`, `preview` y `doc`.
