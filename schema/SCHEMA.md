# NOTAM extraction schema

This document explains, field by field, the contract defined in `notam_extraction.schema.json` (JSON Schema 2020-12, `schemaVersion` 2.0.0). The same contract is used in three places:

- the silver labeler's instructions;
- the human review tool;
- the SF50 TOLD app's `@Generable` Swift struct and its Evaluations harness.

The schema records exactly what the app needs to answer three questions about a runway direction: is it closed for takeoff or landing, what stated length or displacement shortens it, and is there an aerodrome obstacle whose height and distance from a runway end are knowable.

## Principles

1. **Record only what the text states.** Never derive a value, and never fill a field from context, convention or common sense. The only exceptions are the unit rules listed under Units. When the text does not state a fact, the field is `null`. `null` is a real label: the evaluation scores it, because that is how it catches invented values.
2. **Normalise the form, not the facts.** Units are recorded as written and never converted. Designators are recorded as written, zero-padded to two digits. Numbers lose their thousands separators and fractions become decimals (`1,500` → `1500`, `1/8IN` → `0.125`). Nothing is computed.
3. **The app does the arithmetic.** The app itself derives these values, so the label never records them:
   - shortening (runway length minus TORA/LDA, or the closed length, or the displacement);
   - the app's own contamination categories and the governing RwyCC;
   - which obstacle lies ahead of which takeoff.
4. **The input is exactly what the model sees:** `Location: <icao_location>`, a blank line, then the NOTAM text as the NOTAM API returns it. A label may use only that input.

## Top level: `NOTAMExtraction`

| Field | Type | Rule |
|---|---|---|
| `isCanceled` | bool | `true` only when the text itself shows a cancellation: `NOTAMC`, `CANCELED`, `CANCELLED`, `CNL`, or "NOTAM CNL". A NOTAM that is cancelled only in metadata the model cannot see is labelled as its text reads. |
| `effects` | [RunwayEffect] | One entry per runway direction that the text states a performance-relevant fact about, following the scope rule below. Empty when nothing qualifies. **Always empty when `isCanceled` is `true`.** |
| `obstacles` | [Obstacle] | One entry per obstacle in the aerodrome environment reported with a height or a position. Empty when none qualifies, and always empty when `isCanceled` is `true`. |

Every key is always present. Optional values are an explicit `null`, never omitted.

## `RunwayEffect`

| Field | Type | Rule |
|---|---|---|
| `runway` | string? | One runway direction, exactly as the text writes it, normalised to `^\d{2}[LCR]?$` (`9R` → `09R`). Use `null` when the effect applies to the aerodrome or to all runways, or when the text names no runway (`RWY` with no number). Never infer the designator from the airport's layout. |
| `closure` | `none` / `takeoff` / `landing` / `both` | Which operations the text states this direction is closed to. See Closures. |
| `partialClosure` | PartialClosure? | A stated closed portion of this direction, with its length and end when stated. `null` when no portion is stated closed. |
| `thresholdDisplacement` | Length? | The stated displacement of this direction's threshold (`THR DSPLCD`, `DTHR`, `THR DISPLACED BY`). A relocated threshold (`THR RELOCATED 1040FT`) is recorded here too: it shortens the runway, and that shortening is what the app needs. When the text gives only a further displacement beyond a published one (`FURTHER DISPLACED BY 180M`), record the total if it is stated (`TOTAL DISPLACEMENT 589FT`), otherwise `null`. |
| `declaredDistances` | DeclaredDistances? | TORA and LDA as stated for this direction. `null` when the text states neither, or when no unit can be found for them (see Units). |
| `surfaceCondition` | SurfaceCondition? | A runway condition report: FAA `FICON`, Canadian `RSC`, or an ICAO `SNOWTAM` (GRF runway condition report). |

An effect must state something: a `closure` other than `none`, or at least one non-null field. **One effect per direction:** every fact the text states about `09R` goes in the `09R` effect.

**A pair expands.** A fact stated for a runway pair (`RWY 09/27 CLSD`, `RSC 04/22 …`) is a fact about each direction, so it is recorded on an effect for `09` and an effect for `27`, each carrying the same stated values. Nothing is recorded for the pair itself.

### Closures

| Text | `closure` |
|---|---|
| `CLSD`, `CLOSED`, `NOT AVBL`, `CLSD FOR TKOF AND LDG`, `CLSD FOR ARR/DEP`, `CLSD TO LDG/TKOF TFC` | `both` |
| `CLSD FOR LDG`, `CLSD LDG`, `LDG RWY 16R NOT AVBL`, `NOT AVBL FOR LDG`, `LDG NOT AUTH` | `landing` |
| `CLSD FOR TKOF`, `DEP RWY 07 NOT AVBL`, `TKOF NOT AUTH` | `takeoff` |
| Available for one operation only: `AVBL FOR TKOF ONLY`, `LIMITED TO ARR ONLY` | closed for the other operation (`landing`, `takeoff`) |
| Closed with exceptions that do not include the SF50: `CLSD EXC PPR`, `CLSD EXC SKED ACFT`, `CLSD TO JET TFC`, `CLSD TO FIXED WING ACFT` | as the closure reads (`both`, `landing`, `takeoff`) |
| Closed to a class that excludes the SF50, or with an exception that includes it: `CLSD TO ACFT OVER 12500LBS`, `CLSD TO HEL`, `CLSD EXC ACFT WINGSPAN LESS THAN 79FT` | `none` |
| Closed only at stated times within the NOTAM's validity: `CLSD DLY 2200-0600`, `CLSD AFTER LAST SKED FLT`, `CLSD MON-FRI 0800-1600` | `none` |
| A restriction, not a closure: `IFR DEP RWY 07 NOT AUTH`, `FIRST 3010FT NOT AVBL TO CIVILIAN ACFT` | `none` |

A direction closed for an operation states no distance for it: `TORA` is `null` when the direction is closed for takeoff, `LDA` is `null` when it is closed for landing, and a direction closed for `both` records no `partialClosure`, `thresholdDisplacement` or `declaredDistances` at all, even when the text also shortens it (`RWY 10/28 FIRST 300M CLSD … RWY 10/28 AVBL FOR HEL ONLY`).

## `PartialClosure`

| Field | Type | Rule |
|---|---|---|
| `length` | Length? | Length of the closed portion, when stated (`W 1713FT CLSD`, `CLOSED FIRST 1,500 FT`). |
| `end` | string? | Where the closed portion is, as stated. Write it as one of: a 16-point compass abbreviation (`NORTH END` → `N`, `W` → `W`); a runway end (`27L`); or, for a portion counted from one end of the effect's direction, `thresholdEnd` (`FIRST`/`FST 1500FT RWY 34`) or `departureEnd` (`LAST 90M RWY 10`). Use `null` when the text doesn't say where: FIRST or LAST given against a pair (`RWY 24L/6R CLOSED FIRST 1,500 FT`), or a position relative to a taxiway (`N OF TWY K`). |

A portion stated closed with neither a length nor an end (`RWY 08L/26R CLSD BTN FOXTROT ROMEO AND TANGO`) is `{"length": null, "end": null}`: it still says a portion is closed. When a NOTAM closes portions at both ends of different directions, each direction gets its own `partialClosure`.

## `Length`, `Depth`, `Distance`, `Height`

| Type | Fields | Units |
|---|---|---|
| `Length` | `value`: number, `unit` | `ft`, `m` |
| `Depth` | `value`: number, `unit` | `in`, `mm` |
| `Distance` | `value`: number, `unit` | `ft`, `m`, `nm` |
| `Height` | `value`: number, `unit`, `datum` | `ft`, `m`; datum `AGL` or `MSL` |

**Units.** Units are recorded as written and never converted. A value's unit comes from the first of these that applies:

1. **The value itself** (`1665M`, `10810FT`), or the header of the table or column it sits in.
2. **A format that defines its unit**: the FAA `OBST` height format and SNOWTAM coverage and depth (see those sections).
3. **Unitless declared distances**: the unit the same NOTAM uses for the runway's length and threshold displacement. That means its runway, available or closed lengths (`AVBL LEN 990M`, `RWY LENGTH TO READ: 3875FT`) and its displacement (`DTHR 210M`, `DISPLACED BY 1500FT`). If those lengths use different units, or the NOTAM states none, the declared distances have no unit.
4. **Unitless heights and elevations in a US NOTAM**: if the NOTAM states no unit for any height, elevation or altitude, they are feet. A US NOTAM is one whose location is a US identifier: ICAO codes beginning `K`, `PA`, `PH`, `PG`, `PW` or `TJ`, or an FAA domestic identifier such as `BZN` or `64S`.

No other convention supplies a unit ("Australian NOTAMs are metric" does not). A value with no unit is recorded as `null`, and the labeler notes it. If neither declared distance for a direction has a unit, `declaredDistances` is `null`.

Every value is greater than zero.

## `DeclaredDistances`

`TORA` and `LDA`: each a `Length?`. Record the distances that are stated and leave the other `null`; never copy one distance into another. TODA and ASDA are not recorded. A dash or `NIL` in a declared-distance table is `null`. Parenthesised gradients (`2232(2.37)`) are not recorded.

Declared distances that name no runway belong to the only runway direction the NOTAM names (`THR RWY 27 DISPLACED 200M … DECLARED DISTANCES CHANGED: TORA: 690M.` → runway `27`). If the NOTAM names more than one runway, or names only a pair (`RWY 09/27`), they have no direction, so they aren't recorded and the labeler notes it.

Declared distances given for a runway pair (`RWY12R/30L LDA 320M`) apply to each direction: each direction's effect records the same values.

Figures that aren't labelled as declared distances are not declared distances: "available length", "effective operating length" and "remaining" figures (`AVBL LEN 1200M`, `EFFECTIVE OPR LENGTH 1420M`) are not recorded, though they do supply a unit (Units rule 3). Distances measured from an intersection (`DIST FROM TWY B: RWY 10 - TORA-2123M`) are for intersection takeoffs, not the runway's declared distances. They aren't recorded.

## `SurfaceCondition`

| Field | Type | Rule |
|---|---|---|
| `rwyCC` | [int 0…6]? | The runway condition codes as reported, in reporting order (`5/5/3` → `[5, 5, 3]`). A single reported code is `[n]`. `null` when no codes are reported. |
| `contaminants` | [Contaminant] | The distinct contaminants reported for the runway surface covered by the report. May be empty (for example, a report of `DRY`). |

**Report formats.** Three formats appear in the corpus:

- **FAA `FICON`** (JO 7930.2): `RWY 31 FICON 6/3/3 10 PCT ICE AND 10 PCT COMPACTED SN, 10 PCT ICE AND …`. Commas separate the thirds, in reporting order; every contaminant of every third is recorded, and a contaminant reported identically for several thirds is recorded once.
- **Canadian `RSC`**: `RSC 16 3/2/5 50 PCT 1/8IN WET SNOW, 70 PCT 1/8IN WET SNOW, 40 PCT 1/8IN WET SNOW.` This follows the same rules as FICON. The runway follows `RSC`; a pair (`RSC 04/22`) gives an effect per direction.
- **ICAO `SNOWTAM`** (GRF): each runway line is `<observed> <runway> <RWYCC> <coverage> <depth> <condition>`, with every field given per third and separated by slashes. For example, `09241032 16 5/5/5 100/100/100 03/03/03 DRY SNOW/DRY SNOW/DRY SNOW`.
  - Each runway line is its own effect.
  - The SNOWTAM format itself defines coverage as percent and depth as millimetres, so those units count as stated, just as the FAA `OBST` format defines its first height as MSL.
  - A third reported as `DRY` or `NR` has no contaminant. An `NR` coverage or depth is `null`.

Remarks such as `RWYCC DOWNGRADED`, friction coefficients (`CRFI`, `MEASURED FRICTION COEFFICIENTS`), chemical residue and conditions on taxiways and aprons are not recorded.

## `Contaminant`

| Field | Type | Rule |
|---|---|---|
| `type` | enum | See the vocabulary below. |
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

An obstacle is a physical object (crane, tower, rig, etc.) reported in the aerodrome environment with a height or a position. Each distinct obstacle is one entry; an obstacle must state a height or a distance.

| Field | Type | Rule |
|---|---|---|
| `height` | Height? | The stated height with its datum: `AGL` for a height stated as `AGL` or labelled `HEIGHT`/`HGT` without `AMSL`/`MSL`; `MSL` for an elevation stated as `MSL` or `AMSL`, or labelled `ELEVATION`/`ELEV`. In the FAA `OBST` format `<n>FT (<n>FT AGL)`, the first height is MSL by that format's definition. When both are stated, record the MSL one. `UNKNOWN` is not a height: record the other one, or `null`. |
| `distance` | Distance? | The stated distance from the reference. |
| `reference` | ObstacleReference? | What the distance is measured from. `null` exactly when `distance` is `null`. |
| `direction` | string / number? | The direction from the reference as stated: a 16-point compass abbreviation (`WNW`, `N`), or a bearing in degrees when the text gives one (`RDL 114`, `270 DEG`, `BRG 090`). `RIGHT OF CENTERLINE` and the like are not directions; they record `null`. |

### `ObstacleReference`

| Field | Type | Rule |
|---|---|---|
| `kind` | `departureEnd` / `threshold` / `ARP` / `other` | `departureEnd` for `DER`, `DEP END`, `DEPARTURE END`, and a distance `BEYOND TORA RWY xx` or `BEYOND END RWY xx`. `threshold` for `THR`, `THRESHOLD`, `APCH END`, `APPROACH END`, `BFR THR`. `ARP` for `ARP`, and for the airport identifier in the FAA `OBST … (<n>NM <direction> <IDENT>)` format, whose reference is the airport. `other` for anything else (a taxiway, a town, a heliport, `FROM RWY` without an end). |
| `runway` | string? | For `departureEnd` and `threshold`: the runway end's direction, normalised like `RunwayEffect.runway`. It is the designator named with the end; when none is named and the NOTAM names exactly one direction, that one. For `ARP` and `other`: `null`. A runway end the text does not place on a direction is `other`. |

Positions (`PSN 523627N 0002918W`) are not recorded.

## Scope rule

The app is SF50 TOLD, for the Cirrus SF50 Vision Jet: a light, single-engine, fixed-wing jet (6,000 lb maximum takeoff weight, 39 ft wingspan). A NOTAM gets effects or obstacles only if it changes something the app models:

- runway availability for takeoff or landing (closures);
- the usable length of a direction (closed portions, the threshold, declared distances);
- runway surface condition;
- an obstacle in the aerodrome environment.

Everything else gets `effects: []` and `obstacles: []`.

| NOTAM | Label |
|---|---|
| Anything that isn't one of the four things above: runway, approach or obstacle lighting; navaids and GPS; taxiway and apron closures and FICONs (`TWY … FICON`); procedure minima and SID/STAR/IAP changes; aerodrome or service hours, ATC, fuel, customs; airspace, UAS, parachuting, military activity; markings, signs, rubber removal, grass cutting; helipad and water-lane closures and conditions | nothing |
| A runway fact given only as the reason (`DUE …`) for an out-of-scope change (`AUTH TO CIRCLING MINIMA ONLY … DUE THR DISPLACED`); a fact the text states in its own right is recorded | not recorded: the NOTAM that states the fact itself carries it |
| An obstacle named in an instrument approach procedure (IAP) or minima NOTAM (`IAP … TEMPORARY CRANE 809 MSL 1.36NM NW OF RWY 31`) | not recorded: approach obstacles are not takeoff obstacles |
| A temporary obstacle an obstacle departure procedure adds (`ODP … TEMPORARY CRANE 4739 FT FROM DER`) | an obstacle: departure obstacles are takeoff obstacles |
| A list of published obstacles in an ODP's takeoff minimum notes (`TAKEOFF OBSTACLE NOTES: TREE … FROM DER …, TREE …`) | not recorded |
| An obstacle that exists only under a stated condition (`OBST EXISTS ONLY WHEN RAISED`) | not recorded |
| An obstacle in an en-route obstacle list (`REF AIP ENR 5.4`, low-flying-zone or vertical-obstacle lists) | not recorded: it is not in an aerodrome environment |
| An obstacle at a heliport | an obstacle: which aerodromes matter is for the app to decide |
| A runway closed to a class of aircraft that excludes the SF50, or with an exception that includes it (see Closures) | `closure: "none"` |
| A runway closed to a class that includes the SF50 (`CLSD TO JET TFC`, `CLSD TO FIXED WING ACFT`), or with other exceptions (`CLSD EXC PPR`) | the closure as it reads |
| A runway closed for one operation (`LDG RWY 16R NOT AVBL`, `RWY 20 CLSD LDG`), or available for one operation only (`LIMITED TO ARR ONLY`) | `closure: "landing"` or `"takeoff"` |
| A runway or portion closed only at stated times within the NOTAM's validity | not a closure |
| A direction closed for `both` that the NOTAM also shortens | only the closure |
| A threshold that is no longer displaced, or declared distances "as published" | nothing |
| A runway FICON, even when it reports only `WET` | `surfaceCondition` |

## Canonical ordering

Gold labels are stored in canonical order, and the evaluation canonicalises model output the same way before scoring. The order the model emits in therefore never affects its score.

- **Effects** are sorted by `runway`, with `null` first and the rest in lexicographic order. Since each direction has one effect, this order is total.
- **Obstacles** are sorted by their reference's `runway` (`null` first), then its `kind`, then `height.value`, `distance.value` and `direction`. The sort is stable.
- **Contaminants** within a `surfaceCondition` are deduplicated, then sorted by `type`, `coveragePercent` and `depth`.

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
      "partialClosure": null,
      "thresholdDisplacement": null,
      "declaredDistances": {
        "TORA": {
          "value": 10810,
          "unit": "ft"
        },
        "LDA": {
          "value": 10275,
          "unit": "ft"
        }
      },
      "surfaceCondition": null
    }
  ],
  "obstacles": []
}
```

### Some declared distances stated

```text
Location: MPMG

RWY 19 TEMPO REDUCTION DECLARED DIST DUE OBST: 
TORA: 1665M
TODA: 1665M
```

LDA is not stated, so it is null. It is not copied from TORA. TODA is not recorded.

```json
{
  "isCanceled": false,
  "effects": [
    {
      "runway": "19",
      "closure": "none",
      "partialClosure": null,
      "thresholdDisplacement": null,
      "declaredDistances": {
        "TORA": {
          "value": 1665,
          "unit": "m"
        },
        "LDA": null
      },
      "surfaceCondition": null
    }
  ],
  "obstacles": []
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

The closure is stated for the pair, so each direction's effect records it, and each records its own declared distances. TODA and ASDA are not recorded.

```json
{
  "isCanceled": false,
  "effects": [
    {
      "runway": "09R",
      "closure": "none",
      "partialClosure": {
        "length": {
          "value": 1713,
          "unit": "ft"
        },
        "end": "W"
      },
      "thresholdDisplacement": null,
      "declaredDistances": {
        "TORA": {
          "value": 6787,
          "unit": "ft"
        },
        "LDA": {
          "value": 6787,
          "unit": "ft"
        }
      },
      "surfaceCondition": null
    },
    {
      "runway": "27L",
      "closure": "none",
      "partialClosure": {
        "length": {
          "value": 1713,
          "unit": "ft"
        },
        "end": "W"
      },
      "thresholdDisplacement": null,
      "declaredDistances": {
        "TORA": {
          "value": 6787,
          "unit": "ft"
        },
        "LDA": {
          "value": 6787,
          "unit": "ft"
        }
      },
      "surfaceCondition": null
    }
  ],
  "obstacles": []
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
      "partialClosure": null,
      "thresholdDisplacement": {
        "value": 210,
        "unit": "m"
      },
      "declaredDistances": {
        "TORA": {
          "value": 1090,
          "unit": "m"
        },
        "LDA": {
          "value": 990,
          "unit": "m"
        }
      },
      "surfaceCondition": null
    },
    {
      "runway": "25",
      "closure": "none",
      "partialClosure": null,
      "thresholdDisplacement": null,
      "declaredDistances": {
        "TORA": {
          "value": 1090,
          "unit": "m"
        },
        "LDA": {
          "value": 990,
          "unit": "m"
        }
      },
      "surfaceCondition": null
    }
  ],
  "obstacles": []
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
      "partialClosure": null,
      "thresholdDisplacement": {
        "value": 200,
        "unit": "m"
      },
      "declaredDistances": {
        "TORA": {
          "value": 690,
          "unit": "m"
        },
        "LDA": {
          "value": 690,
          "unit": "m"
        }
      },
      "surfaceCondition": null
    }
  ],
  "obstacles": []
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
      "partialClosure": null,
      "thresholdDisplacement": {
        "value": 320,
        "unit": "m"
      },
      "declaredDistances": null,
      "surfaceCondition": null
    }
  ],
  "obstacles": []
}
```

### Partial closure of a pair from one end, end not named

```text
Location: NKX

RWY 24L/6R CLOSED FIRST 1,500 FT FOR CONCRETE DEMO. LAST 6,500 FT OF RWY USED FOR CONSTRUCTION VEHICLES AND HAUL ROUTES.
```

"6R" is zero-padded to "06R" and "1,500" becomes 1500. FIRST is given against the pair, not one direction, so each direction records the closed length with end null.

```json
{
  "isCanceled": false,
  "effects": [
    {
      "runway": "06R",
      "closure": "none",
      "partialClosure": {
        "length": {
          "value": 1500,
          "unit": "ft"
        },
        "end": null
      },
      "thresholdDisplacement": null,
      "declaredDistances": null,
      "surfaceCondition": null
    },
    {
      "runway": "24L",
      "closure": "none",
      "partialClosure": {
        "length": {
          "value": 1500,
          "unit": "ft"
        },
        "end": null
      },
      "thresholdDisplacement": null,
      "declaredDistances": null,
      "surfaceCondition": null
    }
  ],
  "obstacles": []
}
```

### Closed portions counted from each end

```text
Location: SBTA

RWY 08 FST 100M AND RWY 26 LAST 100M CLSD DUE TO HOLE
RMK: THIS AERONAUTICAL INFORMATION WILL BE EXTENDED BY AN AIP SUP
```

FIRST (FST) is counted from the named runway's threshold and LAST from its departure end. Each direction the text names gets its own effect.

```json
{
  "isCanceled": false,
  "effects": [
    {
      "runway": "08",
      "closure": "none",
      "partialClosure": {
        "length": {
          "value": 100,
          "unit": "m"
        },
        "end": "thresholdEnd"
      },
      "thresholdDisplacement": null,
      "declaredDistances": null,
      "surfaceCondition": null
    },
    {
      "runway": "26",
      "closure": "none",
      "partialClosure": {
        "length": {
          "value": 100,
          "unit": "m"
        },
        "end": "departureEnd"
      },
      "thresholdDisplacement": null,
      "declaredDistances": null,
      "surfaceCondition": null
    }
  ],
  "obstacles": []
}
```

### Full closure of a pair

```text
Location: NZCH

RWY 02/20 CLSD DUE WIP
```

A closure stated for the pair closes each direction for both operations.

```json
{
  "isCanceled": false,
  "effects": [
    {
      "runway": "02",
      "closure": "both",
      "partialClosure": null,
      "thresholdDisplacement": null,
      "declaredDistances": null,
      "surfaceCondition": null
    },
    {
      "runway": "20",
      "closure": "both",
      "partialClosure": null,
      "thresholdDisplacement": null,
      "declaredDistances": null,
      "surfaceCondition": null
    }
  ],
  "obstacles": []
}
```

### Closed for both operations, spelled out

```text
Location: EPCE

RWY 07/25 CLSD FOR TKOF AND LDG OPERATIONS DUE TO WEATHER 
CONDITIONS.
```

Closed for takeoff and landing is closed for both, in each direction. The weather is the reason, not a condition on the closure.

```json
{
  "isCanceled": false,
  "effects": [
    {
      "runway": "07",
      "closure": "both",
      "partialClosure": null,
      "thresholdDisplacement": null,
      "declaredDistances": null,
      "surfaceCondition": null
    },
    {
      "runway": "25",
      "closure": "both",
      "partialClosure": null,
      "thresholdDisplacement": null,
      "declaredDistances": null,
      "surfaceCondition": null
    }
  ],
  "obstacles": []
}
```

### Closed for one operation

```text
Location: EPOK

RWY 13/31 CLSD FOR LDG.
```

Each direction of the pair is closed for landing only. Nothing is stated about takeoff, so no distance is recorded either.

```json
{
  "isCanceled": false,
  "effects": [
    {
      "runway": "13",
      "closure": "landing",
      "partialClosure": null,
      "thresholdDisplacement": null,
      "declaredDistances": null,
      "surfaceCondition": null
    },
    {
      "runway": "31",
      "closure": "landing",
      "partialClosure": null,
      "thresholdDisplacement": null,
      "declaredDistances": null,
      "surfaceCondition": null
    }
  ],
  "obstacles": []
}
```

### Available for one operation only

```text
Location: CYQB

RWY 29 AVBL FOR TKOF ONLY
```

Available for takeoff only means RWY 29 is closed for landing.

```json
{
  "isCanceled": false,
  "effects": [
    {
      "runway": "29",
      "closure": "landing",
      "partialClosure": null,
      "thresholdDisplacement": null,
      "declaredDistances": null,
      "surfaceCondition": null
    }
  ],
  "obstacles": []
}
```

### Negative: closed only at stated times

```text
Location: KLAX

RWY 06L/24R CLSD DLY 0730-1330
```

The closure applies only in a daily window within the NOTAM's validity, so it is not a closure.

```json
{
  "isCanceled": false,
  "effects": [],
  "obstacles": []
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
      "runway": "16R",
      "closure": "both",
      "partialClosure": null,
      "thresholdDisplacement": null,
      "declaredDistances": null,
      "surfaceCondition": null
    },
    {
      "runway": "34L",
      "closure": "both",
      "partialClosure": null,
      "thresholdDisplacement": null,
      "declaredDistances": null,
      "surfaceCondition": null
    }
  ],
  "obstacles": []
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
      "partialClosure": null,
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
            "coveragePercent": 100,
            "depth": null
          }
        ]
      }
    }
  ],
  "obstacles": []
}
```

### FICON with per-third contaminants

```text
Location: FAR

FAR RWY 31 FICON 6/3/3 10 PCT ICE AND 10 PCT COMPACTED SN, 10 PCT
ICE AND 30 PCT 1/8IN DRY SN OVER COMPACTED SN, 10 PCT ICE AND 20 PCT
COMPACTED SN OBS AT 2511280521.
```

Commas separate the thirds. Every third's contaminants are recorded; 10 PCT ICE is reported for all three thirds, so it is recorded once. The depth of a layered contaminant is the depth of its top layer.

```json
{
  "isCanceled": false,
  "effects": [
    {
      "runway": "31",
      "closure": "none",
      "partialClosure": null,
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
            "coveragePercent": 10,
            "depth": null
          },
          {
            "type": "compactedSnow",
            "coveragePercent": 20,
            "depth": null
          },
          {
            "type": "drySnowOverCompactedSnow",
            "coveragePercent": 30,
            "depth": {
              "value": 0.125,
              "unit": "in"
            }
          },
          {
            "type": "ice",
            "coveragePercent": 10,
            "depth": null
          }
        ]
      }
    }
  ],
  "obstacles": []
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

Each runway line is one effect. WET is reported for every third at 100 percent, so it is one contaminant. Depth is NR, so it is null. The RWYCC DOWNGRADED remarks are not recorded.

```json
{
  "isCanceled": false,
  "effects": [
    {
      "runway": "04L",
      "closure": "none",
      "partialClosure": null,
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
            "coveragePercent": 100,
            "depth": null
          }
        ]
      }
    },
    {
      "runway": "04R",
      "closure": "none",
      "partialClosure": null,
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
            "coveragePercent": 100,
            "depth": null
          }
        ]
      }
    },
    {
      "runway": "15",
      "closure": "none",
      "partialClosure": null,
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
            "coveragePercent": 100,
            "depth": null
          }
        ]
      }
    }
  ],
  "obstacles": []
}
```

### SNOWTAM with depth

```text
Location: BGQQ

SWBG0221 BGQQ 09241032
 (SNOWTAM 0221
 BGQQ
 09241032 16 5/5/5 100/100/100 03/03/03 DRY SNOW/DRY SNOW/DRY SNOW
 
 RWY 16 MEASURED FRICTION COEFFICIENTS 68/69/69 TAP. REMARK/ RWY 16 
 TAKEOFF SIGNIFICANT CONTAMINANT THIN RWYCC 5/5/5.)
```

The SNOWTAM format defines depth in millimetres. Friction coefficients are not recorded.

```json
{
  "isCanceled": false,
  "effects": [
    {
      "runway": "16",
      "closure": "none",
      "partialClosure": null,
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
            "coveragePercent": 100,
            "depth": {
              "value": 3,
              "unit": "mm"
            }
          }
        ]
      }
    }
  ],
  "obstacles": []
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

RSC 16 and RSC 34 are two reports, one effect each. Commas separate the thirds, and each third's coverage differs, so each is a contaminant. The CRFI friction values and the taxiway and apron remarks are not recorded.

```json
{
  "isCanceled": false,
  "effects": [
    {
      "runway": "16",
      "closure": "none",
      "partialClosure": null,
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
            "coveragePercent": 40,
            "depth": {
              "value": 0.125,
              "unit": "in"
            }
          },
          {
            "type": "wetSnow",
            "coveragePercent": 50,
            "depth": {
              "value": 0.125,
              "unit": "in"
            }
          },
          {
            "type": "wetSnow",
            "coveragePercent": 70,
            "depth": {
              "value": 0.125,
              "unit": "in"
            }
          }
        ]
      }
    },
    {
      "runway": "34",
      "closure": "none",
      "partialClosure": null,
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
            "coveragePercent": 40,
            "depth": {
              "value": 0.125,
              "unit": "in"
            }
          },
          {
            "type": "wetSnow",
            "coveragePercent": 50,
            "depth": {
              "value": 0.125,
              "unit": "in"
            }
          },
          {
            "type": "wetSnow",
            "coveragePercent": 70,
            "depth": {
              "value": 0.125,
              "unit": "in"
            }
          }
        ]
      }
    }
  ],
  "obstacles": []
}
```

### Obstacle near the aerodrome

```text
Location: JFK

JFK OBST CRANE (ASN 2024-AEA-1604-NRA) 403906N0734931W (2.2NM WNW
JFK) 114FT (100FT AGL) FLAGGED AND LGTD
```

In the FAA OBST format `<n>FT (<n>FT AGL)`, the first height is MSL, and when both are stated the MSL one is recorded. The reference in that format is the airport, so it is ARP, and WNW is the direction. The position is not recorded.

```json
{
  "isCanceled": false,
  "effects": [],
  "obstacles": [
    {
      "height": {
        "value": 114,
        "unit": "ft",
        "datum": "MSL"
      },
      "distance": {
        "value": 2.2,
        "unit": "nm"
      },
      "reference": {
        "kind": "ARP",
        "runway": null
      },
      "direction": "WNW"
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

The MSL height is UNKNOWN, so the AGL height is recorded. APCH END RWY 03L is runway 03L's threshold, and N is the direction from it.

```json
{
  "isCanceled": false,
  "effects": [],
  "obstacles": [
    {
      "height": {
        "value": 60,
        "unit": "ft",
        "datum": "AGL"
      },
      "distance": {
        "value": 1,
        "unit": "nm"
      },
      "reference": {
        "kind": "threshold",
        "runway": "03L"
      },
      "direction": "N"
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

Beyond the end of TORA RWY 18C is beyond its departure end. The text gives no compass direction, so direction is null.

```json
{
  "isCanceled": false,
  "effects": [],
  "obstacles": [
    {
      "height": {
        "value": 138,
        "unit": "ft",
        "datum": "MSL"
      },
      "distance": {
        "value": 2000,
        "unit": "m"
      },
      "reference": {
        "kind": "departureEnd",
        "runway": "18C"
      },
      "direction": null
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

HEIGHT is above ground and ELEV is above sea level; both are stated, so the elevation is recorded. RDL 114 is a bearing in degrees from the ARP.

```json
{
  "isCanceled": false,
  "effects": [],
  "obstacles": [
    {
      "height": {
        "value": 572,
        "unit": "ft",
        "datum": "MSL"
      },
      "distance": {
        "value": 0.62,
        "unit": "nm"
      },
      "reference": {
        "kind": "ARP",
        "runway": null
      },
      "direction": 114
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
  "effects": [],
  "obstacles": []
}
```

### Relocated threshold

```text
Location: KTKI

RWY 18 THR RELOCATED 1040FT S DECLARED DIST: TORA 5962FT TODA 5962FT ASDA 6462FT LDA 6462FT
```

A relocated threshold shortens the runway just as a displaced one does, so it is recorded as thresholdDisplacement. TODA and ASDA are not recorded.

```json
{
  "isCanceled": false,
  "effects": [
    {
      "runway": "18",
      "closure": "none",
      "partialClosure": null,
      "thresholdDisplacement": {
        "value": 1040,
        "unit": "ft"
      },
      "declaredDistances": {
        "TORA": {
          "value": 5962,
          "unit": "ft"
        },
        "LDA": {
          "value": 6462,
          "unit": "ft"
        }
      },
      "surfaceCondition": null
    }
  ],
  "obstacles": []
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
      "partialClosure": null,
      "thresholdDisplacement": {
        "value": 160,
        "unit": "m"
      },
      "declaredDistances": {
        "TORA": null,
        "LDA": {
          "value": 320,
          "unit": "m"
        }
      },
      "surfaceCondition": null
    },
    {
      "runway": "30L",
      "closure": "none",
      "partialClosure": null,
      "thresholdDisplacement": null,
      "declaredDistances": {
        "TORA": null,
        "LDA": {
          "value": 320,
          "unit": "m"
        }
      },
      "surfaceCondition": null
    }
  ],
  "obstacles": []
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
  "effects": [],
  "obstacles": []
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

The SF50 is a jet, so a closure to jet traffic applies to it, in each direction.

```json
{
  "isCanceled": false,
  "effects": [
    {
      "runway": "18",
      "closure": "both",
      "partialClosure": null,
      "thresholdDisplacement": null,
      "declaredDistances": null,
      "surfaceCondition": null
    },
    {
      "runway": "36",
      "closure": "both",
      "partialClosure": null,
      "thresholdDisplacement": null,
      "declaredDistances": null,
      "surfaceCondition": null
    }
  ],
  "obstacles": []
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
      "closure": "both",
      "partialClosure": null,
      "thresholdDisplacement": null,
      "declaredDistances": null,
      "surfaceCondition": null
    },
    {
      "runway": "20",
      "closure": "both",
      "partialClosure": null,
      "thresholdDisplacement": null,
      "declaredDistances": null,
      "surfaceCondition": null
    }
  ],
  "obstacles": []
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

Departure-procedure obstacles are takeoff obstacles, unlike obstacles named in approach procedures. The distance is from RWY 19's departure end; RIGHT OF CENTERLINE is not a direction. The climb gradient is not recorded.

```json
{
  "isCanceled": false,
  "effects": [],
  "obstacles": [
    {
      "height": {
        "value": 440,
        "unit": "ft",
        "datum": "MSL"
      },
      "distance": {
        "value": 4739,
        "unit": "ft"
      },
      "reference": {
        "kind": "departureEnd",
        "runway": "19"
      },
      "direction": null
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
  "effects": [],
  "obstacles": []
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
  "effects": [],
  "obstacles": []
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
  "effects": [],
  "obstacles": []
}
```
