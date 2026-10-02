import os
import sys
import unittest
from datetime import date, datetime, timedelta

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from time_utils import (
    local_day_bounds_utc,
    local_month_bounds_utc,
    local_to_utc,
    local_week_bounds_utc,
    now_local,
    today_local,
)


class PragueMidnightTestCase(unittest.TestCase):
    def test_today_switches_at_prague_midnight_not_utc_midnight(self):
        # CEST = UTC+2 → pražská půlnoc 1. 10. je 30. 9. 22:00 UTC.
        self.assertEqual(today_local(datetime(2026, 9, 30, 21, 59)), date(2026, 9, 30))
        self.assertEqual(today_local(datetime(2026, 9, 30, 22, 0)), date(2026, 10, 1))
        self.assertEqual(today_local(datetime(2026, 9, 30, 22, 30)), date(2026, 10, 1))

    def test_day_bounds_are_prague_midnights_in_utc(self):
        self.assertEqual(
            local_day_bounds_utc(date(2026, 10, 2)),
            (datetime(2026, 10, 1, 22, 0), datetime(2026, 10, 2, 22, 0)),
        )
        # zima (CET = UTC+1)
        self.assertEqual(
            local_day_bounds_utc(date(2026, 12, 2)),
            (datetime(2026, 12, 1, 23, 0), datetime(2026, 12, 2, 23, 0)),
        )

    def test_local_to_utc_round_trip(self):
        local_naive = datetime(2026, 10, 3, 18, 0)
        utc = local_to_utc(local_naive)
        self.assertEqual(utc, datetime(2026, 10, 3, 16, 0))
        self.assertEqual(now_local(utc).replace(tzinfo=None), local_naive)


class DstTransitionTestCase(unittest.TestCase):
    def test_march_transition_day_has_23_hours(self):
        # 29. 3. 2026: 02:00 CET → 03:00 CEST
        start, end = local_day_bounds_utc(date(2026, 3, 29))
        self.assertEqual(start, datetime(2026, 3, 28, 23, 0))
        self.assertEqual(end, datetime(2026, 3, 29, 22, 0))
        self.assertEqual(end - start, timedelta(hours=23))

        before = now_local(datetime(2026, 3, 29, 0, 59))
        after = now_local(datetime(2026, 3, 29, 1, 0))
        self.assertEqual((before.hour, before.minute, before.tzname()), (1, 59, "CET"))
        self.assertEqual((after.hour, after.minute, after.tzname()), (3, 0, "CEST"))

    def test_october_transition_day_has_25_hours(self):
        # 25. 10. 2026: 03:00 CEST → 02:00 CET (hodina 02:xx nastane dvakrát)
        start, end = local_day_bounds_utc(date(2026, 10, 25))
        self.assertEqual(start, datetime(2026, 10, 24, 22, 0))
        self.assertEqual(end, datetime(2026, 10, 25, 23, 0))
        self.assertEqual(end - start, timedelta(hours=25))

        first = now_local(datetime(2026, 10, 25, 0, 30))
        second = now_local(datetime(2026, 10, 25, 1, 30))
        self.assertEqual((first.hour, first.minute, first.tzname()), (2, 30, "CEST"))
        self.assertEqual((second.hour, second.minute, second.tzname()), (2, 30, "CET"))

    def test_week_bounds_across_october_transition(self):
        # týden 19.–25. 10. 2026 začíná v CEST a končí v CET → 7 dní + 1 h
        start, end = local_week_bounds_utc(date(2026, 10, 21))
        self.assertEqual(start, datetime(2026, 10, 18, 22, 0))
        self.assertEqual(end, datetime(2026, 10, 25, 23, 0))
        self.assertEqual(end - start, timedelta(days=7, hours=1))

    def test_week_starts_monday(self):
        start, end = local_week_bounds_utc(date(2026, 11, 1))  # neděle
        self.assertEqual(start, datetime(2026, 10, 25, 23, 0))  # po 26. 10. 00:00 CET
        self.assertEqual(end, datetime(2026, 11, 1, 23, 0))

    def test_month_bounds_across_october_transition_and_year_end(self):
        self.assertEqual(
            local_month_bounds_utc(date(2026, 10, 15)),
            (datetime(2026, 9, 30, 22, 0), datetime(2026, 10, 31, 23, 0)),
        )
        self.assertEqual(
            local_month_bounds_utc(date(2026, 12, 31)),
            (datetime(2026, 11, 30, 23, 0), datetime(2026, 12, 31, 23, 0)),
        )


if __name__ == "__main__":
    unittest.main()
