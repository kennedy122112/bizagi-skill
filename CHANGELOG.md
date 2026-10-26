# Changelog

## 0.5.0 — 2026-10-26

### Nuevo
- **`docx --template`**: cualquier `.docx` o `.dotx` sirve de plantilla, sin depender de un formato institucional en particular.
  - Se conservan la carátula, los logos, los encabezados y pies, los márgenes y los estilos.
  - `{{CONTENIDO}}` marca dónde va el proceso; sin él, el proceso se agrega al final.
  - `{{nombre}}`, `{{codigo}}`, `{{version}}`, `{{fecha}}`, `{{responsable}}`, `{{area}}`, `{{elaborado}}`, `{{revisado}}`, `{{aprobado}}` y cualquier clave de `meta` se rellenan, también en encabezados y pies, aunque Word haya partido el marcador en varios fragmentos.
  - Los títulos usan los estilos de la plantilla, buscados por su nombre interno, así que funciona aunque Word esté en otro idioma (en español el identificador es `Ttulo1`). Si la plantilla numera sus títulos, no se numeran de nuevo.
  - Las tablas toman el color del título 1 o del acento del tema.
  - Las secciones copian la configuración de página de la plantilla y solo cambian la orientación (horizontal o A3) para el diagrama y las tablas anchas.
- `plantillas/plantilla-ejemplo.docx`: plantilla neutra con carátula, control de versiones, aprobaciones y encabezado y pie con marcadores.

### Correcciones
- Las imágenes declaran sus espacios de nombres de dibujo, necesarios al insertarlas en documentos creados por Word.

## 0.4.1 — 2026-10-26

- Instalador de una línea para Windows (`install.ps1`) y para macOS, Linux y Git Bash (`install.sh`).
- Deja un solo clon en `~/.agents/skills/bizagi` para Codex, OpenCode, Gemini y Cursor, y un enlace para Claude Code. Volver a ejecutarlo actualiza; también permite desinstalar.
- Si había una copia anterior, la respalda en la carpeta temporal en lugar de borrarla.

## 0.4.0 — 2026-10-26

Versión surgida de probar el skill con 5 procesos descritos como habla o escribe la gente: un audio transcrito, un correo, notas de reunión, un dictado con correcciones y un pedido de una línea. Cada caso lo modeló un agente independiente y se hizo una segunda ronda de verificación. Ver `tests/`.

### Diagrama
- Enrutador de líneas que evita atravesar elementos y montarse sobre otras líneas: usa pasillos entre columnas, rodeos en U para un paso opcional y entradas por arriba o abajo de las compuertas.
- Las etiquetas prueban varias posiciones y usan la primera que no pisa nodos, líneas ni otras etiquetas. Las de las compuertas van junto a su salida.
- Las anotaciones crecen según su texto. Los nombres de documentos no pisan su ícono, y el texto de una tarea con eventos adjuntos sube para que el evento no lo tape.
- `preview -o vista.png` genera el PNG directamente. `AVISO diagrama` avisa si alguna línea no pudo evitar un elemento.

### Word y Markdown
- El orden de lectura sigue el proceso: por etapa y, dentro de cada etapa, primero los desvíos y luego el camino principal.
- Las compuertas sin nombre se describen como "Decisión", "División en paralelo" o "Unión de caminos". Las uniones no se narran y las paralelas ya no aparecen como decisiones.
- Los plazos se escriben en palabras ("3 días") y se admite `deadline` en texto ("5 días hábiles").
- Hay una tabla de roles con las actividades a cargo de cada uno, y los carriles pueden llevar una descripción con `{"name", "doc"}`.
- La columna *Sistemas* va separada de *Entradas* y *Salidas*.
- `assumptions` y `questions` en la spec generan la sección "Supuestos y puntos por validar".
- La ficha muestra los campos estándar como "Por completar" cuando faltan y ya no incluye la marca de la herramienta.
- Un diagrama grande se imprime en A3: una vista general más páginas de detalle con texto legible.

### SKILL
- Instrucciones para lenguaje coloquial y correcciones, para cuando no se puede preguntar y para los pedidos de una línea.
- Recomendaciones sobre compuertas de unión, tareas del sistema, terceros externos, varios canales de entrada, pasos opcionales y plazos que cubren varias actividades.
- Explica qué controla el layout: el orden de los carriles y el orden de los flujos.

## 0.3.0 — 2026-10-26

### Nuevo
- Comando **`docx`**: documento Word (.docx) generado solo con la biblioteca estándar. Incluye:
  - una ficha con los datos de `meta`, el objetivo y los participantes;
  - el diagrama en una página horizontal, en SVG con un PNG de respaldo cuando hay Chrome o Edge (`--no-png` para omitirlo);
  - tablas de actividades, decisiones, excepciones, documentos y sistemas, interacciones externas y notas;
  - pie con número de página.
- `meta` en la spec: `codigo`, `version`, `responsable`, `area`, `elaborado`, `revisado`, `aprobado`, `fecha`.
- Probado abriendo el documento en Word 365, sin modo de compatibilidad.

### Cambios
- `doc` y `docx` comparten el mismo resumen del proceso.

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
