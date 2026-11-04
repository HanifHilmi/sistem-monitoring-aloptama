"""Registry snapshot loaded from the database (FR-REG-001). Business logic takes its lists from here."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


@dataclass(frozen=True)
class MetricField:
    code: str
    column: str
    value_type: str
    unit: str | None
    name_en: str
    name_id: str
    sort: int

    @property
    def is_text(self) -> bool:
        return self.value_type == "text"


@dataclass(frozen=True)
class Cdp:
    id: int
    code: str
    preference: int


@dataclass(frozen=True)
class Component:
    id: int
    site_id: int
    type_code: str
    is_dcp: bool
    name_en: str
    name_id: str
    sort: int
    fields: tuple[str, ...]  # field codes reported by this component at its site
    mandatory: tuple[str, ...]  # subset of fields that must be valid (FR-REG-003)
    in_service_from: datetime | None
    in_service_to: datetime | None


@dataclass(frozen=True)
class Site:
    id: int
    code: str
    station_code: str
    slug: str
    name_en: str
    name_id: str
    sort: int
    components: tuple[Component, ...]

    @property
    def sensor_components(self) -> tuple[Component, ...]:
        return tuple(c for c in self.components if not c.is_dcp)

    @property
    def dcp(self) -> Component | None:
        return next((c for c in self.components if c.is_dcp), None)


@dataclass(frozen=True)
class System:
    id: int
    code: str
    type_code: str
    kpi_profile: str
    name_en: str
    name_id: str
    icao: str | None
    coverage_start: datetime
    cdps: tuple[Cdp, ...]
    sites: tuple[Site, ...]
    fields: dict[str, MetricField] = field(default_factory=dict)

    def site_by_slug(self, slug: str) -> Site | None:
        return next((s for s in self.sites if s.slug == slug), None)

    def site_by_station(self, station: str) -> Site | None:
        return next((s for s in self.sites if s.station_code == station), None)

    def cdp_by_code(self, code: str) -> Cdp | None:
        return next((c for c in self.cdps if c.code == code), None)

    def column(self, field_code: str) -> str:
        return self.fields[field_code].column

    def site_field_columns(self, site: Site) -> list[str]:
        """All non-DCP field columns at a site (used by the DCP rule)."""
        cols: list[str] = []
        for comp in site.sensor_components:
            for f in comp.fields:
                col = self.column(f)
                if col not in cols:
                    cols.append(col)
        return cols


async def load_systems(conn: AsyncConnection) -> list[System]:
    systems = (
        (
            await conn.execute(
                text(
                    """
        SELECT s.id, s.code, s.type_code, t.kpi_profile, s.name_en, s.name_id, s.icao, s.coverage_start
        FROM system s JOIN system_type t ON t.code = s.type_code ORDER BY s.sort, s.id
        """
                )
            )
        )
        .mappings()
        .all()
    )
    out: list[System] = []
    for sy in systems:
        fields = {
            r["code"]: MetricField(
                r["code"], r["column_name"], r["value_type"], r["unit"], r["name_en"], r["name_id"], r["sort"]
            )
            for r in (
                await conn.execute(
                    text("SELECT * FROM metric_field WHERE system_type_code = :t ORDER BY sort"),
                    {"t": sy["type_code"]},
                )
            ).mappings()
        }
        mandatory: dict[str, set[str]] = {}
        for r in (
            await conn.execute(
                text(
                    "SELECT component_type_code, field_code FROM mandatory_field WHERE system_type_code = :t"
                ),
                {"t": sy["type_code"]},
            )
        ).mappings():
            mandatory.setdefault(r["component_type_code"], set()).add(r["field_code"])
        cdps = tuple(
            Cdp(r["id"], r["code"], r["preference"])
            for r in (
                await conn.execute(
                    text(
                        "SELECT id, code, preference FROM cdp_node WHERE system_id = :s ORDER BY preference"
                    ),
                    {"s": sy["id"]},
                )
            ).mappings()
        )
        comp_rows = (
            (
                await conn.execute(
                    text(
                        """
            SELECT c.id, c.site_id, c.type_code, ct.is_dcp, ct.name_en, ct.name_id, c.sort,
                   c.in_service_from, c.in_service_to,
                   coalesce(array_agg(cf.field_code) FILTER (WHERE cf.field_code IS NOT NULL), '{}') AS fields
            FROM component c
            JOIN component_type ct ON ct.code = c.type_code
            JOIN site st ON st.id = c.site_id
            LEFT JOIN component_field cf ON cf.component_id = c.id
            WHERE st.system_id = :s
            GROUP BY c.id, ct.is_dcp, ct.name_en, ct.name_id
            ORDER BY c.site_id, c.sort
            """
                    ),
                    {"s": sy["id"]},
                )
            )
            .mappings()
            .all()
        )
        comps_by_site: dict[int, list[Component]] = {}
        for r in comp_rows:
            flds = tuple(sorted(r["fields"], key=lambda f: fields[f].sort))
            mand = tuple(f for f in flds if f in mandatory.get(r["type_code"], set()))
            if not r["is_dcp"] and not mand:
                # Never let a component without mandatory fields silently count as always valid.
                raise ValueError(f"component {r['id']} ({r['type_code']}) has no mandatory field at its site")
            comps_by_site.setdefault(r["site_id"], []).append(
                Component(
                    r["id"],
                    r["site_id"],
                    r["type_code"],
                    r["is_dcp"],
                    r["name_en"],
                    r["name_id"],
                    r["sort"],
                    flds,
                    mand,
                    r["in_service_from"],
                    r["in_service_to"],
                )
            )
        sites = tuple(
            Site(
                r["id"],
                r["code"],
                r["station_code"],
                r["slug"],
                r["name_en"],
                r["name_id"],
                r["sort"],
                tuple(comps_by_site.get(r["id"], [])),
            )
            for r in (
                await conn.execute(
                    text("SELECT * FROM site WHERE system_id = :s ORDER BY sort, id"), {"s": sy["id"]}
                )
            ).mappings()
        )
        out.append(
            System(
                sy["id"],
                sy["code"],
                sy["type_code"],
                sy["kpi_profile"],
                sy["name_en"],
                sy["name_id"],
                sy["icao"],
                sy["coverage_start"],
                cdps,
                sites,
                fields,
            )
        )
    return out


async def load_system(conn: AsyncConnection, code: str) -> System | None:
    return next((s for s in await load_systems(conn) if s.code == code), None)


async def get_setting(conn: AsyncConnection, key: str, default: Any = None) -> Any:
    row = (await conn.execute(text("SELECT value FROM setting WHERE key = :k"), {"k": key})).first()
    if row is None:
        return default
    value = row[0]
    return json.loads(value) if isinstance(value, str) else value
