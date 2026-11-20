"""Bulk import of sensor records, parts and calibrations (R2.5.1, R3.7), for loading what the station already knows.

`simola import-records <file.json> --actor <name>` takes a JSON document:

    {"components": [{"site": "04", "type": "ATRH", "installed_on": "2025-12-23",
                     "parts": [{"role": "Thermohygrometer", "model": "5190-F", "serial_number": "..."},
                               {"role": "MARS", "serial_number": "..."}]}, ...],
     "calibrations": [{"site": "04", "type": "ATRH", "date": "2025-12-27", "performed_by": "...",
                       "interval_months": 12, "validated_on": "2025-12-31", "notes": "...",
                       "part": "Thermohygrometer"}, ...]}

- A component entry changes only the record fields it names; the others stay as they are.
- A part entry updates the installed part of that name (the fields it names), or adds it when the sensor has none.
  Replacements are made in the screens, where the old part's removal date is asked for. The older form, with
  ``manufacturer``, ``model``, ``part_number``, ``serial_number`` and ``firmware`` on the component itself, still
  works: those fields go to the sensor's main part (``records.MAIN_PART``).
- A calibration's ``part`` names one of the sensor's installed parts (after the parts above are written).
- A calibration is added unless the sensor already has one (not removed) on the same date, so a second run of the
  same file adds nothing.
- Everything is checked first, with the same rules as the Admin screens; one refusal stops the whole import and
  nothing is written. Every change is audited under ``actor``, like a change made in the screens.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from simola import records
from simola.registry import Component, System


def _blank(v: Any) -> Any:
    if isinstance(v, str):
        return v.strip() or None
    return v


class _Entry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    site: str
    type: str

    @field_validator("*", mode="before")
    @classmethod
    def _strip(cls, v: Any) -> Any:
        return _blank(v)


class PartEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str = Field(min_length=1, max_length=60)
    manufacturer: str | None = Field(None, max_length=100)
    model: str | None = Field(None, max_length=100)
    part_number: str | None = Field(None, max_length=100)
    serial_number: str | None = Field(None, max_length=100)
    firmware: str | None = Field(None, max_length=100)
    installed_on: dt.date | None = None
    notes: str | None = Field(None, max_length=500)

    @field_validator("*", mode="before")
    @classmethod
    def _strip(cls, v: Any) -> Any:
        return _blank(v)


LEGACY_PART_FIELDS = ("manufacturer", "model", "part_number", "serial_number", "firmware")


class ComponentEntry(_Entry):
    sensor_type: str | None = Field(None, max_length=100)
    installed_on: dt.date | None = None
    notes: str | None = Field(None, max_length=500)
    parts: list[PartEntry] = []
    # the older form: these describe the sensor's main part
    manufacturer: str | None = Field(None, max_length=100)
    model: str | None = Field(None, max_length=100)
    part_number: str | None = Field(None, max_length=100)
    serial_number: str | None = Field(None, max_length=100)
    firmware: str | None = Field(None, max_length=100)


class CalibrationEntry(_Entry):
    date: dt.date
    performed_by: str | None = Field(None, max_length=100)
    certificate: str | None = Field(None, max_length=100)
    next_due: dt.date | None = None
    interval_months: int | None = None
    validated_on: dt.date | None = None
    notes: str | None = Field(None, max_length=500)
    part: str | None = Field(None, max_length=60)  # an installed part's name


class ImportDoc(BaseModel):
    model_config = ConfigDict(extra="forbid")

    components: list[ComponentEntry] = []
    calibrations: list[CalibrationEntry] = []


class ImportRefused(ValueError):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def where_of(system: System, comp: Component) -> str:
    return records.where(system, comp)


def _find(system: System, site: str, type_: str) -> Component | None:
    s = system.site_by_slug(site)
    return next((c for c in s.components if c.type_code == type_), None) if s else None


async def run_import(
    conn: AsyncConnection, system: System, doc: ImportDoc, *, actor: str, today: dt.date
) -> dict[str, int]:
    """Checks every entry, then writes. Raises ImportRefused (nothing written) when any entry is refused."""
    problems: list[str] = []
    metas: list[tuple[Component, dict[str, Any]]] = []
    part_entries: list[tuple[Component, dict[str, Any]]] = []
    for e in doc.components:
        comp = _find(system, e.site, e.type)
        if comp is None:
            problems.append(f"components {e.site}:{e.type}: unknown component")
            continue
        given = {k: getattr(e, k) for k in e.model_fields_set if k in records.COMPONENT_FIELDS}
        entries = [
            {
                "role": " ".join(pe.role.split()),
                **{k: getattr(pe, k) for k in pe.model_fields_set if k != "role"},
            }
            for pe in e.parts
        ]
        legacy = {k: getattr(e, k) for k in e.model_fields_set if k in LEGACY_PART_FIELDS}
        if legacy:
            entries.insert(0, {"role": records.MAIN_PART.get(comp.type_code, comp.type_code), **legacy})
        try:
            records.check_installed(given.get("installed_on"), today)
            for pe in entries:
                records.check_installed(pe.get("installed_on"), today)
        except records.RecordError as exc:
            problems.append(f"components {e.site}:{e.type}: {exc.code}")
            continue
        metas.append((comp, given))
        part_entries += [(comp, pe) for pe in entries]
    cals: list[tuple[Component, dict[str, Any]]] = []
    for ce in doc.calibrations:
        comp = _find(system, ce.site, ce.type)
        where = f"calibrations {ce.site}:{ce.type} {ce.date}"
        if comp is None:
            problems.append(f"{where}: unknown component")
            continue
        if comp.is_dcp:
            problems.append(f"{where}: dcp_not_calibrated")
            continue
        d = ce.model_dump(exclude={"site", "type", "part"})
        d["part_role"] = ce.part
        try:
            d["next_due"] = records.check_calibration(
                ce.date, ce.performed_by, ce.next_due, ce.interval_months, today, ce.validated_on
            )
        except records.RecordError as exc:
            problems.append(f"{where}: {exc.code}")
            continue
        cals.append((comp, d))
    if problems:
        raise ImportRefused(problems)

    out = {
        "components_changed": 0,
        "components_unchanged": 0,
        "parts_added": 0,
        "parts_changed": 0,
        "parts_unchanged": 0,
        "calibrations_added": 0,
        "calibrations_skipped": 0,
    }
    current = await records.component_meta(conn, [c.id for c, _ in metas])
    for comp, given in metas:
        await conn.execute(text("SELECT id FROM component WHERE id = :id FOR UPDATE"), {"id": comp.id})
        new = {**current[comp.id], **given}
        if new == current[comp.id]:
            out["components_unchanged"] += 1
            continue
        current[comp.id] = await records.save_component_meta(conn, system, comp, new, actor=actor)
        out["components_changed"] += 1
    for comp, pe in part_entries:
        await conn.execute(text("SELECT id FROM component WHERE id = :id FOR UPDATE"), {"id": comp.id})
        installed = (await records.parts_of(conn, [comp.id]))[comp.id]
        same = next((p for p in installed if records.same_part_name(p["role"], pe["role"])), None)
        if same is None:
            await records.add_part(
                conn, system, comp, {k: pe.get(k) for k in records.PART_FIELDS}, actor=actor
            )
            out["parts_added"] += 1
            continue
        new = {**{k: same[k] for k in records.PART_FIELDS}, **pe, "role": same["role"]}
        if new == {k: same[k] for k in records.PART_FIELDS}:
            out["parts_unchanged"] += 1
            continue
        await records.update_part(conn, system, comp, same, new, actor=actor)
        out["parts_changed"] += 1
    for comp, d in cals:
        role = d.pop("part_role")
        d["part_id"] = None
        if role:
            installed = (await records.parts_of(conn, [comp.id]))[comp.id]
            match = next((p for p in installed if records.same_part_name(p["role"], role)), None)
            if match is None:
                raise ImportRefused(
                    [f"calibrations {where_of(system, comp)} {d['date']}: part_not_installed"]
                )
            d["part_id"] = match["id"]
        exists = await conn.scalar(
            text("""
            SELECT 1 FROM calibration_record WHERE component_id = :c AND date = :d AND removed_at IS NULL LIMIT 1
        """),
            {"c": comp.id, "d": d["date"]},
        )
        if exists:
            out["calibrations_skipped"] += 1
            continue
        await records.add_calibration(conn, system, comp, d, actor=actor)
        out["calibrations_added"] += 1
    return out
