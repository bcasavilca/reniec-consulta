# ActaSegura Perú — reniec-consulta

Verifica si tu acta de nacimiento, matrimonio o defunción está ubicada en RENIEC. Búsqueda sin DNI, gratis en esta fase.

Origen oficial: `https://apps.reniec.gob.pe/actascertificadas` — endpoint `POST /actascertificadas/actas/consultar_acta.do`, respuesta en `div#msgAlerta` (`Acta ubicada` / `No se ubica`).

## Fase actual: todo gratis

- Búsqueda / verificación: gratis
- Fecha exacta ubicada: visible, sin blur, gratis
- Ayuda con la copia certificada por WhatsApp: gratis, sin Stripe

## Ejecutar en local

```bash
pip install -r requirements.txt
uvicorn app:app --port 8901
# abrir http://127.0.0.1:8901
```

## Cómo usar el sitio

1. Elige el tipo: `01` Nacimiento, `02` Matrimonio, `03` Defunción
2. Completa primer apellido, segundo apellido y prenombres (MAYÚSCULAS, sin tilde: `EXALTACION`)
3. Completa la fecha:
   - `01`: día/mes/año completo, o solo `AAAA-MM` (~30 búsquedas), o solo `AAAA` (365/366 búsquedas)
   - `02`: `AAAA-MM` o solo `AAAA` (12 búsquedas, una por mes)
   - `03`: solo `AAAA`
4. Marca la declaración de la Ley N.º 29733 y pulsa Verificar
5. Deja la página abierta: resultado `UBICADA en <fecha>` o `NO - N fechas revisadas`

Ejemplo que funcionó: `03 / 1981 / MENDOZA / ESTEBAN / GREGORIA = UBICADA`.

## API

```bash
# crear búsqueda (hasta 366 fechas por job)
POST /jobs
{"tipo":"01","paterno":"CASAVILCA","materno":"APONTE","nombres":"EXALTACION","fecha":"1938-09"}

# ver estado (consultar cada 2 s)
GET /jobs/{id}
# => {"status":"working|done|error","result":"revisando 5/30… | UBICADA en 14/09/1938 … | NO - …"}
```

Admin (dueño): `GET /?admin=TOKEN` activa la cookie, luego `GET /stats` y `GET /stats.json`. El token se genera en `admin_token.txt` (no se sube a git).

## Límites y técnica

- Worker con pausa de 2.5 s entre consultas para evitar el `555 SECURITY PAGE`
- Siempre `User-Agent: Mozilla/5.0` + cookies de sesión + `X-Requested-With: XMLHttpRequest` + `Referer`
- Normalización: sin tildes, el orden importa (`SAMUEL ALBERTO` ≠ `ALBERTO SAMUEL`), variantes `CASAVILLA/CAJAVILCA`, `QUIROS/QUIROZ`, `EXALTACION/EXAUTACION`, `APONTE/APOTE`
- Si sale `No se ubica` y el registro es antiguo (ej. Palca/Huando 1938), puede existir solo en libro físico (municipalidad / archivo regional)

## Estructura

- `app.py` — FastAPI + cola SQLite (`jobs.db`) + worker + `/stats`
- `index.html` — frontend único, sin build
- `requirements.txt` — `fastapi, uvicorn, requests`
- `jobs.db`, `admin_token.txt` — locales, fuera de git vía `.gitignore`

## Aviso legal

Uso familiar/genealógico. Actas de terceros vivos solo con consentimiento. Ley de protección de datos personales N.º 29733.
