# Raster Auto Style — plugin QGIS

*One QML, every raster on its own min/max.*

Adatta uno stile *Singola banda falso colore* al min/max di ogni raster, con una sola QML.

Guida completa: [docs/GUIDA.md](docs/GUIDA.md).

## Installazione

QGIS → Plugin → Gestisci e installa plugin → **Installa da ZIP** → `raster_auto_style.zip`.
Le azioni compaiono nel pulsante con l'icona in barra strumenti (menu a tendina) e in **Raster → Raster Auto Style**. Se il pulsante non si vede: Visualizza → Barre degli strumenti → Raster Auto Style.

## Come funziona

Una QML è dinamica se contiene la custom property `dynamic_minmax=true`. I suoi item sono valori relativi (0 = minimo, 1 = massimo) e il plugin li riscala sul range del raster. Le statistiche vengono lette in quest'ordine:

1. tag `STATISTICS_MINIMUM/MAXIMUM` incorporati nel file (gli stessi letti da GeoServer);
2. sidecar `<file>.tif.aux.xml`;
3. stima su un campione di 250.000 pixel.

Con `dynamic_minmax_mode=percentile` si usa invece un taglio cumulativo (default 2–98%).

La riscalatura avviene da sola quando:

- si apre un TIFF con accanto una QML dinamica con lo stesso nome (es. quella generata da `style_resolver.py`);
- si carica una QML dinamica da Proprietà › Stile;
- si apre un progetto che contiene layer con stile dinamico.

L'automatismo si disattiva dall'ultima voce del menu.

## Azioni

- **Applica template dinamico ai layer selezionati**: carica una QML dinamica su più layer insieme.
- **Importa SLD di GeoServer come stile dinamico**: legge la ColorMap dell'SLD (QGIS da solo non importa SLD per i raster) e permette di ridurre le classi, es. da 50 a 10.
- **Ricalcola stile dinamico**: rilegge le statistiche, utile dopo "Forza statistiche".
- **Forza statistiche**: calcola le statistiche esatte e le salva in `.aux.xml`, senza modificare il TIFF. Non funziona su file remoti (`/vsicurl`) o in cartelle in sola lettura.
- **Esporta stile come template dinamico**: salva lo stile del layer attivo come QML dinamica 0–1 da distribuire.

`template_esempio.qml` è un template viridis a 10 classi.

## Note

- Supporta solo il renderer *Singola banda falso colore*.
- QGIS stesso scrive un `.aux.xml` quando calcola statistiche: per questo i tag incorporati nel file hanno la precedenza sul sidecar.
- Testato in QGIS 3.34 headless; da verificare a mano nell'interfaccia e sulle versioni usate dagli utenti.
