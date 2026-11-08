"""Monthly PDF report (R3.5, FR-EXP-001): one UTC month of a system, in Bahasa Indonesia or English.

The report reads the same answers the dashboard reads (KPIs, the day matrix, the outage list, the data-quality
summary, calibration status) and lays them out with an HTML template that WeasyPrint turns into a PDF, so every
figure in it is the dashboard's figure for the month.

    texts.py    the words, in both languages, and how numbers and dates are written
    charts.py   the daily SLA/OLA chart and the alarms-per-day chart, drawn as SVG
    model.py    what goes on each page, built from the dashboard's answers
    render.py   HTML from the template, then the PDF; only the bundled fonts are ever loaded
"""
