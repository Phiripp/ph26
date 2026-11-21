# Caudal

**Caudal tells Chile's water authority (Dirección General de Aguas, DGA) which farms to inspect first, using satellite imagery, weather data and the public registry of water rights.**

## The problem

Petorca and the Aconcagua valley have been in drought for over a decade. Some towns depend on water trucks, while nearby orchards keep being irrigated without water rights. The DGA has few inspectors for thousands of farms. Only one in three of its inspections finds an infraction (33% of water-extraction inspections in our two study areas, according to the DGA's public inspection records), and many start from a complaint by a neighbor who had to gather the evidence on their own.

## What Caudal does

1. **Detects irrigation during dry spells.** For every rural property it computes greenness (NDVI) and moisture (NDMI) from Sentinel-2 every 5 days and compares them with the nearby dryland scrub on the same date. If it has not rained for 10 days or more and the property is still much greener and wetter than the dryland around it, that is a sign of irrigation.
2. **Checks it against water rights.** It estimates crop water use with FAO-56, always as a range, and compares it with the rights registered at the DGA for that property and its surroundings.
3. **Ranks properties and plans the route.** It orders properties by suspicion and confidence, and proposes a one-day inspection route for the top ones.
4. **Prepares the visit and the complaint.** It marks where to look inside the property (irrigated patches, possible ponds, canals, wells) and generates a PDF file with the fields of the DGA's official complaint guide: location, map, description of the facts and a technical annex. The complainant's details, the harm they suffered and the signature are left for the person to fill in.

## A real case

In November 2021 the DGA fined an avocado farm in Hijuelas 1,983.9 UTM (about CLP 127 million) for extracting water without rights, and said it had found it with satellite imagery. Caudal sees the dry-season irrigation signal on that property in **all 7 dry seasons analyzed (2019-20 to 2025-26), including the two before the inspection**, with no water rights registered on the property or within 500 m. The example file for this case is in the repository.

## In numbers

- 2 areas in the Valparaíso region: Petorca (Petorca, Cabildo, La Ligua, Papudo and Zapallar) and lower Aconcagua (Hijuelas, La Cruz, Quillota, Nogales and La Calera).
- 7,911 rural properties analyzed with December–March imagery, against 3,642 dryland reference polygons.
- 497 water-extraction inspections for validation, with a clean set of positives and negatives.
- Sentinel-2 series since 2019, corrected and checked pixel by pixel (sea and tile overlap tests); they run on GCP in minutes.

## Principles

- **Caudal ranks, it does not accuse.** It gives signs and ranges and never claims an infraction. A person files the complaint with their national digital ID (Clave Única), and the DGA decides.
- **Everything as a range, with its confidence.** Every estimate says where it comes from, how recent it is and how much cloud cover or uncertainty it has.
- **Public data.** Copernicus Sentinel-2, DGA (water rights, inspections and streams), CIREN (properties, fruit-crop census and canals), CONAF (land use) and Open-Meteo.

## Team

Nicolas Del Valle, Felipe Mellado, Tomás Morales and Gabriela Acuña · Platanus Hack 26 Santiago, Physical World track.
