"""THE BUILD LOGIC: a whole-job schedule made from the SCOPE of a building and
the ORDER construction has to follow, then held against the filed daily logs.

Operator, 2026-11-20: "predictive schedule engine based on the project scope
and construction logic for the type of building": the superstructure cycle per
floor, sleeves per floor, the earliest framing can start once the forms are
out, the trades behind it, and STRICT logic ("can't close sheetrock before
insulation inspected, all vent lines connected to fans, AC drain lines
connected to drain"). And from it: the quickest way to build, where the job
stands, and where it can be improved.

THREE THINGS, all pure (no database, no network, no model):

  network(scope)        every activity of the job, floor by floor, with what
                        must come before it. A link is HARD (the work cannot
                        physically or legally go ahead without it) or SOFT
                        (the usual order; a choice).
  plan(scope)           the earliest dates the logic allows (critical path),
                        the chain that sets the finish, the absolute minimum
                        with unlimited crews, and which second crew buys days.
  status(scope, rows, end)
                        the same network with the daily logs laid over it:
                        what is done, work logged BEFORE something it depends
                        on, how long each trade waited after its floor was
                        ready, what the logic says can start today, and the
                        finish the remaining logic gives.

THE DURATIONS ARE ASSUMPTIONS, STATED AS SUCH. DAYS below is working days per
floor for a floor of BASE_UNITS apartments (or for the whole job). They are a
starting table, not measurements; Scope.days overrides any of them, and
measured_cycle() reads the real floor-to-floor pace out of the logs. The ORDER
is the part that does not depend on them.

THE RULES ARE DATA: ACTS and LINKS. Changing a rule is changing a row.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from statistics import median
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from lib import progress_stages as PS
from lib import report_calendar

SYSTEMS = ("cast_in_place", "cfs", "block_plank")
BASE_UNITS = 6.0
#: A trade not seen on a floor for this many worked site days is no longer "active" there.
AWAY = 7
#: A wait shorter than this many worked site days is not worth a finding.
MIN_WAIT = 3


@dataclass(frozen=True)
class Scope:
    """What is being built. Everything the schedule is made from."""
    floors: int
    system: str = "cast_in_place"
    units_per_floor: float = BASE_UNITS
    piles: bool = False
    cellar: bool = False
    bulkhead: bool = False
    sprinkler: bool = True
    gas: bool = False
    elevator: bool = False
    #: Working days from one floor's structure starting to the next floor's; None = the table's own cycle.
    cycle_days: Optional[float] = None
    #: Working days between a slab pour and its forms coming out (cast in place).
    strip_days: float = 5.0
    #: {activity key: working days} to replace the table.
    days: Mapping[str, float] = field(default_factory=dict)
    #: {trade: crews working different floors at once}; default one.
    crews: Mapping[str, int] = field(default_factory=dict)

    def flags(self) -> set:
        on = {self.system}
        for name in ("piles", "cellar", "bulkhead", "sprinkler", "gas", "elevator"):
            if getattr(self, name):
                on.add(name)
        return on


@dataclass(frozen=True)
class Act:
    key: str
    label: str
    es: str
    trade: str = ""               # the crew; "" = nobody (a milestone)
    family: str = ""              # the progress_stages family the logs report it under
    per: str = "floor"            # "floor" | "job"
    days: float = 0.0
    scales: bool = False          # per-floor days grow with apartments per floor
    x_floors: bool = False        # a job-wide activity whose days are per floor
    gate: bool = False            # an inspection, test or check: no crew, it must be PASSED
    cycle: bool = False           # part of the superstructure cycle (Scope.cycle_days stretches it)
    only: Tuple[str, ...] = ()    # Scope flags it needs
    words: str = ""               # within its family, the log lines that mean THIS activity


def _a(key, label, es, trade="", family="", days=0.0, **kw) -> Act:
    return Act(key=key, label=label, es=es, trade=trade, family=family, days=days, **kw)


CIP, CFS, BP = ("cast_in_place",), ("cfs",), ("block_plank",)

ACTS: Tuple[Act, ...] = (
    # ── below the building ──
    _a("site_prep", "Site prep & layout", "Preparación del sitio", "excavation", "excavation", 3, per="job",
       words=r"site prep|layout|survey"),
    _a("excavation", "Excavation & shoring", "Excavación y apuntalamiento", "excavation", "excavation", 8, per="job"),
    _a("piles", "Piles & pile caps", "Pilotes y cabezales", "foundation", "excavation", 6, per="job", only=("piles",),
       words=r"\bpiles?\b"),
    _a("foundations", "Footings, grade beams & foundation walls", "Zapatas, vigas y muros de cimentación",
       "concrete", "excavation", 10, per="job", words=r"footing|foundation|grade beam"),
    _a("foundation_waterproofing", "Foundation waterproofing & backfill", "Impermeabilización y relleno",
       "waterproofing", "excavation", 4, per="job", only=("cellar",), words=r"waterproof|backfill"),
    _a("underground_plumbing", "Underground plumbing & under-slab MEP", "Plomería subterránea y MEP bajo losa",
       "plumbing", "plumbing", 3, per="job", words=r"underground|under.?slab"),
    _a("gate_underground", "Underground plumbing inspection", "Inspección de plomería subterránea",
       family="plumbing", days=1, per="job", gate=True,
       words=r"under.?(?:ground|slab).*inspect"),
    _a("slab_on_grade", "Slab on grade", "Losa sobre terreno", "concrete", "concrete", 3, per="job"),

    # ── superstructure, one cycle per floor: cast in place ──
    _a("verticals", "Columns & shear walls (rebar, forms, pour)", "Columnas y muros (acero, cimbra, colado)",
       "concrete", "concrete", 2, cycle=True, only=CIP, words=r"column|shear ?wall"),
    _a("deck_forms", "Slab shoring & formwork", "Apuntalamiento y cimbra de losa", "concrete", "concrete", 2,
       cycle=True, only=CIP, words=r"\bform(?:s|work)?\b|shoring"),
    _a("slab_rebar", "Slab rebar", "Acero de losa", "concrete", "concrete", 2, cycle=True, only=CIP,
       words=r"rebar|post.?tension"),
    _a("sleeves", "MEP sleeves & embeds in the deck", "Pasamuros y embebidos MEP en la losa", "mep", "", 1,
       only=CIP,
       words=r"sleeve|embed"),
    _a("gate_pour", "Pre-pour inspection (rebar, sleeves)", "Inspección previa al colado (acero, pasamuros)",
       gate=True, only=CIP,
       words=r"pre.?pour|rebar.*inspect"),
    _a("pour_slab", "Pour slab", "Colado de losa", "concrete", "concrete", 1, only=CIP, words=r"pour"),
    _a("strip", "Strip forms & reshore", "Descimbrado y reapuntalamiento", "concrete", "concrete", 1, only=CIP,
       words=r"strip|reshor"),
    # ── cold-formed steel bearing walls ──
    _a("cfs_walls", "Bearing walls (track, studs, sheathing)", "Muros de carga (canal, postes, forro)",
       "framing", "framing", 3, cycle=True, only=CFS),
    _a("cfs_deck", "Floor joists, deck & topping", "Viguetas, cubierta y firme", "framing", "framing", 3,
       cycle=True, only=CFS, words=r"joist|deck|topping|subfloor"),
    _a("cfs_sleeves", "MEP floor penetrations & sleeves", "Pasos y pasamuros MEP en el piso", "mep", "", 1, only=CFS,
       words=r"sleeve|penetration|\bcor(?:e|es|ing)\b"),
    # ── block and plank ──
    _a("cmu_walls", "Block bearing walls", "Muros de bloque de carga", "masonry", "facade", 4, cycle=True, only=BP,
       words=r"\bblock\b|cmu|masonry"),
    _a("plank", "Plank, grout & topping", "Losas prefabricadas, lechada y firme", "concrete", "concrete", 2,
       cycle=True, only=BP, words=r"plank|grout|topping"),
    _a("bp_sleeves", "MEP sleeves & cores in the plank", "Pasamuros y perforaciones MEP", "mep", "", 1, only=BP,
       words=r"sleeve|penetration|\bcor(?:e|es|ing)\b"),
    # ── every system meets here ──
    _a("structure", "Floor structure closed (floor above is on, forms out)",
       "Estructura del piso cerrada (piso superior colocado, sin cimbra)"),
    _a("top_out", "Structure topped out", "Estructura terminada", per="job"),

    # ── roof and outside ──
    _a("bulkhead", "Roof bulkhead", "Caseta de azotea", "structure", "", 5, per="job", only=("bulkhead",)),
    _a("roofing", "Roofing & flashing", "Techado y tapajuntas", "roofing", "roofing", 6, per="job"),
    _a("roof_mep", "Rooftop units, fans & roof MEP", "Equipos de azotea, ventiladores y MEP", "hvac", "hvac", 4,
       per="job", words=r"roof|rtu"),
    _a("scaffold", "Scaffold up", "Montaje de andamio", "scaffold", "", 4, per="job",
       words=r"scaffold"),
    _a("windows", "Windows & exterior doors", "Ventanas y puertas exteriores", "windows", "windows", 2),
    _a("facade", "Exterior walls & facade", "Muros exteriores y fachada", "facade", "facade", 5, per="job",
       x_floors=True),
    _a("scaffold_down", "Scaffold down", "Desmontaje de andamio", "scaffold", "", 3, per="job",
       words=r"scaffold.*(?:dismantl|remov|down)|dismantl"),

    # ── inside, floor by floor: framing and rough-ins ──
    _a("framing", "Interior framing (layout, track, studs, door bucks)",
       "Bastidores interiores (trazo, canal, postes, marcos)", "framing", "framing", 5, scales=True,
       words=r"interior|partition|door buck|ceiling drop|soffit|furring"),
    _a("plumbing_rough", "Plumbing rough-in (waste, vent, water)", "Plomería en bruto (desagüe, ventilación, agua)",
       "plumbing", "plumbing", 5, scales=True),
    _a("gas_rough", "Gas piping", "Tubería de gas", "plumbing", "", 2, only=("gas",),
       words=r"\bgas\b"),
    _a("hvac_rough", "HVAC rough-in (ducts, exhaust, refrigerant & drain lines)",
       "HVAC en bruto (ductos, extracción, líneas de refrigerante y drenaje)", "hvac", "hvac", 4, scales=True),
    _a("sprinkler_rough", "Sprinkler rough-in", "Rociadores en bruto", "sprinkler", "sprinkler", 4, scales=True,
       only=("sprinkler",)),
    _a("electrical_rough", "Electrical rough-in", "Electricidad en bruto", "electrical", "electrical", 5,
       scales=True),
    _a("low_voltage_rough", "Fire alarm & low-voltage rough-in", "Alarma contra incendio y baja tensión en bruto",
       "low_voltage", "low_voltage", 2, scales=True),
    _a("blocking", "Blocking & backing", "Refuerzos y soportes en muros", "framing", "framing", 1,
       words=r"\bblocking\b|backing"),

    # ── the checks that stand between rough-in and closed walls ──
    _a("gate_plumbing", "Plumbing rough inspection & pressure test", "Inspección y prueba de presión de plomería",
       family="plumbing", days=1, gate=True,
       words=r"^plumbing:.*(?:inspect|test|hydro)"),
    _a("gate_gas", "Gas pressure test & inspection", "Prueba de presión e inspección de gas", days=1, gate=True,
       only=("gas",),
       words=r"gas.*(?:test|inspect)"),
    _a("gate_sprinkler", "Sprinkler hydrostatic test", "Prueba hidrostática de rociadores", family="sprinkler",
       days=1, gate=True, only=("sprinkler",),
       words=r"^sprinkler:.*(?:inspect|test|hydro)|sprinkler.*(?:test|hydro)"),
    _a("gate_electrical", "Electrical rough inspection", "Inspección eléctrica en bruto", family="electrical",
       days=1, gate=True,
       words=r"^electrical:.*(?:inspect|test)"),
    _a("check_exhaust", "Every vent and exhaust duct connected to its fan",
       "Todo ducto de ventilación y extracción conectado a su ventilador", family="hvac", gate=True,
       words=r"(?:duct|vent|exhaust).*connect|fans? connect"),
    _a("check_condensate", "Every AC drain line connected to a drain",
       "Toda línea de drenaje de aire acondicionado conectada a un desagüe", gate=True,
       words=r"(?:condensate|drain lines?|a/?c drains?).*connect"),
    _a("firestopping", "Firestopping of penetrations", "Sellado cortafuego de penetraciones", "firestopping",
       "insulation", 2, words=r"fire ?stop"),
    _a("gate_firestop", "Firestopping inspection", "Inspección de sellado cortafuego", days=1, gate=True,
       words=r"fire ?stop.*inspect|inspect.*fire ?stop"),
    _a("insulation", "Insulation", "Aislamiento", "insulation", "insulation", 2, scales=True),
    _a("gate_insulation", "Insulation / energy code inspection", "Inspección de aislamiento / código de energía",
       family="insulation", days=1, gate=True,
       words=r"^insulation:.*inspect|energy.*inspect|insulation.*inspect"),

    # ── closing and finishing, floor by floor ──
    _a("drywall", "Sheetrock (close walls & ceilings)", "Tablaroca (cierre de muros y plafones)", "drywall",
       "drywall", 5, scales=True),
    _a("taping", "Taping & compound", "Encintado y compuesto", "taping", "taping", 6, scales=True),
    _a("prime", "Prime", "Sellador", "painting", "painting", 2, scales=True, words=r"prim"),
    _a("tile", "Bathroom waterproofing & tile", "Impermeabilización y azulejo de baños", "tile", "flooring", 5,
       scales=True, words=r"til(?:e|es|ing)\b|grout|thin ?set|waterproof"),
    _a("underlayment", "Floor underlayment (sound mat, gypsum topping)", "Base de piso (acústica, firme de yeso)",
       "flooring", "flooring", 2, scales=True, words=r"underlayment|gyp.?crete|self.?level|sound mat"),
    _a("flooring", "Flooring", "Pisos", "flooring", "flooring", 4, scales=True),
    _a("millwork", "Kitchens, vanities, doors & trim", "Cocinas, tocadores, puertas y molduras", "millwork", "", 5,
       scales=True,
       words=r"cabinet|vanit|millwork|kitchens?\b|counter ?tops?|interior doors?|door hanging"),
    _a("plumbing_finish", "Plumbing fixtures", "Muebles y accesorios de plomería", "plumbing", "plumbing_finish", 3,
       scales=True),
    _a("electrical_finish", "Electrical devices & lights", "Dispositivos eléctricos y luminarias", "electrical",
       "electrical_finish", 3, scales=True),
    _a("hvac_finish", "HVAC grilles, units & start-up", "Rejillas, equipos y arranque de HVAC", "hvac",
       "hvac_finish", 2, scales=True),
    _a("sprinkler_finish", "Sprinkler heads & trim", "Cabezas y acabados de rociadores", "sprinkler",
       "sprinkler_finish", 1, only=("sprinkler",)),
    _a("low_voltage_finish", "Fire alarm & low-voltage devices", "Dispositivos de alarma y baja tensión",
       "low_voltage", "low_voltage_finish", 1),
    _a("paint", "Finish paint", "Pintura final", "painting", "painting", 3, scales=True),
    _a("punch", "Punch list", "Lista de pendientes", "gc", "", 2,
       words=r"punch"),

    # ── the building's own close-out ──
    _a("elevator", "Elevator install", "Instalación de elevador", "elevator", "", 30, per="job", only=("elevator",),
       words=r"elevator"),
    _a("gate_elevator", "Elevator inspection", "Inspección de elevador", days=2, per="job", gate=True,
       only=("elevator",),
       words=r"elevator.*(?:test|inspect)"),
    _a("gate_fire_alarm", "Fire alarm test", "Prueba de alarma contra incendio", days=3, per="job", gate=True,
       words=r"fire alarm.*(?:test|inspect)"),
    _a("gate_final", "Final inspections & sign-offs", "Inspecciones finales y aprobaciones", days=5, per="job",
       gate=True,
       words=r"final inspect|sign.?off|\btco\b|certificate of occupancy"),
    _a("tco", "Ready for TCO", "Listo para TCO", per="job"),
)
ACT = {a.key: a for a in ACTS}


@dataclass(frozen=True)
class Link:
    a: str                 # this ...
    b: str                 # ... before this
    why: str = ""
    es: str = ""
    hard: bool = True
    kind: str = "FS"       # FS: b starts after a FINISHES.  SS: b starts `lag` days after a STARTS.
    lag: float = 0.0
    rel: str = ""          # floor to floor: "" same floor | "below": b needs a on the floor below
    #                        floor/job mix:  "" every floor | "top" | "first"
    #: PHYSICAL: b cannot exist without a (a wall on a deck). Work logged on b proves a is behind it,
    #: whatever the logs say. A hard link that is not physical CAN be broken on site, and that is a finding.
    phys: bool = False


def _h(a, b, why, es, **kw) -> Link:
    return Link(a, b, why, es, True, **kw)


def _p(a, b, why, es, **kw) -> Link:
    return Link(a, b, why, es, True, phys=True, **kw)


def _s(a, b, why="the usual order", es="el orden habitual", **kw) -> Link:
    return Link(a, b, why, es, False, **kw)


_COVER = ("once the board is up nobody can see or reach it", "con la tablaroca puesta ya no se puede ver ni alcanzar")

LINKS: Tuple[Link, ...] = (
    # below the building
    _p("site_prep", "excavation", "the site is laid out and protected first", "primero se traza y protege el sitio"),
    _p("excavation", "piles", "piles are driven from the excavated grade", "los pilotes se hincan desde la excavación"),
    _p("piles", "foundations", "pile caps and footings sit on the piles", "las zapatas se apoyan en los pilotes"),
    _p("excavation", "foundations", "footings are poured in the excavation", "las zapatas se cuelan en la excavación"),
    _h("foundations", "foundation_waterproofing", "the wall has to exist to be waterproofed",
       "el muro debe existir para impermeabilizarse"),
    _h("foundations", "underground_plumbing", "underground pipes run inside the foundation",
       "la tubería subterránea corre dentro de la cimentación"),
    _h("underground_plumbing", "gate_underground", "the pipes are inspected before they are buried",
       "la tubería se inspecciona antes de enterrarla"),
    _h("gate_underground", "slab_on_grade", "the slab buries the underground plumbing for good",
       "la losa entierra la plomería para siempre"),
    _p("foundations", "slab_on_grade", "the slab sits inside the foundation", "la losa va dentro de la cimentación"),
    _p("underground_plumbing", "slab_on_grade", "the slab buries the underground plumbing for good",
       "la losa entierra la plomería para siempre"),
    _h("foundation_waterproofing", "slab_on_grade", "backfill and waterproofing are done from outside first",
       "primero el relleno y la impermeabilización"),
    # cast in place: the cycle
    _p("slab_on_grade", "verticals", "the first columns stand on the slab", "las primeras columnas se apoyan en la losa",
       rel="first"),
    _p("pour_slab", "verticals", "the next floor is built on the slab just poured",
       "el siguiente piso se construye sobre la losa recién colada", rel="below", lag=1),
    _p("verticals", "deck_forms", "the deck forms land on the poured columns and walls",
       "la cimbra se apoya en columnas y muros colados"),
    _p("deck_forms", "slab_rebar", "rebar is placed on the formed deck", "el acero se coloca sobre la cimbra"),
    _h("deck_forms", "sleeves", "sleeves are set on the formed deck", "los pasamuros se fijan sobre la cimbra"),
    _h("slab_rebar", "gate_pour", "rebar is inspected before concrete covers it",
       "el acero se inspecciona antes de cubrirlo"),
    _h("sleeves", "gate_pour", "a sleeve missed before the pour is a core drill after it",
       "un pasamuros olvidado es una perforación después"),
    _h("gate_pour", "pour_slab", "no pour without the inspection", "no se cuela sin la inspección"),
    _p("slab_rebar", "pour_slab", "the concrete covers the rebar", "el concreto cubre el acero"),
    _p("pour_slab", "strip", "the slab must gain strength before the forms come out",
       "la losa debe ganar resistencia antes de descimbrar", lag=-1),      # lag set from Scope.strip_days
    _p("strip", "structure", "the floor is usable once the forms are out",
       "el piso es utilizable al salir la cimbra"),
    # cold-formed steel
    _p("slab_on_grade", "cfs_walls", "the first walls stand on the slab", "los primeros muros se apoyan en la losa",
       rel="first"),
    _p("cfs_deck", "cfs_walls", "the next floor's walls stand on the deck below",
       "los muros del siguiente piso se apoyan en la cubierta", rel="below"),
    _p("cfs_walls", "cfs_deck", "joists bear on the walls", "las viguetas se apoyan en los muros"),
    _h("cfs_walls", "cfs_sleeves", "penetrations are laid out with the floor framing",
       "los pasos se trazan con el entramado", kind="SS", lag=1),
    _p("cfs_deck", "structure", "the floor is closed when the deck above is on",
       "el piso se cierra cuando está la cubierta superior"),
    _h("cfs_sleeves", "structure", "floor penetrations go in before the topping",
       "los pasos se hacen antes del firme"),
    # block and plank
    _p("slab_on_grade", "cmu_walls", "the first walls stand on the slab", "los primeros muros se apoyan en la losa",
       rel="first"),
    _p("plank", "cmu_walls", "the next floor's block stands on the plank below",
       "el bloque del siguiente piso se apoya en la losa", rel="below"),
    _p("cmu_walls", "plank", "plank bears on the block", "la losa se apoya en el bloque"),
    _h("cmu_walls", "bp_sleeves", "cores are laid out with the plank", "las perforaciones se trazan con la losa",
       kind="SS", lag=1),
    _p("plank", "structure", "the floor is closed when the plank above is grouted",
       "el piso se cierra con la losa superior colocada"),
    _h("bp_sleeves", "structure", "cores are cut before the topping", "se perfora antes del firme"),
    # top of the building and outside
    _p("structure", "top_out", "the top floor's structure is the last", "la estructura del último piso es la última",
       rel="top"),
    _p("top_out", "bulkhead", "the bulkhead sits on the roof structure", "la caseta se apoya en la azotea"),
    _p("top_out", "roofing", "the roof deck has to exist", "debe existir la cubierta"),
    _p("bulkhead", "roofing", "roofing flashes up the bulkhead walls", "el techado remata contra la caseta"),
    _h("top_out", "roof_mep", "the units sit on the roof structure", "los equipos van sobre la estructura de azotea"),
    _s("roofing", "roof_mep", "units sit on finished roofing and curbs", "los equipos van sobre el techado terminado",
       kind="SS", lag=2),
    _h("top_out", "scaffold", "the scaffold goes to the top of the structure", "el andamio llega hasta arriba"),
    _p("structure", "windows", "the opening exists once the floor above is on",
       "el vano existe cuando está el piso superior"),
    _h("scaffold", "facade", "the facade is worked from the scaffold", "la fachada se trabaja desde el andamio"),
    _s("windows", "facade", "the facade finishes against the window frames", "la fachada remata contra las ventanas"),
    _h("facade", "scaffold_down", "the scaffold stays until the facade is done",
       "el andamio se queda hasta terminar la fachada"),
    # inside: framing and rough-ins
    _p("structure", "framing", "partitions are laid out on a floor with its forms out and the floor above on",
       "los muros se trazan en un piso descimbrado y con el piso superior colocado"),
    _h("framing", "plumbing_rough", "pipes are hung in and through the studs", "la tubería pasa por los postes",
       kind="SS", lag=2),
    _h("framing", "hvac_rough", "ducts need the framed ceilings and shafts", "los ductos necesitan plafones y ductos armados",
       kind="SS", lag=2),
    _h("framing", "sprinkler_rough", "sprinkler mains hang from the framed ceilings",
       "los rociadores cuelgan de los plafones armados", kind="SS", lag=2),
    _h("framing", "gas_rough", "gas pipe runs in the framed walls", "el gas corre por los muros armados",
       kind="SS", lag=2),
    _h("framing", "electrical_rough", "boxes and wire go on the studs", "cajas y cable van en los postes",
       kind="SS", lag=3),
    _s("hvac_rough", "electrical_rough", "big ducts and pipes first, wire fits around them",
       "primero ductos y tubos, el cable se acomoda", kind="SS", lag=1),
    _s("plumbing_rough", "electrical_rough", "big ducts and pipes first, wire fits around them",
       "primero ductos y tubos, el cable se acomoda", kind="SS", lag=1),
    _h("framing", "low_voltage_rough", "cable runs through finished framing", "el cable pasa por el bastidor",
       kind="SS", lag=3),
    _h("framing", "blocking", "blocking is fixed between the studs", "los refuerzos van entre los postes",
       kind="SS", lag=2),
    # the checks before the walls close
    _h("plumbing_rough", "gate_plumbing", "the rough-in is tested when it is complete",
       "la instalación se prueba al terminarla"),
    _h("gas_rough", "gate_gas", "gas pipe is pressure tested when complete", "el gas se prueba al terminarlo"),
    _h("sprinkler_rough", "gate_sprinkler", "sprinkler pipe is tested when complete",
       "los rociadores se prueban al terminarlos"),
    _h("electrical_rough", "gate_electrical", "wiring is inspected when complete",
       "el cableado se inspecciona al terminarlo"),
    _h("hvac_rough", "check_exhaust", "the ducts have to be run to be connected", "los ductos deben estar tendidos"),
    _h("hvac_rough", "check_condensate", "the drain lines have to be run", "las líneas de drenaje deben estar tendidas"),
    _h("plumbing_rough", "check_condensate", "the drain they connect to has to be there",
       "el desagüe al que se conectan debe existir"),
    _h("plumbing_rough", "firestopping", "every penetration must be made before it is sealed",
       "cada penetración debe existir antes de sellarla"),
    _h("hvac_rough", "firestopping", "every penetration must be made before it is sealed",
       "cada penetración debe existir antes de sellarla"),
    _h("electrical_rough", "firestopping", "every penetration must be made before it is sealed",
       "cada penetración debe existir antes de sellarla"),
    _h("sprinkler_rough", "firestopping", "every penetration must be made before it is sealed",
       "cada penetración debe existir antes de sellarla"),
    _h("firestopping", "gate_firestop", "firestopping is inspected before it is covered",
       "el sellado se inspecciona antes de cubrirlo"),
    _h("gate_plumbing", "insulation", "insulation covers the pipes: they are tested first",
       "el aislamiento cubre la tubería: primero se prueba"),
    _h("gate_electrical", "insulation", "insulation covers the wiring: it is inspected first",
       "el aislamiento cubre el cableado: primero se inspecciona"),
    _h("windows", "insulation", "insulation must stay dry", "el aislamiento debe mantenerse seco"),
    _h("insulation", "gate_insulation", "insulation is inspected before it is covered",
       "el aislamiento se inspecciona antes de cubrirlo"),
    _h("gate_plumbing", "drywall", *_COVER),
    _h("gate_gas", "drywall", *_COVER),
    _h("gate_sprinkler", "drywall", *_COVER),
    _h("gate_electrical", "drywall", *_COVER),
    _h("check_exhaust", "drywall", "a duct left loose from its fan cannot be reached again",
       "un ducto suelto de su ventilador ya no se alcanza"),
    _h("check_condensate", "drywall", "a drain line left open floods the finished ceiling",
       "una línea de drenaje abierta inunda el plafón terminado"),
    _h("gate_firestop", "drywall", *_COVER),
    _h("gate_insulation", "drywall", "the wall cannot be closed before the insulation is inspected",
       "no se cierra el muro antes de inspeccionar el aislamiento"),
    _h("low_voltage_rough", "drywall", *_COVER),
    _h("hvac_rough", "drywall", "ducts and lines above the ceiling are closed in by the board",
       "los ductos y líneas sobre el plafón quedan cerrados por la tablaroca"),
    _h("blocking", "drywall", *_COVER),
    _h("windows", "drywall", "board must stay dry: the floor is closed to weather first",
       "la tablaroca debe mantenerse seca: primero se cierra el piso"),
    _h("roofing", "drywall", "board under an open roof gets wet", "la tablaroca bajo una azotea abierta se moja",
       rel="top"),
    # closing and finishing
    _p("drywall", "taping", "tape goes on hung board", "la cinta va sobre la tablaroca colocada"),
    _p("taping", "prime", "primer goes on sanded compound", "el sellador va sobre el compuesto lijado"),
    _h("taping", "tile", "tile goes on finished, waterproofed board", "el azulejo va sobre tablaroca terminada"),
    _h("taping", "flooring", "sanding dust and compound ruin a finished floor",
       "el polvo y el compuesto arruinan un piso terminado"),
    _h("structure", "underlayment", "underlayment goes on the bare floor", "la base va sobre el piso desnudo"),
    _h("underlayment", "flooring", "the finished floor goes on the underlayment", "el piso terminado va sobre la base"),
    _s("prime", "tile"),
    _s("prime", "flooring"),
    _h("prime", "millwork", "cabinets go against primed walls", "los gabinetes van contra muros sellados"),
    _s("flooring", "millwork"),
    _h("tile", "plumbing_finish", "toilets and tubs trim are set on finished tile",
       "los muebles se colocan sobre azulejo terminado"),
    _h("millwork", "plumbing_finish", "sinks and faucets go on the vanities and counters",
       "lavabos y llaves van sobre tocadores y cubiertas"),
    _h("prime", "electrical_finish", "devices go on primed walls", "los dispositivos van sobre muros sellados"),
    _h("prime", "hvac_finish", "grilles go on primed ceilings", "las rejillas van sobre plafones sellados"),
    _h("prime", "sprinkler_finish", "heads and trim go on primed ceilings",
       "cabezas y acabados van sobre plafones sellados"),
    _h("prime", "low_voltage_finish", "devices go on primed walls", "los dispositivos van sobre muros sellados"),
    _h("prime", "paint", "finish coats go over primer", "la pintura final va sobre el sellador"),
    _s("millwork", "paint"),
    _s("tile", "paint"),
    _h("paint", "punch", "the punch list is walked on finished work", "la lista se recorre con el trabajo terminado"),
    _h("plumbing_finish", "punch", "", ""), _h("electrical_finish", "punch", "", ""),
    _h("hvac_finish", "punch", "", ""), _h("sprinkler_finish", "punch", "", ""),
    _h("low_voltage_finish", "punch", "", ""), _h("flooring", "punch", "", ""),
    # the building
    _h("roofing", "elevator", "the elevator needs a dry shaft and machine space", "el elevador necesita un cubo seco"),
    _h("elevator", "gate_elevator", "", ""),
    _h("low_voltage_finish", "gate_fire_alarm", "every device is in before the system is tested",
       "todos los dispositivos antes de probar el sistema"),
    _h("roof_mep", "hvac_finish", "units start up once the rooftop equipment is set",
       "el arranque requiere el equipo de azotea", rel="top"),
    _h("punch", "gate_final", "finals are called on finished floors", "las finales se piden con pisos terminados"),
    _h("gate_fire_alarm", "gate_final", "", ""), _h("gate_elevator", "gate_final", "", ""),
    _h("scaffold_down", "gate_final", "", ""), _h("roof_mep", "gate_final", "", ""),
    _h("gate_final", "tco", "", ""),
)


# ── THE NETWORK ──────────────────────────────────────────────────────────────

@dataclass
class Node:
    id: str
    key: str
    floor: Optional[int]
    days: float
    preds: List[Tuple[str, Link]] = field(default_factory=list)

    @property
    def act(self) -> Act:
        return ACT[self.key]


def nid(key: str, floor: Optional[int] = None) -> str:
    return key if floor is None else f"{key}@{floor}"


def _days(a: Act, s: Scope) -> float:
    if a.key in s.days:
        return float(s.days[a.key])
    d = a.days
    if a.cycle and s.cycle_days:
        mine = [x for x in ACTS if x.cycle and set(x.only) <= s.flags()]
        fixed = 2.0 if s.system == "cast_in_place" else 0.0          # the pour day and the day after it
        d = a.days * max(0.5, (s.cycle_days - fixed)) / sum(x.days for x in mine)
    if a.scales:
        d *= max(0.5, s.units_per_floor / BASE_UNITS)
    if a.x_floors:
        d *= s.floors
    return d


def network(scope: Scope) -> Dict[str, Node]:
    """Every activity of this building and what comes before each one."""
    if scope.system not in SYSTEMS:
        raise ValueError(f"unknown structural system {scope.system!r}; one of {SYSTEMS}")
    if scope.floors < 1:
        raise ValueError("a building has at least one floor")
    on = scope.flags()
    floors = list(range(1, scope.floors + 1))
    live = {a.key: a for a in ACTS if set(a.only) <= on}
    nodes: Dict[str, Node] = {}
    for a in live.values():
        for f in (floors if a.per == "floor" else [None]):
            nodes[nid(a.key, f)] = Node(nid(a.key, f), a.key, f, _days(a, scope))
    for ln in LINKS:
        if ln.a not in live or ln.b not in live:
            continue
        if ln.a == "pour_slab" and ln.b == "strip":
            ln = Link(ln.a, ln.b, ln.why, ln.es, ln.hard, ln.kind, float(scope.strip_days), ln.rel)
        pa, pb = live[ln.a].per, live[ln.b].per
        pairs: List[Tuple[Optional[int], Optional[int]]] = []
        if pa == "floor" and pb == "floor":
            pairs = [(f - 1, f) for f in floors[1:]] if ln.rel == "below" else [(f, f) for f in floors]
        elif pa == "floor":
            pairs = [(f, None) for f in ({"top": floors[-1:], "first": floors[:1]}.get(ln.rel, floors))]
        elif pb == "floor":
            pairs = [(None, f) for f in ({"top": floors[-1:], "first": floors[:1]}.get(ln.rel, floors))]
        else:
            pairs = [(None, None)]
        for fa, fb in pairs:
            nodes[nid(ln.b, fb)].preds.append((nid(ln.a, fa), ln))
    return nodes


_CREW = Link("", "", "one crew, floor after floor", "una cuadrilla, piso tras piso", False)


def _edges(nodes: Dict[str, Node], scope: Scope, *, hard_only: bool, crews: bool) -> Dict[str, List[Tuple[str, Link]]]:
    out = {k: [(p, ln) for p, ln in n.preds if ln.hard or not hard_only] for k, n in nodes.items()}
    if crews:
        for n in nodes.values():
            a = n.act
            if n.floor is None or not a.trade or a.gate:
                continue
            back = nid(n.key, n.floor - max(1, int(scope.crews.get(a.trade, 1))))
            if back in nodes:
                out[n.id].append((back, _CREW))
    return out


def _order(edges: Dict[str, List[Tuple[str, Link]]]) -> List[str]:
    deg = {k: len(v) for k, v in edges.items()}
    succ: Dict[str, List[str]] = defaultdict(list)
    for k, v in edges.items():
        for p, _ln in v:
            succ[p].append(k)
    ready = sorted(k for k, d in deg.items() if d == 0)
    out: List[str] = []
    while ready:
        k = ready.pop(0)
        out.append(k)
        for s in sorted(succ[k]):
            deg[s] -= 1
            if deg[s] == 0:
                ready.append(s)
    if len(out) != len(edges):
        raise ValueError("the rules contradict each other (a loop) among: "
                         + ", ".join(sorted(k for k, d in deg.items() if d > 0)[:8]))
    return out


def _forward(nodes, edges, order) -> Tuple[Dict[str, float], Dict[str, float], Dict[str, Optional[str]]]:
    es: Dict[str, float] = {}
    ef: Dict[str, float] = {}
    driver: Dict[str, Optional[str]] = {}
    for k in order:
        best, by = 0.0, None
        for p, ln in edges[k]:
            t = (es[p] if ln.kind == "SS" else ef[p]) + ln.lag
            if t > best or (by is None and t >= best):
                best, by = t, p
        es[k], ef[k], driver[k] = best, best + nodes[k].days, by
    return es, ef, driver


def _chain(driver: Dict[str, Optional[str]], last: str) -> List[str]:
    out = [last]
    while driver.get(out[-1]):
        out.append(driver[out[-1]])            # type: ignore[arg-type]
    return out[::-1]


def plan(scope: Scope) -> Dict[str, Any]:
    """The earliest schedule the logic allows, in working days from day 0.

      days        the length with one crew per trade moving floor to floor
      fastest     the length with HARD rules only and as many crews as floors:
                  below this the building cannot be built in this order
      chain       the activities that set the finish, first to last
      second_crew [{trade, days_saved}]: what a second crew of each trade buys
    """
    nodes = network(scope)

    def run(sc: Scope, **kw):
        e = _edges(nodes, sc, **kw)
        o = _order(e)
        return e, o, _forward(nodes, e, o)
    edges, order, (es, ef, driver) = run(scope, hard_only=False, crews=True)
    length = max(ef.values())
    _e2, _o2, (_s2, ef2, _d2) = run(scope, hard_only=True, crews=False)
    succ: Dict[str, List[Tuple[str, Link]]] = defaultdict(list)
    for k, v in edges.items():
        for p, ln in v:
            succ[p].append((k, ln))
    ls: Dict[str, float] = {}
    for k in reversed(order):
        lf = min([(ls[s] - ln.lag + (nodes[k].days if ln.kind == "SS" else 0.0)) for s, ln in succ[k]] or [length])
        ls[k] = lf - nodes[k].days
    last = max(order, key=lambda k: (ef[k], k))
    gains = []
    for trade in sorted({n.act.trade for n in nodes.values() if n.floor is not None and n.act.trade and not n.act.gate}):
        sc = Scope(**{**scope.__dict__, "crews": {**scope.crews, trade: int(scope.crews.get(trade, 1)) + 1}})
        saved = length - max(run(sc, hard_only=False, crews=True)[2][1].values())
        if saved > 0.01:
            gains.append({"trade": trade, "days_saved": round(saved, 1)})
    rows = [{"id": k, "key": nodes[k].key, "floor": nodes[k].floor, "label": nodes[k].act.label, "es": nodes[k].act.es,
             "trade": nodes[k].act.trade, "gate": nodes[k].act.gate, "days": round(nodes[k].days, 1),
             "start": round(es[k], 1), "finish": round(ef[k], 1), "float": round(ls[k] - es[k], 1),
             "critical": ls[k] - es[k] < 0.01, "driver": driver[k]} for k in order]
    rows.sort(key=lambda r: (r["start"], r["finish"], r["id"]))
    return {"days": round(length, 1), "fastest": round(max(ef2.values()), 1), "chain": _chain(driver, last),
            "second_crew": sorted(gains, key=lambda g: -g["days_saved"]), "nodes": rows}


# ── THE CALENDAR ─────────────────────────────────────────────────────────────

def workdays_from(start: date, n: int, closed: Iterable[date] = ()) -> List[date]:
    """The first `n` working days on or after `start`: weekdays, less federal
    holidays, less the site's own `closed` days."""
    shut = set(closed)
    out: List[date] = []
    d = start
    while len(out) < n:
        if d not in shut and report_calendar.working_days(d, d):
            out.append(d)
        d += timedelta(days=1)
    return out


def on_calendar(p: Dict[str, Any], start: date, closed: Iterable[date] = ()) -> Dict[str, Any]:
    """The plan with calendar dates: an activity that runs from working day
    4.0 to 6.5 starts on the fifth working day and finishes on the seventh."""
    cal = workdays_from(start, int(math.ceil(p["days"])) + 2, closed)
    rows = [{**r, "start_date": cal[int(math.floor(r["start"] + 1e-9))],
             "finish_date": cal[max(int(math.floor(r["start"] + 1e-9)), int(math.ceil(r["finish"] - 1e-9)) - 1)]}
            for r in p["nodes"]]
    return {**p, "nodes": rows, "start_date": start, "finish_date": max(r["finish_date"] for r in rows)}


# ── THE LOGS LAID OVER THE NETWORK ───────────────────────────────────────────
#
# A daily log is not a schedule update. Four readings keep it honest:
#   * a START is the first day followed by another within START_WINDOW worked
#     site days: one stray mention is not a trade starting;
#   * work logged on something proves what it PHYSICALLY stands on is behind it;
#   * a fixture or trim line on a floor whose walls are not being taped yet
#     is rough-in (a tub is set before the walls close);
#   * on a steel-stud building the crew writes "framing" for the bearing walls
#     and for the partitions alike: on each floor it is structure until the
#     framing first reaches the floor above, partitions after.

START_WINDOW = 5
#: Small work that trails its trade: a late start is not a wait.
_NO_WAIT = ("blocking", "firestopping")
_SPLIT = re.compile(r"\s*(?:,|;|/|\s\+\s|\s&\s|\band\b|\bthen\b)\s*", re.IGNORECASE)
_UNDER = re.compile(r"under.?ground|under.?slab|below.?slab", re.IGNORECASE)
_SAID_DONE = re.compile(r"\b(?:complete[d]?|done|finished|passed|approved)\b", re.IGNORECASE)
_ROUGH_OF = {"plumbing_finish": "plumbing_rough", "electrical_finish": "electrical_rough",
             "hvac_finish": "hvac_rough", "sprinkler_finish": "sprinkler_rough",
             "low_voltage_finish": "low_voltage_rough"}
_MEP = ("plumbing", "electrical", "hvac", "sprinkler", "low_voltage")


def _picker(scope: Scope):
    on = scope.flags()
    live = [a for a in ACTS if set(a.only) <= on]
    by: Dict[str, List[Act]] = defaultdict(list)
    for a in live:
        if a.family and not a.gate:
            by[a.family].append(a)
    gates = [a for a in live if a.gate and a.words]
    loose = [a for a in live if not a.gate and not a.family and a.words]
    structure = {"cfs": "framing"}.get(scope.system)

    def work(fam: str, phrase: str) -> Optional[str]:
        if fam in _MEP and _UNDER.search(phrase or ""):
            return "underground_plumbing"
        cands = by.get(fam, [])
        if fam == structure:                      # split by date afterwards, see _split_structure
            cands = [a for a in cands if not a.cycle]
        for a in cands:
            if a.words and re.search(a.words, phrase or "", re.IGNORECASE):
                return a.key
        plain = [a for a in cands if not a.words]
        if plain:
            return plain[0].key
        return "framing" if fam == structure else None

    def gate(tag: str) -> Optional[str]:
        for a in gates:
            if re.search(a.words, tag, re.IGNORECASE):
                return a.key
        return None

    def other(text: str) -> List[str]:
        return [a.key for a in loose if re.search(a.words, text, re.IGNORECASE)]
    return work, gate, other


def read_logs(scope: Scope, rows: Iterable[Dict[str, Any]], end: date) -> Dict[str, Dict[str, Any]]:
    """{node id: {first, start, last, dates, credit, said_done}} from the crew
    rows of the filed daily logs. `credit` is days of work: a row naming three
    floors gives each a third of a day. `start` is the sustained start."""
    work, gate, other = _picker(scope)
    nodes = network(scope)
    log: Dict[str, Dict[date, float]] = defaultdict(dict)
    said: Dict[str, date] = {}
    rows = [r for r in rows if isinstance(r.get("date"), date) and r["date"] <= end]
    for r in rows:
        d = r["date"]
        fl = [f for f in (r.get("floors") or PS.floors_of_text(r.get("where")) or PS.floors_of_text(r.get("work")))
              if 1 <= f <= scope.floors]
        crew = PS.crew_family(r.get("trade"), r.get("company")) or ""
        text = str(r.get("work") or "")
        hits: List[Tuple[str, str]] = []
        gated = set()
        for ph in [p for p in _SPLIT.split(text) if p.strip()]:
            g = gate(f"{PS._base(PS._strong(ph) or crew)}:{ph}")
            if g:
                hits.append((g, ph))
                gated.add(" ".join(ph.split()).strip(" .-").lower())
        for fam, ph in PS.families_of(r):
            if ph.lower() in gated:
                continue
            key = work(fam, ph)
            if key:
                hits.append((key, ph))
        hits += [(k, text) for k in other(f"{r.get('trade') or ''} {text}")]
        for key, ph in hits:
            spots = [None] if ACT[key].per == "job" else fl
            for f in spots:
                k = nid(key, f)
                if k not in nodes:
                    continue
                log[k][d] = max(log[k].get(d, 0.0), 1.0 / (len(spots) * max(1, len(hits))))
                if ACT[key].gate or _SAID_DONE.search(ph or ""):
                    said[k] = max(said.get(k, d), d)
    days = sorted({r["date"] for r in rows})
    idx = {d: n for n, d in enumerate(days)}
    _split_structure(scope, log, said)

    def sustained(ds: List[date]) -> date:
        for a, b in zip(ds, ds[1:]):
            if idx[b] - idx[a] <= START_WINDOW:
                return a
        return ds[0]
    board = {f: sustained(sorted(log[nid("taping", f)])) if log.get(nid("taping", f)) else None
             for f in range(1, scope.floors + 1)}
    for fin, rough in _ROUGH_OF.items():           # trim before the walls are taped is rough-in
        for f, b in board.items():
            src, dst = nid(fin, f), nid(rough, f)
            if src not in log or dst not in nodes:
                continue
            for d in [d for d in log[src] if b is None or d < b]:
                log[dst][d] = max(log[dst].get(d, 0.0), log[src].pop(d))
            if not log[src]:
                del log[src]
                said.pop(src, None)
    out: Dict[str, Dict[str, Any]] = {}
    for k, per_day in log.items():
        if not per_day:
            continue
        ds = sorted(per_day)
        out[k] = {"first": ds[0], "start": sustained(ds), "last": ds[-1], "dates": ds,
                  "credit": round(sum(per_day.values()), 2), "said_done": said.get(k)}
    return out


def _split_structure(scope: Scope, log: Dict[str, Dict[date, float]], said: Dict[str, date]) -> None:
    """Steel stud: framing on a floor before the framing reaches the floor
    above is the bearing structure; after that it is partitions."""
    if scope.system != "cfs":
        return
    pool = {f: dict(log.get(nid("framing", f), {})) for f in range(1, scope.floors + 1)}
    for f, per_day in pool.items():
        if not per_day:
            continue
        above = pool.get(f + 1) if f < scope.floors else log.get("roofing")
        until = min(above) if above else None
        for d, c in per_day.items():
            if until is None or d < until:
                log[nid("cfs_walls", f)][d] = c
                del log[nid("framing", f)][d]
        if not log[nid("framing", f)]:
            del log[nid("framing", f)]
            said.pop(nid("framing", f), None)


def site_days(rows: Iterable[Dict[str, Any]], end: date) -> List[date]:
    return sorted({r["date"] for r in rows if isinstance(r.get("date"), date) and r["date"] <= end})


def measured_cycle(scope: Scope, rows: Iterable[Dict[str, Any]], end: date) -> Dict[str, Any]:
    """The superstructure's real pace: worked site days between the structure
    first reaching one floor and first reaching the next. Read from FIRST
    appearances, so a line naming three floors at once does not blur it."""
    rows = list(rows)
    keys = [a.key for a in ACTS if (a.cycle or a.key == "pour_slab") and set(a.only) <= scope.flags()]
    act = read_logs(scope, rows, end)
    days = site_days(rows, end)
    first: Dict[int, date] = {}
    for f in range(1, scope.floors + 1):
        ds = [act[nid(k, f)]["first"] for k in keys if nid(k, f) in act]
        if ds:
            first[f] = min(ds)
    steps = [{"from": f, "to": f + 1, "days": sum(1 for d in days if first[f] <= d < first[f + 1])}
             for f in sorted(first) if f + 1 in first and first[f + 1] > first[f]]
    return {"reached": first, "steps": steps, "cycle": median([s["days"] for s in steps]) if steps else None}


def status(scope: Scope, rows: Iterable[Dict[str, Any]], end: date,
           closed: Iterable[date] = ()) -> Dict[str, Any]:
    """Where the job stands against its own logic on `end`.

      nodes         every activity: state none / active / idle / done, the days
                    logged, the work credited, what is left, forecast dates
      early         [{node, before, floors, kind}]: work that STARTED before
                    something it depends on by a hard rule. kind "never": the
                    earlier work is on no log. kind "still_open": it was still
                    being logged afterwards.
      not_on_record inspections and checks no log mentions, for work that has
                    started on the far side of them
      waited        worked site days between a floor being ready for a trade
                    and the trade starting there
      open_now      not started, with nothing the logic requires outstanding
      finish_date   the finish the REMAINING logic gives from `end` if the
                    durations hold; `chain` is what sets it

    A log is not an inspection record: `not_on_record` means the logs do not
    say it, not that it did not happen.
    """
    rows = [r for r in rows if isinstance(r.get("date"), date) and r["date"] <= end]
    nodes = network(scope)
    act = read_logs(scope, rows, end)
    days = site_days(rows, end)
    idx = {d: n for n, d in enumerate(days)}
    edges = _edges(nodes, scope, hard_only=False, crews=False)
    succ: Dict[str, List[Tuple[str, Link]]] = defaultdict(list)
    for k, v in edges.items():
        for p, ln in v:
            succ[p].append((k, ln))
    order = _order(edges)
    visible = {a.key for a in ACTS if a.family or a.words}       # what a log line can show at all

    state: Dict[str, str] = {}
    for k, a in act.items():
        if a["said_done"] and a["said_done"] >= a["last"]:
            state[k] = "done"
        elif len(days) - 1 - idx[a["last"]] < AWAY:
            state[k] = "active"
        else:
            followed = any(s in act and act[s]["last"] > a["last"] for s, _ln in succ[k])
            state[k] = "done" if followed and a["credit"] >= 0.5 * nodes[k].days else "idle"
    behind = set()                                       # proven behind us by what stands on it
    for k in reversed(order):
        if any(ln.kind == "FS" and (s in act or s in behind) and
               (ln.phys or (ln.hard and s in behind and not nodes[s].act.trade and not nodes[s].act.gate))
               for s, ln in succ[k]):
            behind.add(k)
            if state.get(k) != "active":
                state[k] = "done"
    for k in order:                                      # a milestone is reached when all before it is
        n = nodes[k]
        hard = [p for p, ln in n.preds if ln.hard]
        if k not in state and not n.act.trade and not n.act.gate and hard and all(state.get(p) == "done" for p in hard):
            state[k] = "done"
    for k in order:
        state.setdefault(k, "none")

    def before(k: str, hard_only: bool, seen=None) -> List[Tuple[str, Link]]:
        """What a node depends on, looking THROUGH checks and milestones no log records."""
        seen = seen if seen is not None else set()
        out: List[Tuple[str, Link]] = []
        for p, ln in nodes[k].preds:
            if (hard_only and not ln.hard) or p in seen:
                continue
            seen.add(p)
            if p in act or (nodes[p].act.trade and not nodes[p].act.gate):
                out.append((p, ln))
            elif p in behind or (hard_only and nodes[p].act.gate and not nodes[p].days):
                continue             # proven behind us; or a check, which is its own line in not_on_record
            else:
                out.extend((q, ln2 if ln2.why else ln) for q, ln2 in before(p, hard_only, seen))
        return out

    early: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    missing: Dict[Tuple[str, str], Dict[str, Any]] = {}
    waited: List[Dict[str, Any]] = []
    open_now: List[str] = []
    for k in order:
        n = nodes[k]
        b = act.get(k)
        if b and n.act.trade and not n.act.gate and len(b["dates"]) >= 2:
            for p, ln in before(k, True):
                if ln.kind == "SS" or ln.phys or nodes[p].key not in visible or nodes[p].act.gate:
                    continue             # a physical order cannot be broken: a "break" there is a misread line
                kind = None
                if p not in act:
                    kind = None if p in behind else "never"
                elif sum(1 for d in act[p]["dates"] if d > b["start"]) >= 2:
                    kind = "still_open"
                if kind:
                    e = early.setdefault((n.key, nodes[p].key, kind), {
                        "node": n.key, "before": nodes[p].key, "kind": kind, "floors": [], "date": b["start"],
                        "last": None, "why": ln.why, "why_es": ln.es})
                    e["floors"].append(n.floor)
                    e["date"] = min(e["date"], b["start"])
                    if p in act:
                        e["last"] = max(e["last"] or act[p]["last"], act[p]["last"])
            for p, ln in n.preds:
                if ln.hard and nodes[p].act.gate and p not in act:
                    m = missing.setdefault((n.key, nodes[p].key), {"node": n.key, "gate": nodes[p].key, "floors": [],
                                                                   "date": b["start"], "why": ln.why, "why_es": ln.es})
                    m["floors"].append(n.floor)
                    m["date"] = min(m["date"], b["start"])
            ready: List[Tuple[date, str]] = []
            for p, ln in before(k, False):
                if p in act and ln.kind == "SS":
                    ready.append((act[p]["start"], p))
                elif p in act and state[p] == "done":
                    ready.append((act[p]["last"], p))
                elif state[p] != "done":
                    ready = []
                    break
            if ready and max(ready)[0] < b["start"]:
                when, after = max(ready)
                gap = sum(1 for d in days if when < d < b["start"])
                if gap >= MIN_WAIT and n.key not in _NO_WAIT:
                    waited.append({"node": k, "key": n.key, "floor": n.floor, "ready": when, "started": b["start"],
                                   "days": gap, "after": after})
        elif state[k] == "none" and (n.act.trade or n.act.gate):
            hard = [p for p, ln in n.preds if ln.hard]
            if hard and all(state[p] == "done" for p in hard):
                open_now.append(k)

    # the remaining logic, from the day after `end`
    left: Dict[str, float] = {}
    for k in order:
        d = nodes[k].days
        left[k] = 0.0 if state[k] == "done" else d if k not in act else max(min(1.0, d), d - act[k]["credit"])
    fedges = _edges(nodes, scope, hard_only=False, crews=True)
    forder = _order(fedges)
    fs: Dict[str, float] = {}
    ff: Dict[str, float] = {}
    driver: Dict[str, Optional[str]] = {}
    for k in forder:
        if state[k] == "done":
            fs[k], ff[k], driver[k] = 0.0, 0.0, None
            continue
        going = state[k] in ("active", "idle")
        best, by = 0.0, None
        for p, ln in fedges[k]:
            if state[p] == "done" or (going and not ln.hard):
                continue
            if ln.kind == "SS":
                t = fs[p] + ln.lag if state[p] == "none" else 0.0
            else:
                t = ff[p] + ln.lag
            if going:
                t -= left[k]     # work under way keeps going; it cannot FINISH before what it hard-depends on
            if t > best:
                best, by = t, p
        fs[k], ff[k], driver[k] = best, best + left[k], by
    length = max(ff.values()) if ff else 0.0
    cal = workdays_from(end + timedelta(days=1), int(math.ceil(length)) + 2, closed)

    def day(x: float, finish: bool = False) -> date:
        i = int(math.ceil(x - 1e-9)) - 1 if finish else int(math.floor(x + 1e-9))
        return cal[max(0, i)]
    out_nodes = []
    for k in order:
        n, a = nodes[k], act.get(k)
        row = {"id": k, "key": n.key, "floor": n.floor, "label": n.act.label, "es": n.act.es, "trade": n.act.trade,
               "gate": n.act.gate, "state": state[k], "days": round(n.days, 1), "left": round(left[k], 1),
               "first": a["first"] if a else None, "start": a["start"] if a else None,
               "last": a["last"] if a else None, "credit": round(a["credit"], 1) if a else 0.0,
               "forecast_start": None, "forecast_finish": None}
        if state[k] != "done":
            row["forecast_start"] = day(fs[k]) if state[k] == "none" else None
            row["forecast_finish"] = day(ff[k], True) if left[k] else day(fs[k])
        out_nodes.append(row)
    last = max(forder, key=lambda k: (ff[k], k))
    real = [k for k in order if nodes[k].act.trade or nodes[k].act.gate]
    for e in list(early.values()) + list(missing.values()):
        e["floors"] = sorted(f for f in e["floors"] if f is not None)
    return {"as_of": end, "nodes": out_nodes,
            "early": sorted(early.values(), key=lambda e: (e["date"], e["node"], e["before"])),
            "not_on_record": sorted(missing.values(), key=lambda e: (e["date"], e["node"], e["gate"])),
            "waited": sorted(waited, key=lambda w: -w["days"]), "open_now": open_now,
            "days_left": round(length, 1), "finish_date": day(length, True) if length else end,
            "chain": [k for k in _chain(driver, last) if state[k] != "done"],
            "done": sum(1 for k in real if state[k] == "done"), "of": len(real)}


# ── IN WORDS ─────────────────────────────────────────────────────────────────

def name(node_id: str, es: bool = False) -> str:
    key, _, fl = node_id.partition("@")
    a = ACT[key]
    lab = a.es if es else a.label
    return f"{lab}, {'piso' if es else 'floor'} {fl}" if fl else lab


def _d(d: date, es: bool = False) -> str:
    months = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")
    return f"{d.day} {months[d.month - 1]}" if es else f"{d:%b} {d.day}"


def _floors(fl: List[int], es: bool = False) -> str:
    if not fl:
        return ""
    word = ("piso" if es else "floor") + ("s" if len(fl) > 1 else "")
    runs: List[List[int]] = []
    for f in fl:
        if runs and f == runs[-1][-1] + 1:
            runs[-1].append(f)
        else:
            runs.append([f])
    return f" ({word} " + ", ".join(str(r[0]) if len(r) == 1 else f"{r[0]}-{r[-1]}" for r in runs) + ")"


def findings(st: Dict[str, Any], es: bool = False) -> Dict[str, List[str]]:
    """The status as sentences a superintendent can check against the logs.
    Counts and dates only: no sentence says why something happened."""
    out: Dict[str, List[str]] = {"early": [], "not_on_record": [], "waited": [], "open_now": []}
    for e in st["early"]:
        b, a, fl = ACT[e["node"]], ACT[e["before"]], _floors(e["floors"], es)
        why = e["why_es"] if es else e["why"]
        if e["kind"] == "never":
            out["early"].append(
                (f"{b.es}{fl} empezó el {_d(e['date'], True)}; ningún parte registra: {a.es}. Regla: {why}." if es else
                 f"{b.label}{fl} started {_d(e['date'])}; no log shows any: {a.label}. Rule: {why}."))
        else:
            out["early"].append(
                (f"{b.es}{fl} empezó el {_d(e['date'], True)} mientras seguía registrándose: {a.es} "
                 f"(hasta el {_d(e['last'], True)}). Regla: {why}." if es else
                 f"{b.label}{fl} started {_d(e['date'])} while this was still being logged there: {a.label} "
                 f"(to {_d(e['last'])}). Rule: {why}."))
    by_gate: Dict[str, Dict[str, Any]] = {}
    for m in st["not_on_record"]:
        g = by_gate.setdefault(m["gate"], {"floors": set(), "nodes": []})
        g["floors"].update(m["floors"])
        g["nodes"].append(m["node"])
    for gate, g in by_gate.items():
        a, fl = ACT[gate], _floors(sorted(g["floors"]), es)
        what = ", ".join(dict.fromkeys((ACT[k].es if es else ACT[k].label) for k in g["nodes"]))
        out["not_on_record"].append(
            (f"{a.es}{fl}: ningún parte lo menciona, y ya empezó: {what}." if es else
             f"{a.label}{fl}: no log mentions it, and this has started: {what}."))
    for w in st["waited"]:
        out["waited"].append(
            (f"{name(w['node'], True)}: empezó el {_d(w['started'], True)}, {w['days']} días trabajados después de "
             f"estar listo ({ACT[w['after'].partition('@')[0]].es}, {_d(w['ready'], True)})." if es else
             f"{name(w['node'])}: started {_d(w['started'])}, {w['days']} worked site days after the floor was ready "
             f"for it ({ACT[w['after'].partition('@')[0]].label}, {_d(w['ready'])})."))
    out["open_now"] = [name(k, es) for k in st["open_now"]]
    return out
