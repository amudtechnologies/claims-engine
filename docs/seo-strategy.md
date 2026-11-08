# Estrategia SEO — Amud Technologies

Auditoría, arquitectura, mapa de palabras clave, plan editorial y hoja de ruta
del sitio público (`web/`, https://www.amudtech.com). Fecha: 2026-11-07.

Principio rector: **la página principal posiciona la empresa (dinero,
acreencias y activos identificados a partir de información pública); cada
radar posiciona su producto; Aprenda capta la intención informativa y la
conduce al radar que corresponde.** Ninguna página compite con otra por la
misma intención.

> Sin acceso a Google Search Console, Google Analytics ni a herramientas de
> volumen de búsqueda (Semrush, Ahrefs, Keyword Planner), este documento **no
> contiene cifras de demanda, tráfico ni posiciones**. Donde se habla de
> demanda es una hipótesis cualitativa que hay que validar (§10).

---

## 1. Auditoría del estado actual

Estado medido en producción el 2026-11-07 (HTTP, HTML servido, sitemap y
robots reales).

### 1.1 Hallazgos críticos (contenido)

| # | Hallazgo | Impacto | Esfuerzo | Prioridad |
|---|---|---|---|---|
| C1 | `/nosotros/` está publicada con *Lorem ipsum*. Es la página que buscadores y motores de IA usan para entender quién es la empresa | Alto | Bajo (redactar) | **P0** |
| C2 | `/guias/que-es-un-deposito-judicial/` está publicada con «bla bla bla» como cuerpo y meta description. Es la única guía «real» y apunta a la consulta informativa principal del radar | Alto | Medio | **P0** |
| C3 | Tres artículos «[Placeholder]…» (sembrados por la migración `cms/0003`) están publicados, en el sitemap y enlazados desde `/guias/`. Arrastran además la categoría «Liquidaciones societarias», que solo contiene un placeholder | Alto | Resuelto en código (ver §4) | **P0** |
| C4 | `/politica-de-tratamiento-de-datos-personales/` y `/terminos-y-condiciones/` están publicadas con texto «BORRADOR — contenido pendiente». Para un sitio que cruza números de identificación con dinero, una política de datos vacía es una señal de confianza negativa y un riesgo legal (Ley 1581 de 2012) | Alto | Medio (asesoría jurídica) | **P0** |

Todo lo anterior es contenido gestionado desde el administrador
(`/management/admin/`), no código: salvo C3, no se puede corregir con un
despliegue.

### 1.2 Hallazgos técnicos

| # | Hallazgo | Estado |
|---|---|---|
| T1 | El 404 era la página por defecto de Django, en inglés, sin navegación | **Corregido**: `templates/404.html`, con marca, `noindex`, buscador y enlaces |
| T2 | `/depositos-judiciales/resultado/?nit=…` (página por consulta, con un número de identificación en la URL) no estaba excluida en robots.txt, a diferencia de `/resultados/` | **Corregido**: cada radar declara sus páginas por consulta (`RadarSpec.private_url_names`) y robots.txt las excluye |
| T3 | Las páginas del CMS sin meta description heredaban la descripción global → descripciones duplicadas en todo el sitio | **Corregido**: se usa el inicio del cuerpo de la página |
| T4 | `lang="es"` genérico | **Corregido**: `es-CO` |
| T5 | Schema `Organization` sin `@id`, sin relación con el resto del marcado | **Corregido** (ver §4) |
| T6 | `http://www.amudtech.com/` redirige a `https://www.amudtech.com:443/` (puerto explícito en la URL de destino) y `http://amudtech.com` necesita dos saltos | Pendiente: configuración de nginx/Elastic Beanstalk, fuera del repo |
| T7 | Sin cabecera HSTS | Pendiente (recomendación, no implementado: un HSTS mal configurado es difícil de revertir porque los navegadores lo guardan en caché) |
| T8 | Imagen Open Graph = icono de 180 px con `twitter:card=summary`. Al compartir en WhatsApp o LinkedIn se ve un icono pequeño | Pendiente: diseñar una imagen de 1200×630 |
| T9 | robots.txt bloquea `/resultados/` *y* la página lleva `noindex`. Con el bloqueo, Google no llega a leer el `noindex`; la URL podría indexarse sin contenido si alguien la enlaza | Aceptado a propósito: la prioridad es de privacidad (que no se rastreen números de identificación) |

Sin problemas: HTTPS en producción, redirección apex → www, canonical
autorreferencial, sitemap generado automáticamente que solo incluye contenido
publicado, `noindex` en resultados y borradores, redirecciones 301 automáticas
cuando cambia el slug de una página o artículo, `/radares/` con 301 a
`/#radares`, fuentes autoalojadas con `font-display: swap`, HTML renderizado
en servidor (el JavaScript solo añade animaciones, no contenido), imágenes de
tarjetas con `width`/`height` y `loading="lazy"`.

**Rendimiento / Core Web Vitals:** el HTML de la página principal pesa unos 11
KB y el de la landing de depósitos 27 KB, sin frameworks de JavaScript. No hay
medición de campo (CrUX) disponible sin Search Console/PageSpeed; ver §10.

### 1.3 Hallazgos de arquitectura y on-page

| # | Hallazgo | Estado |
|---|---|---|
| A1 | **Canibalización home ↔ radar.** La meta description de la home hablaba solo de «depósitos judiciales sin reclamar», igual que la landing del radar. La home no comunicaba el concepto de la empresa | **Corregido**: nuevo title/description de empresa; los términos del producto quedan para la landing |
| A2 | **Home con poco contenido**: hero + tarjeta del radar. Un solo H1 y un H2 (el nombre del radar). Nada explicaba qué es Amud, qué busca, cómo trabaja ni en qué se diferencia de una firma jurídica | **Corregido**: tres secciones nuevas (§4) |
| A3 | Sin enlaces del contenido educativo al producto ni del producto al contenido educativo | **Corregido**: bloque «Radar relacionado» en artículos y «Guías relacionadas» en la landing, ambos automáticos por slug de categoría |
| A4 | El footer no enlazaba ninguna landing de radar | **Corregido**: columna «Radares», generada desde el registro de radares |
| A5 | Breadcrumb de la landing («Radar de Acreencias / …») distinto del de la página de detalle («Radares / …») y sin marcado | **Corregido**: «Inicio / Radares / Depósitos judiciales» con `BreadcrumbList` |
| A6 | Title de la landing de depósitos con la palabra clave al final («¿Tiene un depósito judicial sin reclamar? Consulte gratis…») | **Corregido**: «Depósitos judiciales sin reclamar: consulte por NIT o cédula» |
| A7 | La landing de depósitos no tiene buscador: los «Consultar ahora» llevan a `/#buscar`. Quien llega desde Google buscando «consultar depósitos judiciales por cédula» tiene que hacer un clic más para consultar | **No modificado**: el buscador se quitó de la landing a propósito (commit 1291ed3). Ver la recomendación R1 |
| A8 | «Sigue leyendo» (tuteo) en el artículo, contra la regla de usted del sitio | **Corregido**: «Siga leyendo» |
| A9 | Marca usada como «Amud Technologies» y «AmudTech» sin vincular | **Corregido** en el schema (`alternateName`); en el texto visible conviene elegir una forma principal |
| A10 | Los H2 del footer («Amud Technologies», «Información», «Contacto») aparecen en el esquema de encabezados de cada página | Bajo impacto; no se modificó para no tocar el diseño |

---

## 2. Arquitectura SEO propuesta

```
/                                   Empresa: dinero, acreencias y activos identificados
│                                   a partir de información pública (concepto global)
├── /depositos-judiciales/          Radar 1 (producto): consulta, plazos, reclamación
│   └── /resultado/?nit=            Por consulta — noindex, excluida en robots
├── /<radar-futuro>/                Un slug en español por radar, al mismo nivel
├── /resultados/?nit=               Consolidado por consulta — noindex, excluida en robots
├── /guias/                         Aprenda: hub informativo
│   ├── /guias/categoria/<slug>/    Una categoría por radar (mismo slug) + categorías transversales
│   └── /guias/<slug>/              Artículos
├── /nosotros/                      Entidad: quién es, qué hace, qué no es, contacto
├── /metodologia/                   NUEVA (CMS): fuentes, procesamiento, límites de los datos
├── /politica-de-tratamiento-de-datos-personales/
└── /terminos-y-condiciones/
```

Decisiones:

1. **Sin una sección «Servicios» separada por ahora.** Hoy los cuatro niveles
   de servicio (información agregada → registros enriquecidos → investigación
   → gestión) solo existen para un radar y ya están explicados en su landing y
   en la home (§4). Una página `/servicios/` hoy duplicaría la landing del
   radar. Conviene crearla cuando haya dos o más radares activos con servicios
   que se repitan entre ellos.
2. **Sin páginas de «Inteligencia patrimonial» ni de «Identificación de
   activos» como hubs.** Sin un segundo radar no tendrían contenido propio: la
   home ya cumple ese papel. Cuando existan 2–3 radares, la home sigue siendo
   el hub y cada radar es su propia página.
3. **Cada radar nuevo se integra sin rediseño**: al registrar su `RadarSpec`
   aparece en la home (#radares), en el footer, en el sitemap y en robots
   (`private_url_names`); al crear en el CMS una categoría con su mismo slug,
   sus guías aparecen en la landing y cada guía enlaza a la landing. Solo hay
   que escribir la landing.
4. **Categorías de Aprenda**: una por radar (`depositos-judiciales`, y a futuro
   p. ej. `liquidaciones-societarias`) más, como mucho, dos transversales
   cuando tengan ≥3 artículos: «Dinero sin reclamar» (educativo, personas) y
   «Para empresas» (áreas financieras y jurídicas). No crear una categoría hasta
   que tenga tres artículos reales: una categoría vacía o con un solo artículo
   es una página débil en el sitemap.
5. **URLs existentes**: no se cambió ninguna.

---

## 3. Mapa de palabras clave por página

Validación cualitativa (búsquedas del 2026-11-07, sin datos de volumen):

- **«Inteligencia patrimonial» no tiene un uso establecido en Colombia.** Los
  resultados muestran gestión patrimonial familiar y planeación tributaria
  (bancos, firmas de impuestos). Es útil como **categoría de marca** (en la
  home, en Nosotros y para que los motores de IA asocien la expresión a Amud),
  pero no hay que esperar tráfico de esa búsqueda ni convertirla en la
  palabra clave principal de ninguna página: atrae una intención distinta
  (wealth management).
- **«Títulos judiciales»** es el término de uso común en juzgados y trámites
  (el portal del Banco Agrario y los autos de los juzgados hablan de «títulos»).
  Es un sinónimo real que el sitio no usaba; se añadió una pregunta frecuente
  que lo explica en la landing.
- «Identificación / rastreo / búsqueda de activos» en Colombia tiende a
  resultados de investigación patrimonial para cobro de cartera y procesos
  contra deudores, una intención distinta («¿qué bienes tiene mi deudor?»),
  cercana a la investigación de terceros, que el modelo de autoconsulta (D24)
  descarta. **No conviene posicionarse en esos términos** salvo con contenido
  dirigido a empresas que revisan sus *propias* acreencias.

| Página | Intención | Palabra clave principal | Secundarias |
|---|---|---|---|
| `/` | Navegacional + descubrimiento | dinero y acreencias sin reclamar a su nombre | dinero sin reclamar Colombia, acreencias sin cobrar, inteligencia patrimonial (marca), Amud Technologies / AmudTech |
| `/depositos-judiciales/` | Transaccional (consultar) | depósitos judiciales sin reclamar | consultar depósitos judiciales por cédula / por NIT, títulos judiciales, depósitos judiciales susceptibles de prescripción, prescripción de depósitos judiciales |
| `/guias/` | Informativa (hub) | guías sobre acreencias y dinero sin reclamar | qué son las acreencias, derechos económicos |
| `/guias/que-es-un-deposito-judicial/` | Informativa | qué es un depósito judicial | título judicial, Banco Agrario depósitos judiciales |
| `/nosotros/` | Navegacional / confianza | Amud Technologies | qué es AmudTech, quién está detrás |
| `/metodologia/` (nueva) | Confianza / GEO | metodología y fuentes de Amud Technologies | listados de la Rama Judicial, Ley 1743 de 2014, RUES |

Regla anticanibalización: el término «depósitos judiciales» como intención
transaccional solo lo lleva la landing; las guías lo usan con intención
informativa («qué es», «cómo», «cuánto tiempo») y enlazan a la landing.

---

## 4. Mejoras implementadas (código)

| Cambio | Archivos |
|---|---|
| Home: title y description de empresa (antes, del radar) | `web/home/views.py` |
| Home: tres secciones nuevas — «Qué hacemos» (concepto + tipos de oportunidad), «Cómo trabajamos» (los cuatro niveles de servicio), «Nuestro diferencial» (tecnología vs. firma jurídica; hallazgo ≠ derecho comprobado; fuentes oficiales; sin intermediarios obligatorios; independencia del Estado). Textos tomados de la descripción de la empresa y del copy ya existente, en usted. Hero, buscador y tarjetas sin cambios | `web/home/templates/home/index.html`, `web/static/css/home.css` |
| Schema `Organization` con `@id`, `alternateName: AmudTech`, `email` (si está en el perfil), `areaServed` | `web/templates/base.html` |
| Schema `WebSite` en la home (sin `SearchAction`: Google retiró el cuadro de búsqueda de sitelinks y los resultados son `noindex`) | `web/home/templates/home/index.html` |
| Schema `Service` en la landing de depósitos (proveedor por `@id`, Colombia, oferta de consulta gratuita a 0 COP), solo con lo que la página muestra | `web/judicial_deposits/views.py` |
| `BreadcrumbList` + breadcrumb visible unificado en la landing | `web/judicial_deposits/templates/judicial_deposits/index.html` |
| Landing: title con la palabra clave al inicio; FAQ «¿Depósito judicial y título judicial son lo mismo?» | ídem |
| Landing → guías: sección «Guías relacionadas» (artículos publicados de la categoría con el slug del radar; no aparece si no hay ninguno) | `web/cms/templatetags/cms_extras.py`, `web/cms/templates/cms/_related_guides.html` |
| Artículo → radar: bloque «Radar relacionado» cuando el artículo está en la categoría con el slug de un radar activo | `web/cms/views.py`, `web/cms/templates/cms/article_detail.html` |
| Artículo: «Actualizado el …» visible cuando cambió después del día de publicación; `publisher` enlazado por `@id`; «Siga leyendo» | ídem |
| Páginas CMS: meta description de respaldo desde el cuerpo | `web/cms/views.py` |
| `/guias/`: title y description ampliados a acreencias y dinero sin reclamar | `web/cms/views.py` |
| Footer: columna «Radares» desde el registro | `web/templates/base.html`, `web/home/context_processors.py` |
| robots.txt: excluye las páginas por consulta que declare cada radar | `web/home/views.py`, `web/home/radars.py`, `web/judicial_deposits/radar.py` |
| 404 con marca y `noindex` | `web/templates/404.html` |
| Migración `cms/0004`: pasa a borrador (no borra) los artículos `placeholder-*` cuyo cuerpo sigue siendo el de ejemplo | `web/cms/migrations/0004_unpublish_placeholder_articles.py` |
| `lang="es-CO"` | `web/templates/base.html` |

Schema que **no** se añadió, a propósito:
- `FAQPage`: desde 2023 Google solo muestra ese resultado enriquecido para
  sitios gubernamentales y de salud. Las preguntas frecuentes ya están en HTML
  plano y legible, que es lo que leen los motores de IA.
- `LocalBusiness` / dirección / teléfono: el perfil de la empresa tiene «-» en
  NIT, teléfono y dirección. Completarlos en el admin primero (§6).
- `sameAs`: no hay perfiles oficiales en redes. Añadirlo cuando existan.
- `llms.txt`: ningún motor importante ha confirmado que lo use (Google dijo
  públicamente que no). Lo que sí sirve para GEO está en §7.

Verificado: 58 tests en verde (los nuevos cubren robots, schema, enlaces
cruzados, el respaldo de la description y el 404), `ruff check` limpio y el
JSON-LD de cada página se parsea correctamente.

---

## 5. Contenido para redactar ya (borradores para el CMS)

No se publicaron porque son contenido del CMS y necesitan revisión humana
(datos de la empresa, responsables, asesoría jurídica). Los corchetes son
datos que hay que completar; **no inventar los que falten** (quitar la frase
antes que rellenarla).

### 5.1 `/nosotros/` (reemplaza el Lorem ipsum)

- **meta_title**: Nosotros: quiénes somos y qué hacemos
- **meta_description**: Amud Technologies es una empresa colombiana de tecnología que transforma información pública de fuentes oficiales en oportunidades: dinero, acreencias y activos.

> **Quiénes somos**
> Amud Technologies es una empresa privada e independiente de tecnología,
> [constituida en Colombia en AAAA, NIT …]. Transformamos información pública
> en oportunidades reales: procesamos, relacionamos y enriquecemos datos de
> fuentes oficiales para identificar dinero, acreencias y activos que podrían
> pertenecer a personas y empresas, y que muchas veces nadie sabe que existen.
>
> **Qué problema resolvemos**
> En muchos casos el obstáculo para recuperar dinero no es jurídico sino de
> información: el dinero existe, el fundamento legal es claro y su posible
> beneficiario no sabe que está ahí. La información está publicada, pero
> dispersa en documentos de distintos periodos y formatos.
>
> **Qué hacemos**
> Cada fuente que monitoreamos es un *radar*. Hoy está activo el radar de
> depósitos judiciales, construido sobre los listados semestrales de depósitos
> susceptibles de prescripción que publica la Rama Judicial desde 2017.
> Según el radar, ofrecemos información agregada, registros individuales
> enriquecidos, investigación y verificación, y acompañamiento en la gestión.
>
> **Qué no somos**
> No somos una entidad del Estado ni representamos a la Rama Judicial, al
> Banco Agrario ni a ninguna entidad pública. No somos una firma jurídica
> tradicional: nuestro diferencial es la tecnología. Un resultado de búsqueda
> no confirma que el dinero le pertenezca a quien consulta; es un punto de
> partida que debe verificarse. Cualquier persona puede reclamar directamente,
> sin intermediarios.
>
> **Quién está detrás**
> [Nombre, cargo y una línea de experiencia verificable de cada responsable.
> Si se prefiere no publicar nombres, al menos el responsable del tratamiento
> de datos personales.]
>
> **Contacto**
> [Correo · ciudad · NIT]. Enlaces a Metodología y a la Política de datos.

### 5.2 `/metodologia/` (página nueva, `show_in_footer`)

La señal de confianza más fuerte que tiene Amud, y la que mejor citan los
motores de IA, porque es verificable y original. Todo lo que sigue sale de
`docs/project-context.md`; revisar antes de publicar.

- **meta_title**: Metodología: fuentes, procesamiento y límites de los datos
- **meta_description**: De dónde vienen los datos de Amud Technologies, cómo los procesamos y qué pueden y no pueden decir sobre quién es el dueño del dinero.

> **Fuentes**
> Radar de depósitos judiciales: los listados de depósitos judiciales
> susceptibles de prescripción que la Rama Judicial publica semestralmente
> (Ley 1743 de 2014; Acuerdo PCSJA21-11731 de 2021), desde la publicación
> 2017-1 hasta la más reciente. Conservamos cada archivo publicado sin
> modificarlo. Para identificar a las partes consultamos el RUES (Registro
> Único Empresarial y Social).
>
> **Cómo procesamos la información**
> Los archivos cambian de formato, columnas y hojas entre periodos. Los
> unificamos en un mismo modelo, normalizamos valores e identificaciones y
> nunca descartamos un registro en silencio: lo que no puede procesarse queda
> registrado con su motivo. Todo el procesamiento se puede repetir desde los
> archivos originales.
>
> **Lo que los datos no dicen**
> - El listado identifica a las *partes* del proceso (demandante, demandado),
>   no a quién pertenece el dinero. Un depósito puede ser del demandante, del
>   demandado o de un tercero.
> - Desde 2018 los listados no incluyen el número de radicado del proceso ni
>   los nombres de las partes.
> - No podemos confirmar si un depósito se reclamó dentro de los 20 días
>   hábiles siguientes a su publicación.
> - El valor publicado no equivale a dinero disponible para reclamar.
>
> **Actualización**
> [Cada cuánto se incorpora una nueva publicación y fecha de la última.]

### 5.3 Reescribir `/guias/que-es-un-deposito-judicial/`

Es el artículo pilar del radar (ver E1 en §6). Mientras no esté escrito,
pasarlo a borrador: hoy está publicado con «bla bla bla».

---

## 6. Plan editorial (3–6 meses)

Criterio: cada pieza responde una pregunta real, enlaza a una sola página de
destino y, cuando puede, usa datos propios de la infraestructura de Amud
(ventaja que ningún competidor informativo tiene). Una pieza por semana es
suficiente; la calidad pesa más que la frecuencia.

Prioridad: **P1** = meses 1–2, **P2** = meses 2–4, **P3** = meses 4–6.

### A. Guías educativas

| # | Título | KW principal | KW secundarias | Intención | Público | Enlaza a | Prio |
|---|---|---|---|---|---|---|---|
| E1 | Qué es un depósito judicial y por qué podría estar a su nombre | qué es un depósito judicial | título judicial, Banco Agrario, depósito judicial ejemplos | Informativa | Personas y empresas | Landing depósitos | P1 |
| E2 | Prescripción de depósitos judiciales: plazos de 2, 3 y 10 años explicados | prescripción depósitos judiciales | Ley 1743 de 2014, depósitos en condición especial, procesos laborales | Informativa | Personas, abogados | Landing depósitos | P1 |
| E3 | Qué es una acreencia y cómo saber si tiene una a su favor | qué es una acreencia | acreencias sin cobrar, acreencia vs. deuda | Informativa | General | Home | P2 |
| E4 | Dinero sin reclamar en Colombia: qué tipos existen y quién los publica | dinero sin reclamar Colombia | dinero olvidado, cómo saber si tengo dinero a mi nombre | Informativa | Personas | Home (y radares futuros) | P2 |

E4 debe ser una guía honesta y general: incluir también fuentes que Amud
**no** cubre (con enlace a la entidad oficial), e indicar cuál radar cubre cuál.
Verificar cada fuente y su norma antes de publicar; no afirmar lo que no esté
comprobado.

### B. Guías prácticas

| # | Título | KW principal | KW secundarias | Intención | Público | Enlaza a | Prio |
|---|---|---|---|---|---|---|---|
| P1 | Cómo consultar si tiene depósitos judiciales por cédula o NIT | consultar depósitos judiciales por cédula | consulta títulos judiciales, por NIT, listado Rama Judicial | Transaccional-informativa | Personas y empresas | Landing depósitos | P1 |
| P2 | Cómo reclamar un depósito judicial: requisitos y pasos ante el juzgado | cómo reclamar un depósito judicial | solicitud de entrega de títulos, poder, plazo de 20 días hábiles | Informativa-práctica | Personas, abogados | Landing depósitos (servicio de gestión) | P1 |
| P3 | Cómo leer el listado de depósitos susceptibles de prescripción | listado depósitos judiciales prescripción | Rama Judicial, cuenta judicial, despacho | Práctica | Abogados, contadores | Landing depósitos | P2 |
| P4 | Aparezco como demandado en un depósito judicial: ¿el dinero puede ser mío? | depósito judicial a favor del demandado | remanentes, levantamiento de embargo | Informativa | Personas y empresas | Landing depósitos | P2 |

P2 y P4 requieren revisión de abogado (el procedimiento exacto sigue
pendiente de validación según `project-context.md` §2).

### C. Investigaciones con datos propios (la ventaja diferencial)

Usar solo cifras que salgan del pipeline, con fecha de corte y metodología
enlazada. Cifras ya medidas disponibles: 17 publicaciones (2017-1 a 2026-1),
4.574 despachos, ~1,25 millones de números de identificación, 2,8 millones de
depósitos; las personas jurídicas son el 6,6 % de las partes pero cerca del
34 % del valor del lado demandante; menos del 1,5 % de los depósitos
reaparece en la publicación siguiente.

| # | Título | KW principal | Intención | Público | Enlaza a | Prio |
|---|---|---|---|---|---|---|
| D1 | Depósitos judiciales sin reclamar en Colombia: radiografía 2017–2026 | depósitos judiciales sin reclamar cifras | Informativa / prensa | Periodistas, empresas, sector legal | Landing + Metodología | P1 |
| D2 | Por qué casi ningún depósito aparece dos veces: el listado es el último aviso | listado depósitos judiciales prescripción | Informativa | Abogados, empresas | Landing depósitos | P2 |
| D3 | Depósitos judiciales por departamento y especialidad del juzgado | depósitos judiciales por ciudad | Informativa / prensa local | Medios regionales, abogados | Landing | P2 |
| D4 | Empresas en los listados: cuánto valor aparece a nombre de personas jurídicas | depósitos judiciales empresas | Informativa | CFO, áreas jurídicas | Landing | P3 |
| D5 | Informe semestral: lo que trae la nueva publicación (recurrente, cada semestre) | nueva publicación depósitos judiciales [semestre] | Noticiosa | Todos | Landing | P1 (recurrente) |

Las piezas D son también la principal fuente de enlaces entrantes (prensa,
blogs jurídicos) y de citas en motores de IA. Publicar con gráficos y una
tabla descargable. **Nunca** publicar registros individuales ni nombres.

### D. Contenido para empresas

| # | Título | KW principal | KW secundarias | Público | Enlaza a | Prio |
|---|---|---|---|---|---|---|
| B1 | Cómo una empresa puede identificar dinero a su favor en procesos judiciales | depósitos judiciales empresa NIT | acreencias de una empresa, dinero pendiente de cobro | CFO, tesorería, jurídica | Landing depósitos | P2 |
| B2 | Checklist para áreas jurídicas: depósitos de procesos terminados que nadie retiró | depósitos judiciales procesos terminados | cierre de procesos, cartera judicial | Departamentos jurídicos, firmas de cobranza | Landing depósitos | P3 |
| B3 | Liquidaciones societarias: qué pasa con las acreencias de los acreedores | acreencias en liquidación | Supersociedades, insolvencia | Empresas acreedoras | Radar futuro (publicar cuando el radar exista) | P3 |

---

## 7. GEO (motores de respuesta con IA)

Lo que sí mejora la comprensión de Amud por ChatGPT, Gemini o Perplexity, por
orden de efecto esperado:

1. **Una definición estable y repetida de la entidad**: el mismo enunciado
   («empresa privada e independiente de tecnología que transforma información
   pública de fuentes oficiales en oportunidades: dinero, acreencias y
   activos») en la home, Nosotros, el schema `Organization` y el perfil de la
   empresa del footer. Implementado en la home y el schema; falta Nosotros.
2. **Qué no es Amud**, dicho explícitamente (no es el Estado, no es una firma
   jurídica tradicional, no se necesita para reclamar). Implementado en la home
   y la landing.
3. **Metodología y límites de los datos** (§5.2): contenido verificable que
   los motores citan.
4. **Datos originales con fecha** (§6 C): la razón principal por la que un
   motor citaría a Amud y no a una página genérica.
5. **Menciones externas consistentes** (prensa, directorios, LinkedIn de la
   empresa) con el mismo nombre y descripción. Añadirlas a `sameAs` cuando
   existan.

robots.txt no bloquea a los rastreadores de IA (GPTBot, Google-Extended,
PerplexityBot…). Si se quisiera excluir a alguno, es una decisión de negocio,
no técnica.

---

## 8. Confianza y reputación (E-E-A-T)

| Señal | Estado | Acción |
|---|---|---|
| Quién es la empresa | Nosotros vacía | §5.1 (P0) |
| Responsables / autores | Artículos firmados «Equipo Amud Technologies» | Asignar un autor real (usuario con nombre completo) a cada guía; P2/P4 revisadas por abogado, indicarlo en el texto |
| Fuentes oficiales | Landing enlaza a la Rama Judicial | Citar la norma (Ley 1743 de 2014, Acuerdo PCSJA21-11731) con enlace a la fuente en cada guía |
| Fechas de actualización | Implementado en artículos | Indicar la fecha de la última publicación procesada en la landing |
| Metodología | No existe | §5.2 (P1) |
| Hallazgo ≠ derecho comprobado | Presente en la landing; añadido en la home | Mantenerlo en cada guía |
| Independencia del Estado | Presente (footer, landing, home) | — |
| Política de datos / términos | Borradores publicados | Redactar con asesoría jurídica (P0) |
| Datos de la empresa | NIT, teléfono, dirección = «-» | Completar en el admin (Perfil de la empresa) |

---

## 9. Hoja de ruta 30 / 60 / 90 días

**Días 0–30 — Corregir lo que daña**
1. Desplegar este cambio (incluye la migración 0004, que pasa a borrador los placeholders).
2. En el admin: revisar que los tres placeholders quedaron en borrador; pasar a
   borrador «¿Qué es un depósito judicial?» hasta reescribirlo; desactivar la
   categoría «Liquidaciones societarias» hasta que tenga artículos reales.
3. Publicar Nosotros (§5.1) y completar el perfil de la empresa.
4. Política de datos y términos con asesoría jurídica, o pasarlas a borrador
   mientras tanto (salen del footer y del sitemap automáticamente).
5. Search Console: verificar el dominio, enviar el sitemap, pedir la
   eliminación de las URL de los placeholders si llegaron a indexarse.
   Analytics/GA4 (o una alternativa sin cookies) con el evento «consulta
   enviada».
6. nginx: arreglar la redirección `http` → `https` (sin `:443`, un solo salto).

**Días 31–60 — Base de contenido**
1. Publicar Metodología (§5.2).
2. E1, P1, P2 y D1 (las cuatro piezas P1 del plan editorial).
3. Imagen Open Graph de 1200×630 (`twitter:card=summary_large_image`).
4. Decidir R1 (buscador en la landing).

**Días 61–90 — Autoridad**
1. E2, P3, P4, D2, D3.
2. Difundir D1 a prensa económica y jurídica y a facultades de derecho
   (enlaces entrantes).
3. Primera revisión con datos de Search Console: qué consultas traen
   impresiones, CTR por página, ajustar titles y descriptions.
4. Preparar D5 para la siguiente publicación semestral.

---

## 10. Indicadores

Fuente principal: Google Search Console (aún sin configurar) + analítica web
(aún sin configurar). Sin ellas no hay línea base; la primera medición útil
llega unas 4–6 semanas después de verificar el dominio.

| Indicador | Fuente | Segmentación |
|---|---|---|
| Impresiones, clics, CTR, posición media | Search Console | Por página y por grupo: marca / empresa (home) / depósitos (landing + guías) / datos (D) |
| Palabras clave con impresiones (top 3, 4–10, 11–20) | Search Console | Mismo agrupamiento |
| Tráfico orgánico por categoría | Analítica | Por categoría de Aprenda y por radar |
| Consultas gratuitas desde orgánico | Analítica: evento de envío del formulario de búsqueda (`/resultados/`), con fuente/medio | Por página de entrada |
| Clics de resultados al detalle del radar | Analítica | — |
| Solicitudes de servicio (información, investigación, gestión) desde orgánico | CRM o formulario de contacto, cuando exista | Por página de entrada |
| Enlaces entrantes y menciones | Search Console (Enlaces) | Por pieza D |
| Core Web Vitals de campo | Search Console / PageSpeed Insights | Móvil vs. escritorio |

Privacidad: el evento de consulta **no** debe enviar el número consultado a
la analítica. La URL `/resultados/?nit=…` lleva el número en la query, así
que hay que configurar la herramienta para descartar el parámetro `nit`
antes de registrar la página vista.

---

## 11. Pendientes y recomendaciones que requieren decisión o acceso externo

| # | Tema | Por qué no se hizo |
|---|---|---|
| R1 | **Buscador en la landing de depósitos.** Quien llega desde «consultar depósitos judiciales por cédula» necesita un clic más para consultar. Probablemente es la mejora de conversión orgánica más grande | Se quitó a propósito en el commit 1291ed3 (los tests lo documentan). Es una decisión de producto |
| R2 | Contenido del CMS en producción (Nosotros, la guía con «bla bla», política, términos) | Es contenido, no código; requiere datos de la empresa y asesoría jurídica |
| R3 | Redirección `http`→`https` con `:443` y doble salto | Configuración de nginx/EB, fuera del repo |
| R4 | HSTS | Difícil de revertir; activarlo con `SECURE_HSTS_SECONDS` empezando con un valor bajo, una vez confirmado que todo subdominio sirve HTTPS |
| R5 | Imagen Open Graph | Requiere diseño |
| R6 | Volumen de búsqueda de cada palabra clave | Requiere Keyword Planner / Semrush / Ahrefs |
| R7 | Search Console, analítica, CrUX | Requieren acceso a la cuenta de Google y al DNS |
| R8 | Forma principal de la marca en el texto visible («Amud Technologies» vs. «AmudTech») | Decisión de marca |
| R9 | H2 del footer en el esquema de encabezados | Bajo impacto; requiere ajustar estilos |
