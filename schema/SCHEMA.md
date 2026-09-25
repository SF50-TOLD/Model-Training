# NOTAM extraction schema

This document explains, field by field, the contract defined in `notam_extraction.schema.json` (JSON Schema 2020-12, `schemaVersion` 1.3.0). The same contract is used in three places:

- the silver labeler's instructions;
- the human review tool;
- the SF50 TOLD app's `@Generable` Swift struct and its Evaluations harness.

## Principles

1. **Record only what the text states.** Never derive a value, and never fill a field from context, convention or common sense. The only exceptions are the unit rules listed under Units. When the text does not state a fact, the field is `null`. `null` is a real label: the evaluation scores it, because that is how it catches invented values.
2. **Normalise the form, not the facts.** Units are recorded as written and never converted. Designators are recorded as written, zero-padded to two digits. Numbers lose their thousands separators and fractions become decimals (`1,500` → `1500`, `1/8IN` → `0.125`). Nothing is computed.
3. **The app does the arithmetic.** The app itself derives these values, so the label never records them:
   - shortening (runway length minus TORA/LDA);
   - per-direction effects of a closure given for a runway pair;
   - the app's own contamination categories;
   - the governing RwyCC;
   - obstacle distance from coordinates.
4. **The input is exactly what the model sees:** `Location: <icao_location>`, a blank line, then the NOTAM text as the NOTAM API returns it. A label may use only that input.

## Top level: `NOTAMExtraction`

| Field | Type | Rule |
|---|---|---|
| `isCanceled` | bool | `true` only when the text itself shows a cancellation: `NOTAMC`, `CANCELED`, `CANCELLED`, `CNL`, or "NOTAM CNL". A NOTAM that is cancelled only in metadata the model cannot see is labelled as its text reads. |
| `effects` | [RunwayEffect] | One entry per runway designator that the text states a performance-relevant fact about, following the scope rule below. Empty when nothing qualifies. **Always empty when `isCanceled` is `true`.** |

Every key is always present. Optional values are an explicit `null`, never omitted.

## `RunwayEffect`

| Field | Type | Rule |
|---|---|---|
| `runway` | string? | The designator exactly as the text writes it, normalised to `^\d{2}[LCR]?(/\d{2}[LCR]?)?$`: zero-pad (`9R` → `09R`), and write a pair with a slash (`18C-36C` → `18C/36C`). Use `null` when the effect applies to the aerodrome or to all runways, or when the text names no runway (`RWY` with no number, or an obstacle with no runway reference). Never infer the designator from the airport's layout. |
| `closure` | `none` / `full` / `partial` | What this effect states about closure. `full`: the runway is stated closed (`CLSD`, `CLOSED`, `NOT AVBL`), including closures with exceptions (`CLSD EXC PPR`, `CLSD EXC SKED ACFT`). `partial`: a stated portion is closed (`W 1713FT CLSD`, `CLOSED FIRST 1,500 FT`, `N OF TWY K CLSD`). `none`: the effect states no closure. |
| `closedLength` | Length? | Length of the closed portion, only when `closure` is `partial` and the length is stated. |
| `closedEnd` | string? | Where the closed portion is, as stated, only when `closure` is `partial`. Write it as a compass abbreviation (`NORTH END` → `N`, `W` → `W`) or a runway end (`27L`). Use `null` when the text doesn't say which end (`FIRST 1,500 FT`), or states a position relative to a taxiway (`N OF TWY K`). |
| `thresholdDisplacement` | Length? | The stated displacement of this runway's threshold (`THR DSPLCD`, `DTHR`, `THR DISPLACED BY`). A relocated threshold (`THR RELOCATED 1040FT`) is recorded here too: it shortens the runway, and that shortening is what the app needs. Requires a single-direction `runway`. |
| `declaredDistances` | DeclaredDistances? | Declared distances as stated for this direction. Requires a single-direction `runway`. Use `null` when the text states none, or when no unit can be found for them (see Units). |
| `surfaceCondition` | SurfaceCondition? | A runway condition report: FAA `FICON`, Canadian `RSC`, or an ICAO `SNOWTAM` (GRF runway condition report). |
| `obstacle` | Obstacle? | A physical obstacle (crane, tower, rig, etc.) reported with a height or position. |

An effect must state something: a `closure` other than `none`, or at least one non-null field.

Facts about the same designator go in one effect. A second effect for the same designator is only for facts that can't share one, such as a second obstacle. When a NOTAM states facts about different designators, each designator gets its own effect, keyed by the designator as written. The canonical case is a partial closure given for `09R/27L` with declared distances given for `09R` and `27L`. That's three effects: the pair's effect carries the closure, and each direction's effect carries only its declared distances, with `closure: "none"`. The closure is **not** repeated on the per-direction effects; the app merges effects by runway.

## `Length`, `Depth`, `Distance`

| Type | Fields | Units |
|---|---|---|
| `Length` | `value`: number, `unit` | `ft`, `m` |
| `Depth` | `value`: number, `unit` | `in`, `mm` |
| `Distance` | `value`: number, `unit` | `ft`, `m`, `nm` |

**Units.** Units are recorded as written and never converted. A value's unit comes from the first of these that applies:

1. **The value itself** (`1665M`, `10810FT`), or the header of the table or column it sits in.
2. **A format that defines its unit**: the FAA `OBST` height format and SNOWTAM coverage and depth (see those sections).
3. **Unitless declared distances**: the unit the same NOTAM uses for the runway's length and threshold displacement. That means its runway, available or closed lengths (`AVBL LEN 990M`, `RWY LENGTH TO READ: 3875FT`) and its displacement (`DTHR 210M`, `DISPLACED BY 1500FT`). If those lengths use different units, or the NOTAM states none, the declared distances have no unit.
4. **Unitless heights and elevations in a US NOTAM**: if the NOTAM states no unit for any height, elevation or altitude, they are feet. A US NOTAM is one whose location is a US identifier: ICAO codes beginning `K`, `PA`, `PH`, `PG`, `PW` or `TJ`, or an FAA domestic identifier such as `BZN` or `64S`.

No other convention supplies a unit ("Australian NOTAMs are metric" does not). A value with no unit is recorded as `null`, and the labeler notes it. If no declared distance for a direction has a unit, `declaredDistances` is `null`.

Every value is greater than zero.

## `DeclaredDistances`

`TORA`, `TODA`, `ASDA`, `LDA`: each a `Length?`. Record the distances that are stated and leave the rest `null`; never copy one distance into another. A dash or `NIL` in a declared-distance table is `null`. Parenthesised gradients (`2232(2.37)`) are not recorded.

Declared distances that name no runway belong to the only runway direction the NOTAM names (`THR RWY 27 DISPLACED 200M … DECLARED DISTANCES CHANGED: TORA: 690M.` → runway `27`). If the NOTAM names more than one runway, or names only a pair (`RWY 09/27`), they have no direction, so they aren't recorded and the labeler notes it.

Declared distances given for a runway pair (`RWY12R/30L LDA 320M`) apply to each direction: record one effect per direction, each with the same values.

Distances measured from an intersection (`DIST FROM TWY B: RWY 10 - TORA-2123M`) are for intersection takeoffs, not the runway's declared distances. They aren't recorded.

## `SurfaceCondition`

| Field | Type | Rule |
|---|---|---|
| `rwyCC` | [int 0…6]? | The runway condition codes as reported, in reporting order (`5/5/3` → `[5, 5, 3]`). A single reported code is `[n]`. `null` when no codes are reported. |
| `contaminants` | [Contaminant] | The contaminants reported for the runway surface covered by the report. May be empty (for example, a report of `DRY`). |

**Report formats.** Three formats appear in the corpus:

- **FAA `FICON`** (JO 7930.2): `RWY 31 FICON 6/3/3 10 PCT ICE AND 10 PCT COMPACTED SN, 10 PCT ICE AND …`. When one contaminant list follows the codes, it covers the whole runway (`runwayThird: null`). When the thirds differ, commas separate them, in reporting order (thirds 1, 2, 3).
- **Canadian `RSC`**: `RSC 16 3/2/5 50 PCT 1/8IN WET SNOW, 70 PCT 1/8IN WET SNOW, 40 PCT 1/8IN WET SNOW.` This follows the same rules as FICON. The runway follows `RSC`.
- **ICAO `SNOWTAM`** (GRF): each runway line is `<observed> <runway> <RWYCC> <coverage> <depth> <condition>`, with every field given per third and separated by slashes. For example, `09241032 16 5/5/5 100/100/100 03/03/03 DRY SNOW/DRY SNOW/DRY SNOW`.
  - Each runway line is its own effect.
  - Contaminants are always per third (`runwayThird` 1–3).
  - The SNOWTAM format itself defines coverage as percent and depth as millimetres, so those units count as stated, just as the FAA `OBST` format defines its first height as MSL.
  - A third reported as `DRY` or `NR` has no contaminant. An `NR` coverage or depth is `null`.

Remarks such as `RWYCC DOWNGRADED`, friction coefficients (`CRFI`, `MEASURED FRICTION COEFFICIENTS`), chemical residue and conditions on taxiways and aprons are not recorded.

## `Contaminant`

| Field | Type | Rule |
|---|---|---|
| `type` | enum | See the vocabulary below. |
| `runwayThird` | int 1…3? | When the report lists contaminants per third (FAA FICON separates thirds with commas, in reporting order), this is the third it was reported for. Otherwise `null`. Within one report, either every contaminant has a third or none does. |
| `coveragePercent` | int 0…100? | The stated percentage (`40 PCT`). `PATCHY` and `THIN` are not percentages, so they record `null`. |
| `depth` | Depth? | The stated depth (`1/8IN` → `0.125 in`). For a layered contaminant, this is the depth of the top layer. |

**Not recorded:**

- treatments (`SANDED`, `DEICED LIQUID`, `SWEPT`, `PLOWED`, `TREATED`);
- snowbanks, berms and windrows;
- cleared width (`90FT WID`);
- contaminants reported for the `REMAINDER` outside the cleared width;
- braking action (`BA MEDIUM`);
- Mu values;
- observation times.

**Contaminant vocabulary.** These are the FAA AC 150/5200-30D contaminants, as written in FICON NOTAMs (FAA JO 7930.2), and their ICAO GRF (SNOWTAM) and Canadian RSC equivalents:

| NOTAM text | `type` |
|---|---|
| `WET` | `wet` |
| `WATER`, `STANDING WATER` | `water` |
| `SLUSH` | `slush` |
| `WET SN`, `WET SNOW` | `wetSnow` |
| `DRY SN`, `DRY SNOW` | `drySnow` |
| `COMPACTED SN`, `COMPACTED SNOW` | `compactedSnow` |
| `FROST` | `frost` |
| `ICE` | `ice` |
| `WET ICE` | `wetIce` |
| `SLUSH OVER ICE`, `SLUSH ON TOP OF ICE` | `slushOverIce` |
| `WATER OVER COMPACTED SN`, `WATER ON TOP OF COMPACTED SNOW` | `waterOverCompactedSnow` |
| `DRY SN OVER COMPACTED SN`, `DRY SNOW ON TOP OF COMPACTED SNOW` | `drySnowOverCompactedSnow` |
| `WET SN OVER COMPACTED SN`, `WET SNOW ON TOP OF COMPACTED SNOW` | `wetSnowOverCompactedSnow` |
| `DRY SN OVER ICE`, `DRY SNOW ON TOP OF ICE` | `drySnowOverIce` |
| `WET SN OVER ICE`, `WET SNOW ON TOP OF ICE` | `wetSnowOverIce` |
| `DRY` | no contaminant |
| anything else (for example `DAMP`, `SLIPPERY WET`, `MUD`, `COMPACTED SNOW GRAVEL MIX`) | `other` |

## `Obstacle`

| Field | Type | Rule |
|---|---|---|
| `heightAGL` | Length? | Height above ground: a height stated as `AGL`, or labelled `HEIGHT`/`HGT` without `AMSL`/`MSL`. |
| `heightMSL` | Length? | Elevation above sea level: a height stated as `MSL` or `AMSL`, or labelled `ELEVATION`/`ELEV`. In the FAA `OBST` format `<n>FT (<n>FT AGL)`, the first height is MSL by that format's definition. `UNKNOWN` is `null`. |
| `distance` | Distance? | The stated distance from the reference. |
| `distanceReference` | string? | What the distance is measured from, as stated (`APCH END RWY 03L`, `ARP`, `JFK`, `TORA RWY 18C`). |
| `bearingDegrees` | number? | A numeric bearing, when stated (`270 DEG`). Compass words (`WNW`) are not converted; they record `null`. |
| `latitude`, `longitude` | number? | The stated DMS position converted to decimal degrees (north and east positive, 6 decimal places). Converting the notation counts as normalising the form, not deriving a fact. Always a pair. Q-line coordinates are the NOTAM's area of influence, not the obstacle's position, and are never used. |

The obstacle's `runway` is the runway the text relates it to (`APCH END RWY 03L` → `03L`). Otherwise it is `null`.

## Scope rule

The app is SF50 TOLD, for the Cirrus SF50 Vision Jet: a light, single-engine, fixed-wing jet (6,000 lb maximum takeoff weight, 39 ft wingspan). A NOTAM gets effects only if it changes something the app models:

- runway availability or length (closures);
- the threshold;
- declared distances;
- runway surface condition;
- an obstacle in the aerodrome environment.

Everything else gets `effects: []`.

| NOTAM | Effects |
|---|---|
| Runway lighting, approach lights, PAPI/VASI, REIL, runway edge or centreline lights | `[]` |
| ILS, localizer, glideslope, VOR, DME, GPS or other navaid outages | `[]` |
| Taxiway or apron closures, and taxiway or apron FICONs (`TWY … FICON`, `APRON … FICON`) | `[]` |
| Procedure minima, SID/STAR/IAP changes, circling restrictions | `[]` |
| An obstacle named in an instrument approach procedure (IAP) or minima NOTAM (`IAP … TEMPORARY CRANE 809 MSL 1.36NM NW OF RWY 31`) | not recorded: approach obstacles are not takeoff obstacles; `[]` unless something else qualifies |
| An obstacle named in an obstacle departure procedure (`ODP … TEMPORARY CRANE 4739 FT FROM DER`) | effect with `obstacle`: departure obstacles are takeoff obstacles |
| An obstacle that exists only under a stated condition (`OBST EXISTS ONLY WHEN RAISED`) | not recorded |
| Aerodrome or service hours, ATC, fuel, customs | `[]` |
| Airspace, UAS/drone operations, parachuting, military activity | `[]` |
| Obstacle **lights** unserviceable (`OBST LGT U/S`) | `[]` |
| Runway markings, signs, ungrooved sections, rubber removal, grass cutting | `[]` |
| A runway closed only to a class of aircraft that excludes the SF50 (`CLSD TO ACFT WINGSPAN MORE THAN 118FT`, `CLSD TO ACFT OVER 12500LBS`, `CLSD TO HEL`) | `[]` |
| A runway closed to a class of aircraft that includes the SF50 (`CLSD TO JET TFC`, `CLSD TO FIXED WING ACFT`) | `closure: "full"` |
| A runway closed with exceptions (`CLSD EXC PPR`) | `closure: "full"` |
| Takeoff or landing not available in one direction only (`LDG RWY 16R NOT AVBL`) | not a closure; `[]` unless something else qualifies |
| "Effective operating length", "available length" or "remaining" figures that aren't labelled as declared distances | not recorded |
| A threshold that is no longer displaced, or declared distances "as published" | `[]` |
| A runway FICON, even when it reports only `WET` | effect with `surfaceCondition` |
| A crane or tower with a height or position and no runway reference | effect with `runway: null` and `obstacle` |
| Helipad and water-lane closures and conditions | `[]` |
| An obstacle at a heliport | effect with `obstacle`: which aerodromes matter is for the app to decide |

## Canonical ordering

Gold labels are stored in canonical order, and the evaluation canonicalises model output the same way before scoring. The order the model emits in therefore never affects its score.

**Effects** are sorted by, in order:

1. `runway`, with `null` first and the rest in lexicographic order;
2. `closure` in the order `none`, `full`, `partial`;
3. whether `thresholdDisplacement` is present (absent first);
4. whether `declaredDistances` is present (absent first);
5. whether `surfaceCondition` is present (absent first);
6. whether `obstacle` is present (absent first).

The sort is stable, so remaining ties keep their original order.

**Contaminants** within a `surfaceCondition` are sorted by `runwayThird` (`null` first, then ascending), then by `type` in lexicographic order.

## Worked examples

Each example is a verbatim corpus NOTAM, shown with the model's input and the correct output. All outputs are in canonical order.

### Declared distances

```text
Location: SFO

SFO RWY 28L DECLARED DIST: TORA 10810FT TODA 10810FT ASDA 10981FT
LDA 10275FT.
```

```json
{
  "isCanceled": false,
  "effects": [
    {
      "runway": "28L",
      "closure": "none",
      "closedLength": null,
      "closedEnd": null,
      "thresholdDisplacement": null,
      "declaredDistances": {
        "TORA": {
          "value": 10810,
          "unit": "ft"
        },
        "TODA": {
          "value": 10810,
          "unit": "ft"
        },
        "ASDA": {
          "value": 10981,
          "unit": "ft"
        },
        "LDA": {
          "value": 10275,
          "unit": "ft"
        }
      },
      "surfaceCondition": null,
      "obstacle": null
    }
  ]
}
```

### Some declared distances stated

```text
Location: MPMG

RWY 19 TEMPO REDUCTION DECLARED DIST DUE OBST: 
TORA: 1665M
TODA: 1665M
```

ASDA and LDA are not stated, so they are null. They are not copied from TORA.

```json
{
  "isCanceled": false,
  "effects": [
    {
      "runway": "19",
      "closure": "none",
      "closedLength": null,
      "closedEnd": null,
      "thresholdDisplacement": null,
      "declaredDistances": {
        "TORA": {
          "value": 1665,
          "unit": "m"
        },
        "TODA": {
          "value": 1665,
          "unit": "m"
        },
        "ASDA": null,
        "LDA": null
      },
      "surfaceCondition": null,
      "obstacle": null
    }
  ]
}
```

### Partial closure of a runway pair, with per-direction declared distances

```text
Location: DTW

DTW RWY 09R/27L W 1713FT CLSD. DECLARED DIST: RWY 09R TORA 6787FT
TODA 6787FT 
 ASDA 6787FT LDA 6787FT. RWY 27L TORA 6787FT TODA 6787FT ASDA 6787FT
LDA 6787FT.
```

Three effects. The closure is stated for the pair, so it goes on the pair's effect only. Each direction's effect records only its declared distances and has closure "none"; the partial closure is not repeated.

```json
{
  "isCanceled": false,
  "effects": [
    {
      "runway": "09R",
      "closure": "none",
      "closedLength": null,
      "closedEnd": null,
      "thresholdDisplacement": null,
      "declaredDistances": {
        "TORA": {
          "value": 6787,
          "unit": "ft"
        },
        "TODA": {
          "value": 6787,
          "unit": "ft"
        },
        "ASDA": {
          "value": 6787,
          "unit": "ft"
        },
        "LDA": {
          "value": 6787,
          "unit": "ft"
        }
      },
      "surfaceCondition": null,
      "obstacle": null
    },
    {
      "runway": "09R/27L",
      "closure": "partial",
      "closedLength": {
        "value": 1713,
        "unit": "ft"
      },
      "closedEnd": "W",
      "thresholdDisplacement": null,
      "declaredDistances": null,
      "surfaceCondition": null,
      "obstacle": null
    },
    {
      "runway": "27L",
      "closure": "none",
      "closedLength": null,
      "closedEnd": null,
      "thresholdDisplacement": null,
      "declaredDistances": {
        "TORA": {
          "value": 6787,
          "unit": "ft"
        },
        "TODA": {
          "value": 6787,
          "unit": "ft"
        },
        "ASDA": {
          "value": 6787,
          "unit": "ft"
        },
        "LDA": {
          "value": 6787,
          "unit": "ft"
        }
      },
      "surfaceCondition": null,
      "obstacle": null
    }
  ]
}
```

### Unitless declared distances take the runway-length unit

```text
Location: AYKI

RWY 07 DTHR 210M DUE PAVEMENT RESURFACING WIP. AVBL LEN 990M.
DECLARED DIST:
RWY   TORA   ASDA   TODA   LDA
07    1090   1090   1150   990
25    1090   1090   1090   990
RMK:
1. WORKS AREA DENOTED BY UNSERVICEABILITY CONE MARKERS
3. ACFT TO CIRCLE TO ALLOW MEN AND EQPT TO VACATE
4. ACCESS TO EXISTING APN VIA TWY A AND B.
```

The declared-distance table gives no unit, so it takes the unit this NOTAM uses for runway length and displacement (DTHR 210M, AVBL LEN 990M): metres. The table's columns are TORA, ASDA, TODA, LDA, in that order. AVBL LEN is not itself a declared distance.

```json
{
  "isCanceled": false,
  "effects": [
    {
      "runway": "07",
      "closure": "none",
      "closedLength": null,
      "closedEnd": null,
      "thresholdDisplacement": {
        "value": 210,
        "unit": "m"
      },
      "declaredDistances": {
        "TORA": {
          "value": 1090,
          "unit": "m"
        },
        "TODA": {
          "value": 1150,
          "unit": "m"
        },
        "ASDA": {
          "value": 1090,
          "unit": "m"
        },
        "LDA": {
          "value": 990,
          "unit": "m"
        }
      },
      "surfaceCondition": null,
      "obstacle": null
    },
    {
      "runway": "25",
      "closure": "none",
      "closedLength": null,
      "closedEnd": null,
      "thresholdDisplacement": null,
      "declaredDistances": {
        "TORA": {
          "value": 1090,
          "unit": "m"
        },
        "TODA": {
          "value": 1090,
          "unit": "m"
        },
        "ASDA": {
          "value": 1090,
          "unit": "m"
        },
        "LDA": {
          "value": 990,
          "unit": "m"
        }
      },
      "surfaceCondition": null,
      "obstacle": null
    }
  ]
}
```

### Declared distances that name no runway

```text
Location: EDGQ

THR RWY 27 DISPLACED 200M INWARDS. 
DECLARED DISTANCES CHANGED:
TORA: 690M.
LDA: 690M.
```

The declared distances name no runway, so they belong to RWY 27, the only runway the NOTAM names.

```json
{
  "isCanceled": false,
  "effects": [
    {
      "runway": "27",
      "closure": "none",
      "closedLength": null,
      "closedEnd": null,
      "thresholdDisplacement": {
        "value": 200,
        "unit": "m"
      },
      "declaredDistances": {
        "TORA": {
          "value": 690,
          "unit": "m"
        },
        "TODA": null,
        "ASDA": null,
        "LDA": {
          "value": 690,
          "unit": "m"
        }
      },
      "surfaceCondition": null,
      "obstacle": null
    }
  ]
}
```

### Displaced threshold

```text
Location: NZNR

THR RWY 34 DISPLACED 320M. RWY 16/34 EFFECTIVE OPR LENGTH 1420M.
DISPLACED THR LIGHT OPR
```

"EFFECTIVE OPR LENGTH" is not a declared distance, so it is not recorded.

```json
{
  "isCanceled": false,
  "effects": [
    {
      "runway": "34",
      "closure": "none",
      "closedLength": null,
      "closedEnd": null,
      "thresholdDisplacement": {
        "value": 320,
        "unit": "m"
      },
      "declaredDistances": null,
      "surfaceCondition": null,
      "obstacle": null
    }
  ]
}
```

### Partial closure from one end, end not named

```text
Location: NKX

RWY 24L/6R CLOSED FIRST 1,500 FT FOR CONCRETE DEMO. LAST 6,500 FT OF RWY USED FOR CONSTRUCTION VEHICLES AND HAUL ROUTES.
```

"6R" is zero-padded to "06R" and "1,500" becomes 1500. "FIRST" does not say which end, so closedEnd is null.

```json
{
  "isCanceled": false,
  "effects": [
    {
      "runway": "24L/06R",
      "closure": "partial",
      "closedLength": {
        "value": 1500,
        "unit": "ft"
      },
      "closedEnd": null,
      "thresholdDisplacement": null,
      "declaredDistances": null,
      "surfaceCondition": null,
      "obstacle": null
    }
  ]
}
```

### Full closure

```text
Location: NZCH

RWY 02/20 CLSD DUE WIP
```

```json
{
  "isCanceled": false,
  "effects": [
    {
      "runway": "02/20",
      "closure": "full",
      "closedLength": null,
      "closedEnd": null,
      "thresholdDisplacement": null,
      "declaredDistances": null,
      "surfaceCondition": null,
      "obstacle": null
    }
  ]
}
```

### Closure with exceptions

```text
Location: PAE

PAE RWY 16R/34L CLSD EXC SKED ACFT AND AIR CARRIERS 30MIN PPR
425-610-8411
```

A runway closed with exceptions (EXC …, PPR) is recorded as closed. Whether the exception applies is for the pilot to decide.

```json
{
  "isCanceled": false,
  "effects": [
    {
      "runway": "16R/34L",
      "closure": "full",
      "closedLength": null,
      "closedEnd": null,
      "thresholdDisplacement": null,
      "declaredDistances": null,
      "surfaceCondition": null,
      "obstacle": null
    }
  ]
}
```

### FICON with runway condition codes

```text
Location: JNU

JNU RWY 08 FICON 5/5/5 100 PCT WET DEICED LIQUID OBS AT
2511280227.
```

Treatments such as DEICED LIQUID, SANDED, SWEPT and PLOWED are not recorded.

```json
{
  "isCanceled": false,
  "effects": [
    {
      "runway": "08",
      "closure": "none",
      "closedLength": null,
      "closedEnd": null,
      "thresholdDisplacement": null,
      "declaredDistances": null,
      "surfaceCondition": {
        "rwyCC": [
          5,
          5,
          5
        ],
        "contaminants": [
          {
            "type": "wet",
            "runwayThird": null,
            "coveragePercent": 100,
            "depth": null
          }
        ]
      },
      "obstacle": null
    }
  ]
}
```

### FICON with per-third contaminants

```text
Location: FAR

FAR RWY 31 FICON 6/3/3 10 PCT ICE AND 10 PCT COMPACTED SN, 10 PCT
ICE AND 30 PCT 1/8IN DRY SN OVER COMPACTED SN, 10 PCT ICE AND 20 PCT
COMPACTED SN OBS AT 2511280521.
```

Commas separate the thirds, in reporting order. The depth of a layered contaminant is the depth of its top layer.

```json
{
  "isCanceled": false,
  "effects": [
    {
      "runway": "31",
      "closure": "none",
      "closedLength": null,
      "closedEnd": null,
      "thresholdDisplacement": null,
      "declaredDistances": null,
      "surfaceCondition": {
        "rwyCC": [
          6,
          3,
          3
        ],
        "contaminants": [
          {
            "type": "compactedSnow",
            "runwayThird": 1,
            "coveragePercent": 10,
            "depth": null
          },
          {
            "type": "ice",
            "runwayThird": 1,
            "coveragePercent": 10,
            "depth": null
          },
          {
            "type": "drySnowOverCompactedSnow",
            "runwayThird": 2,
            "coveragePercent": 30,
            "depth": {
              "value": 0.125,
              "unit": "in"
            }
          },
          {
            "type": "ice",
            "runwayThird": 2,
            "coveragePercent": 10,
            "depth": null
          },
          {
            "type": "compactedSnow",
            "runwayThird": 3,
            "coveragePercent": 20,
            "depth": null
          },
          {
            "type": "ice",
            "runwayThird": 3,
            "coveragePercent": 10,
            "depth": null
          }
        ]
      },
      "obstacle": null
    }
  ]
}
```

### FICON with cleared width and remainder

```text
Location: GTF

GTF RWY 03 FICON 5/5/5 40 PCT 1/8IN DRY SN SWEPT 90FT WID
REMAINDER 1/8IN DRY SN OBS AT 2511280533.
```

Only the reported width is recorded. The cleared width (90FT WID) and REMAINDER contaminants are not.

```json
{
  "isCanceled": false,
  "effects": [
    {
      "runway": "03",
      "closure": "none",
      "closedLength": null,
      "closedEnd": null,
      "thresholdDisplacement": null,
      "declaredDistances": null,
      "surfaceCondition": {
        "rwyCC": [
          5,
          5,
          5
        ],
        "contaminants": [
          {
            "type": "drySnow",
            "runwayThird": null,
            "coveragePercent": 40,
            "depth": {
              "value": 0.125,
              "unit": "in"
            }
          }
        ]
      },
      "obstacle": null
    }
  ]
}
```

### FICON without codes

```text
Location: SLK

SLK RWY 23 FICON 10 PCT ICE 130FT WID OBS AT 2511250948.
```

```json
{
  "isCanceled": false,
  "effects": [
    {
      "runway": "23",
      "closure": "none",
      "closedLength": null,
      "closedEnd": null,
      "thresholdDisplacement": null,
      "declaredDistances": null,
      "surfaceCondition": {
        "rwyCC": null,
        "contaminants": [
          {
            "type": "ice",
            "runwayThird": null,
            "coveragePercent": 10,
            "depth": null
          }
        ]
      },
      "obstacle": null
    }
  ]
}
```

### Layered contaminant

```text
Location: BKL

BKL RWY 24L FICON 2/2/2 100 PCT 1/2IN WET SN OVER COMPACTED SN OBS
AT 2511280256.
```

```json
{
  "isCanceled": false,
  "effects": [
    {
      "runway": "24L",
      "closure": "none",
      "closedLength": null,
      "closedEnd": null,
      "thresholdDisplacement": null,
      "declaredDistances": null,
      "surfaceCondition": {
        "rwyCC": [
          2,
          2,
          2
        ],
        "contaminants": [
          {
            "type": "wetSnowOverCompactedSnow",
            "runwayThird": null,
            "coveragePercent": 100,
            "depth": {
              "value": 0.5,
              "unit": "in"
            }
          }
        ]
      },
      "obstacle": null
    }
  ]
}
```

### SNOWTAM (ICAO GRF) with several runways

```text
Location: EFHK

SWEF2270 EFHK 09200214
(SNOWTAM 2270
EFHK
09200214 04L 5/5/5 100/100/100 NR/NR/NR WET/WET/WET
09200025 04R 5/4/3 100/100/100 NR/NR/NR WET/WET/WET
09200200 15 4/5/5 100/100/100 NR/NR/NR WET/WET/WET

REMARK/ RWY 04R SECOND PART RWYCC DOWNGRADED / RWY 04R THIRD PART 
RWYCC DOWNGRADED / RWY 15 FIRST PART RWYCC DOWNGRADED.)
```

Each runway line is one effect, and SNOWTAM contaminants are always per third. Depth is NR, so it is null. The RWYCC DOWNGRADED remarks are not recorded.

```json
{
  "isCanceled": false,
  "effects": [
    {
      "runway": "04L",
      "closure": "none",
      "closedLength": null,
      "closedEnd": null,
      "thresholdDisplacement": null,
      "declaredDistances": null,
      "surfaceCondition": {
        "rwyCC": [
          5,
          5,
          5
        ],
        "contaminants": [
          {
            "type": "wet",
            "runwayThird": 1,
            "coveragePercent": 100,
            "depth": null
          },
          {
            "type": "wet",
            "runwayThird": 2,
            "coveragePercent": 100,
            "depth": null
          },
          {
            "type": "wet",
            "runwayThird": 3,
            "coveragePercent": 100,
            "depth": null
          }
        ]
      },
      "obstacle": null
    },
    {
      "runway": "04R",
      "closure": "none",
      "closedLength": null,
      "closedEnd": null,
      "thresholdDisplacement": null,
      "declaredDistances": null,
      "surfaceCondition": {
        "rwyCC": [
          5,
          4,
          3
        ],
        "contaminants": [
          {
            "type": "wet",
            "runwayThird": 1,
            "coveragePercent": 100,
            "depth": null
          },
          {
            "type": "wet",
            "runwayThird": 2,
            "coveragePercent": 100,
            "depth": null
          },
          {
            "type": "wet",
            "runwayThird": 3,
            "coveragePercent": 100,
            "depth": null
          }
        ]
      },
      "obstacle": null
    },
    {
      "runway": "15",
      "closure": "none",
      "closedLength": null,
      "closedEnd": null,
      "thresholdDisplacement": null,
      "declaredDistances": null,
      "surfaceCondition": {
        "rwyCC": [
          4,
          5,
          5
        ],
        "contaminants": [
          {
            "type": "wet",
            "runwayThird": 1,
            "coveragePercent": 100,
            "depth": null
          },
          {
            "type": "wet",
            "runwayThird": 2,
            "coveragePercent": 100,
            "depth": null
          },
          {
            "type": "wet",
            "runwayThird": 3,
            "coveragePercent": 100,
            "depth": null
          }
        ]
      },
      "obstacle": null
    }
  ]
}
```

### SNOWTAM with depth

```text
Location: BGQQ

SWBG0221 BGQQ 09241032 (SNOWTAM 0221 BGQQ 09241032 16 5/5/5 100/100/100 03/03/03 DRY SNOW/DRY SNOW/DRY SNOW  RWY 16 MEASURED FRICTION COEFFICIENTS 68/69/69 TAP. REMARK/ RWY 16  TAKEOFF SIGNIFICANT CONTAMINANT THIN RWYCC 5/5/5.)
```

The SNOWTAM format defines depth in millimetres. Friction coefficients are not recorded.

```json
{
  "isCanceled": false,
  "effects": [
    {
      "runway": "16",
      "closure": "none",
      "closedLength": null,
      "closedEnd": null,
      "thresholdDisplacement": null,
      "declaredDistances": null,
      "surfaceCondition": {
        "rwyCC": [
          5,
          5,
          5
        ],
        "contaminants": [
          {
            "type": "drySnow",
            "runwayThird": 1,
            "coveragePercent": 100,
            "depth": {
              "value": 3,
              "unit": "mm"
            }
          },
          {
            "type": "drySnow",
            "runwayThird": 2,
            "coveragePercent": 100,
            "depth": {
              "value": 3,
              "unit": "mm"
            }
          },
          {
            "type": "drySnow",
            "runwayThird": 3,
            "coveragePercent": 100,
            "depth": {
              "value": 3,
              "unit": "mm"
            }
          }
        ]
      },
      "obstacle": null
    }
  ]
}
```

### Canadian RSC

```text
Location: CYFB

RSC 16 3/2/5 50 PCT 1/8IN WET SNOW, 70 PCT 1/8IN WET SNOW, 40 PCT 
1/8IN WET SNOW. TOUCHDOWN RWYCC DOWNGRADED, MIDPOINT RWYCC 
DOWNGRADED, CHEMICAL RESIDUE PRESENT. SWEEPING IN PROGRESS. VALID 
NOV 25 1124 - NOV 25 1924.

RSC 34 5/2/3 40 PCT 1/8IN WET SNOW, 70 PCT 1/8IN WET SNOW, 50 PCT 
1/8IN WET SNOW. MIDPOINT RWYCC DOWNGRADED, ROLLOUT RWYCC 
DOWNGRADED, CHEMICAL RESIDUE PRESENT. SWEEPING IN PROGRESS. VALID 
NOV 25 1124 - NOV 25 1924.

ADDN NON-GRF/TALPA INFO:
CRFI 16 -6C .33/.29/.43 OBS AT 2511251124.
CRFI 34 -6C .43/.29/.33 OBS AT 2511251124.

RMK: TWY ALPHA, CHARLIE, DELTA, ECHO, FOXTROT, GOLF, 
202511251111, DRY SNOW, 1/8IN. SLIPPERY CONDITIONS.
RMK: APN APRON I, APRON II, APRON III, APRON IV, APRON V, 
202511251106, ICE. SLIPPERY CONDITIONS.
```

Commas separate the thirds. The CRFI friction values and the taxiway and apron remarks are not recorded.

```json
{
  "isCanceled": false,
  "effects": [
    {
      "runway": "16",
      "closure": "none",
      "closedLength": null,
      "closedEnd": null,
      "thresholdDisplacement": null,
      "declaredDistances": null,
      "surfaceCondition": {
        "rwyCC": [
          3,
          2,
          5
        ],
        "contaminants": [
          {
            "type": "wetSnow",
            "runwayThird": 1,
            "coveragePercent": 50,
            "depth": {
              "value": 0.125,
              "unit": "in"
            }
          },
          {
            "type": "wetSnow",
            "runwayThird": 2,
            "coveragePercent": 70,
            "depth": {
              "value": 0.125,
              "unit": "in"
            }
          },
          {
            "type": "wetSnow",
            "runwayThird": 3,
            "coveragePercent": 40,
            "depth": {
              "value": 0.125,
              "unit": "in"
            }
          }
        ]
      },
      "obstacle": null
    },
    {
      "runway": "34",
      "closure": "none",
      "closedLength": null,
      "closedEnd": null,
      "thresholdDisplacement": null,
      "declaredDistances": null,
      "surfaceCondition": {
        "rwyCC": [
          5,
          2,
          3
        ],
        "contaminants": [
          {
            "type": "wetSnow",
            "runwayThird": 1,
            "coveragePercent": 40,
            "depth": {
              "value": 0.125,
              "unit": "in"
            }
          },
          {
            "type": "wetSnow",
            "runwayThird": 2,
            "coveragePercent": 70,
            "depth": {
              "value": 0.125,
              "unit": "in"
            }
          },
          {
            "type": "wetSnow",
            "runwayThird": 3,
            "coveragePercent": 50,
            "depth": {
              "value": 0.125,
              "unit": "in"
            }
          }
        ]
      },
      "obstacle": null
    }
  ]
}
```

### Obstacle near the aerodrome

```text
Location: JFK

JFK OBST CRANE (ASN 2024-AEA-1604-NRA) 403906N0734931W (2.2NM WNW
JFK) 114FT (100FT AGL) FLAGGED AND LGTD
```

In the FAA OBST format `<n>FT (<n>FT AGL)`, the first height is MSL. "WNW" is not a numeric bearing, so bearingDegrees is null. The position is converted from DMS to decimal degrees.

```json
{
  "isCanceled": false,
  "effects": [
    {
      "runway": null,
      "closure": "none",
      "closedLength": null,
      "closedEnd": null,
      "thresholdDisplacement": null,
      "declaredDistances": null,
      "surfaceCondition": null,
      "obstacle": {
        "heightAGL": {
          "value": 100,
          "unit": "ft"
        },
        "heightMSL": {
          "value": 114,
          "unit": "ft"
        },
        "distance": {
          "value": 2.2,
          "unit": "nm"
        },
        "distanceReference": "JFK",
        "bearingDegrees": null,
        "latitude": 40.651667,
        "longitude": -73.825278
      }
    }
  ]
}
```

### Obstacle referenced to a runway end

```text
Location: NYL

NYL OBST CRANE (ASN UNKNOWN) 323904N1143718W (1NM N APCH END RWY
03L) UNKNOWN (60FT AGL) FLAGGED
```

The MSL height is UNKNOWN, so it is null.

```json
{
  "isCanceled": false,
  "effects": [
    {
      "runway": "03L",
      "closure": "none",
      "closedLength": null,
      "closedEnd": null,
      "thresholdDisplacement": null,
      "declaredDistances": null,
      "surfaceCondition": null,
      "obstacle": {
        "heightAGL": {
          "value": 60,
          "unit": "ft"
        },
        "heightMSL": null,
        "distance": {
          "value": 1,
          "unit": "nm"
        },
        "distanceReference": "APCH END RWY 03L",
        "bearingDegrees": null,
        "latitude": 32.651111,
        "longitude": -114.621667
      }
    }
  ]
}
```

### Obstacle beyond the end of TORA

```text
Location: EHAM

REF AIP NETHERLANDS AD 2.EHAM AOC TYPE A RWY 18C-36C. CRANE 
ERECTED AT PSN 521700.1N0044411.0E, 2000M BEYOND TORA RWY 18C ON 
EXTD RCL, 138FT AMSL, MARKED AND LGTD.
```

```json
{
  "isCanceled": false,
  "effects": [
    {
      "runway": "18C",
      "closure": "none",
      "closedLength": null,
      "closedEnd": null,
      "thresholdDisplacement": null,
      "declaredDistances": null,
      "surfaceCondition": null,
      "obstacle": {
        "heightAGL": null,
        "heightMSL": {
          "value": 138,
          "unit": "ft"
        },
        "distance": {
          "value": 2000,
          "unit": "m"
        },
        "distanceReference": "TORA RWY 18C",
        "bearingDegrees": null,
        "latitude": 52.283361,
        "longitude": 4.736389
      }
    }
  ]
}
```

### Obstacle given as height and elevation

```text
Location: LFST

TOWER CRANE OPR AT 'ENTZHEIM' :
RDL 114/0.62NM ARP LFST 
PSN : 483215N 0073855E
HEIGHT : 92FT
ELEV : 572FT
LIGHTING : NONE
```

HEIGHT is above ground and ELEV is above sea level. RDL 114 is a numeric bearing from the ARP.

```json
{
  "isCanceled": false,
  "effects": [
    {
      "runway": null,
      "closure": "none",
      "closedLength": null,
      "closedEnd": null,
      "thresholdDisplacement": null,
      "declaredDistances": null,
      "surfaceCondition": null,
      "obstacle": {
        "heightAGL": {
          "value": 92,
          "unit": "ft"
        },
        "heightMSL": {
          "value": 572,
          "unit": "ft"
        },
        "distance": {
          "value": 0.62,
          "unit": "nm"
        },
        "distanceReference": "ARP LFST",
        "bearingDegrees": 114,
        "latitude": 48.5375,
        "longitude": 7.648611
      }
    }
  ]
}
```

### Obstacle in approach minima

```text
Location: KLNC

IAP LANCASTER RGNL, LANCASTER, TX.
RNAV (GPS) RWY 31, AMDT 1B...
CIRCLING CAT A/B MDA 1160/HAA 659.
TEMPORARY CRANE, 809 MSL, 1.36NM NW OF RWY 31 (2026-ASW-5819-OE).
2609031115-2712031115EST
```

An obstacle named in an approach-procedure NOTAM is not a takeoff obstacle, so it is not recorded, and the minima change is out of scope.

```json
{
  "isCanceled": false,
  "effects": []
}
```

### Relocated threshold

```text
Location: KTKI

RWY 18 THR RELOCATED 1040FT S DECLARED DIST: TORA 5962FT TODA 5962FT ASDA 6462FT LDA 6462FT
```

A relocated threshold shortens the runway just as a displaced one does, so it is recorded as thresholdDisplacement.

```json
{
  "isCanceled": false,
  "effects": [
    {
      "runway": "18",
      "closure": "none",
      "closedLength": null,
      "closedEnd": null,
      "thresholdDisplacement": {
        "value": 1040,
        "unit": "ft"
      },
      "declaredDistances": {
        "TORA": {
          "value": 5962,
          "unit": "ft"
        },
        "TODA": {
          "value": 5962,
          "unit": "ft"
        },
        "ASDA": {
          "value": 6462,
          "unit": "ft"
        },
        "LDA": {
          "value": 6462,
          "unit": "ft"
        }
      },
      "surfaceCondition": null,
      "obstacle": null
    }
  ]
}
```

### Declared distances for a runway pair

```text
Location: EFRY

RWY12R THR TEMPO DISPLACED 160M INWARDS, RWY12R/30L LDA 320M
```

Declared distances given for a pair apply to each direction.

```json
{
  "isCanceled": false,
  "effects": [
    {
      "runway": "12R",
      "closure": "none",
      "closedLength": null,
      "closedEnd": null,
      "thresholdDisplacement": {
        "value": 160,
        "unit": "m"
      },
      "declaredDistances": {
        "TORA": null,
        "TODA": null,
        "ASDA": null,
        "LDA": {
          "value": 320,
          "unit": "m"
        }
      },
      "surfaceCondition": null,
      "obstacle": null
    },
    {
      "runway": "30L",
      "closure": "none",
      "closedLength": null,
      "closedEnd": null,
      "thresholdDisplacement": null,
      "declaredDistances": {
        "TORA": null,
        "TODA": null,
        "ASDA": null,
        "LDA": {
          "value": 320,
          "unit": "m"
        }
      },
      "surfaceCondition": null,
      "obstacle": null
    }
  ]
}
```

### Intersection takeoff distances

```text
Location: UHMM

AFTER RECONSTRUCTION TWY B AND TWY F PUT INTO OPERATION
FOR ALL ACFT TYPES WO WEIGHT RESTRICTIONS. TWY WIDTH AVBL 22.5M.
TWY 2 RENAMED TO TWY B, MAIN TWY RENAMED TO TWY F.
DIST FROM TWY B:
RWY 10 - TORA-2123M, TODA-2511M, ASDA-2123M,
RWY 28 - TORA-1352M, TODA-1752M, ASDA-1352M.
```

Distances from TWY B are for intersection takeoffs, not declared distances, and nothing else here affects a runway.

```json
{
  "isCanceled": false,
  "effects": []
}
```

### Closed to a class that includes the SF50

```text
Location: LTBG

RWY 18/36 CLSD TO JET TFC.
-DUE TO CONST WORKS AT THR 36

SOUTHERN HOOK BARRIER IS LOCATED 1499FT INNER SIDE OF THR 36. 
FOR CARGO ACFT AND HELICOPTERS, IF LANDING DIRECTION IS 36 TFCS 
SHALL PLAN TO TOUCH DOWN BEYOND THE HOOK BARRIER.
```

The SF50 is a jet, so a closure to jet traffic applies to it.

```json
{
  "isCanceled": false,
  "effects": [
    {
      "runway": "18/36",
      "closure": "full",
      "closedLength": null,
      "closedEnd": null,
      "thresholdDisplacement": null,
      "declaredDistances": null,
      "surfaceCondition": null,
      "obstacle": null
    }
  ]
}
```

### Closed to fixed-wing aircraft

```text
Location: NZNS

GRASS RWY 02/20 CLSD TO FIXED WING ACFT
```

The SF50 is a fixed-wing aircraft, so the closure applies to it.

```json
{
  "isCanceled": false,
  "effects": [
    {
      "runway": "02",
      "closure": "full",
      "closedLength": null,
      "closedEnd": null,
      "thresholdDisplacement": null,
      "declaredDistances": null,
      "surfaceCondition": null,
      "obstacle": null
    },
    {
      "runway": "20",
      "closure": "full",
      "closedLength": null,
      "closedEnd": null,
      "thresholdDisplacement": null,
      "declaredDistances": null,
      "surfaceCondition": null,
      "obstacle": null
    }
  ]
}
```

### Obstacle in a departure procedure

```text
Location: KEMT

ODP SAN GABRIEL VALLEY, EL MONTE, CA.
DIVERSE VECTOR AREA, AMDT 1 ...
RWY 19, REQUIRES MINIMUM CLIMB OF 378 FT PER NM TO 600.
TEMPORARY CRANE 4739 FT FROM DER, 785FT RIGHT OF CENTERLINE, 170FT AGL/440FT MSL (2025-AWP-2367-OE).
ALL OTHER DATA REMAINS AS PUBLISHED. 2606041852-2701141852EST
```

Departure-procedure obstacles are takeoff obstacles, unlike obstacles named in approach procedures. The climb gradient is not recorded.

```json
{
  "isCanceled": false,
  "effects": [
    {
      "runway": "19",
      "closure": "none",
      "closedLength": null,
      "closedEnd": null,
      "thresholdDisplacement": null,
      "declaredDistances": null,
      "surfaceCondition": null,
      "obstacle": {
        "heightAGL": {
          "value": 170,
          "unit": "ft"
        },
        "heightMSL": {
          "value": 440,
          "unit": "ft"
        },
        "distance": {
          "value": 4739,
          "unit": "ft"
        },
        "distanceReference": "DER",
        "bearingDegrees": null,
        "latitude": null,
        "longitude": null
      }
    }
  ]
}
```

### Cancellation

```text
Location: TPA

A3388/25 NOTAMC A3387/25 
Q) KZMA/QMRXX/IV/NBO/A/000/999/2759N08232W005 
A) KTPA
B) 2511260315
E)  TPA RWY 01L/19R CLSD
CANCELED
```

A cancellation has no effects, even though the cancelled text describes a closure.

```json
{
  "isCanceled": true,
  "effects": []
}
```

### Negative: approach lighting

```text
Location: KBUF

RWY 14 PAPI U/S
```

```json
{
  "isCanceled": false,
  "effects": []
}
```

### Negative: taxiway FICON

```text
Location: FAI

FAI TWY U, V, W FICON 5IN DRY SN OVER COMPACTED SN OBS AT
2511241642.
```

```json
{
  "isCanceled": false,
  "effects": []
}
```

### Negative: threshold restored

```text
Location: CYVO

THR 36 IS NO LONGER DISPLACED BY 3000FT DUE PAINTING. 
FIRST 3000FT RWY 36 OPN
```

The text says the threshold is back to normal. 3000FT is the displacement being removed, not a current one.

```json
{
  "isCanceled": false,
  "effects": []
}
```
