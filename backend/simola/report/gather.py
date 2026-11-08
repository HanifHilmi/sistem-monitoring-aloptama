"""The monthly report's data: one UTC month of a system, read with the functions behind the dashboard's routes.

Every part is what the dashboard shows for the same month (FR-EXP-001: "every figure equals the dashboard"):
``/kpis``, ``/matrix`` by day, ``/outages`` for ``ola`` and ``sla``, ``/data-quality`` as a signed-in user, the
alarm history's counts, and the calibration status as it stood on the month's last day (today, while the month
is still running), so a past month's report comes out the same whenever it is made.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncConnection

from simola import alarms, records
from simola.api.routers import public
from simola.core.timeutil import day_start
from simola.kpi import outages, quality
from simola.registry import System
from simola.report.model import TOP_OUTAGES, ReportInputs, next_month
from simola.report.texts import Lang


def month_period(month: date) -> tuple[datetime, datetime]:
    return day_start(month), day_start(next_month(month))


async def gather(
    conn: AsyncConnection, system: System, month: date, lang: Lang, generated_by: str, now: datetime
) -> ReportInputs:
    start, end = month_period(month)
    last_day = min(next_month(month) - timedelta(days=1), now.date())
    display = await public.display_view(conn)
    return ReportInputs(
        system=public.registry_view(system),
        station=await records.station_meta(conn, system),
        month=month,
        lang=lang,
        generated_at=now,
        generated_by=generated_by,
        definitions=await public.definitions_view(conn),
        thresholds=display["color_thresholds"],
        kpis=await public.kpis_view(conn, system, start, end, now),
        matrix=await public.matrix_view(conn, system, start, end, now, "day"),
        outages=await outages.outage_report(conn, system, "ola", start, end, now, TOP_OUTAGES),
        sla_outages=await outages.outage_report(conn, system, "sla", start, end, now, 1),
        alarms=await alarms.month_summary(conn, system, start, end),
        quality=await quality.summary(conn, system, start, end, now, signed_in=True),
        calibration=await records.calibration_on(conn, system, last_day),
    )
