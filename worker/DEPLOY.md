# Desplegar Worker de Contacto

Este Worker recibe los mensajes del formulario "Contacto y sugerencias"
de la app IngePresupuestos y los reenvía a tu Gmail vía Resend.com.

## Paso 1: Crear cuenta en Resend

1. Ve a https://resend.com y regístrate con Google
2. En el dashboard → **Domains** → **Add Domain** → `ingepresupuestos.com`
3. Resend te da 2-3 registros DNS (TXT/CNAME) — agrégalos en Cloudflare DNS
4. Espera ~5 min a que verifique (botón "Verify")
5. Ve a **API Keys** → **Create API Key** → copia el `re_xxxxxxxx`

## Paso 2: Crear el Worker en Cloudflare

1. Cloudflare Dashboard → **Workers & Pages** → **Create**
2. Nombre: `contacto-ingepresupuestos`
3. Pegar el contenido de `contacto.js` en el editor
4. Click **Deploy**

## Paso 3: Variables de entorno

En el Worker → **Settings** → **Variables and Secrets**:

| Variable        | Valor                          |
|----------------|--------------------------------|
| RESEND_API_KEY | `re_xxxxxxxx` (el que copiaste)|
| NOTIFY_EMAIL   | `ing.sumari@gmail.com`         |

Click **Encrypt** en RESEND_API_KEY para protegerla.

## Paso 4: Conectar ruta al dominio

Opción A — **Custom Domain** (recomendada):
- Worker → **Triggers** → **Custom Domains** → agregar `api.ingepresupuestos.com`
- Luego la app envía a `https://api.ingepresupuestos.com/contacto`
- Actualizar `_DEFAULT_FORM_URL` en `views/acerca_view.py`

Opción B — **Route** en el dominio existente:
- Cloudflare Dashboard → `ingepresupuestos.com` → **Workers Routes**
- Agregar ruta: `ingepresupuestos.com/api/*` → worker `contacto-ingepresupuestos`
- La app ya apunta a `https://ingepresupuestos.com/api/contacto` ✓

## Verificar

```bash
curl -X POST https://ingepresupuestos.com/api/contacto \
  -H "Content-Type: application/json" \
  -d '{"Nombre":"Test","Tipo":"Prueba","Mensaje":"Hola desde curl","Fecha":"2026-05-25"}'
```

Deberías recibir el email en tu Gmail en <10 segundos.

## Costos

- Cloudflare Workers: gratis (100K requests/día)
- Resend: gratis (100 emails/mes, 3000 emails/mes primer mes)
- Total: $0/mes
