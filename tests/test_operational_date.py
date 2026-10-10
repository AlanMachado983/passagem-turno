"""Regressões de data operacional sem abrir Streamlit ou acessar o banco."""
import ast
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
import unittest
from zoneinfo import ZoneInfo

SOURCE = Path(__file__).resolve().parents[1] / 'app.py'
TREE = ast.parse(SOURCE.read_text(encoding='utf-8'))
NAMES = {'FUSO_OPERACIONAL', 'HORARIOS_TURNOS', 'agora_operacional',
         'sugerir_data_operacional', 'PgCursor'}
nodes = [
    node for node in TREE.body
    if (isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in NAMES)
    or (isinstance(node, ast.Assign) and any(
        isinstance(target, ast.Name) and target.id in NAMES for target in node.targets))
]
scope = dict(datetime=datetime, date=date, timedelta=timedelta, ZoneInfo=ZoneInfo)
exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), 'exec'), scope)
suggest = scope['sugerir_data_operacional']
TZ = scope['FUSO_OPERACIONAL']

class OperationalDateTests(unittest.TestCase):
    def test_shift_boundaries_and_late_handoffs(self):
        cases = [
            ('T1', '00:00', 10), ('T1', '06:00', 10),
            ('T2', '00:00', 9), ('T2', '06:18', 9),
            ('T2', '14:19', 9), ('T2', '14:20', 10),
            ('T2', '22:35', 10), ('T2', '22:53', 10),
            ('T2', '23:59', 10),
            ('T3', '00:00', 9), ('T3', '06:17', 9),
            ('T3', '06:18', 9), ('T3', '06:19', 9),
            ('T3', '22:34', 9), ('T3', '22:35', 10),
            ('T3', '23:59', 10), ('2X2 2A', '00:00', 10),
        ]
        for shift, clock, day in cases:
            with self.subTest(shift=shift, clock=clock):
                instant = datetime.fromisoformat('2026-10-10T' + clock).replace(tzinfo=TZ)
                self.assertEqual(suggest(shift, instant), date(2026, 10, day))

    def test_utc_server_is_converted_before_selecting_date(self):
        for shift in ['T2', 'T3']:
            self.assertEqual(suggest(shift, datetime(2026, 10, 10, 2, tzinfo=timezone.utc)),
                             date(2026, 10, 9))
            self.assertEqual(suggest(shift, datetime(2026, 10, 10, 3, tzinfo=timezone.utc)),
                             date(2026, 10, 9))

    def test_month_year_and_leap_day(self):
        for stamp, expected in [
            ('2027-01-01T00:10', date(2026, 12, 31)),
            ('2026-11-01T06:18', date(2026, 10, 31)),
            ('2028-03-01T06:18', date(2028, 2, 29)),
        ]:
            for shift in ['T2', 'T3']:
                self.assertEqual(suggest(shift, datetime.fromisoformat(stamp).replace(tzinfo=TZ)),
                                 expected)

    def test_registration_keeps_actual_instant_and_offset(self):
        instant = scope['agora_operacional']()
        self.assertEqual(instant.tzinfo, TZ)
        self.assertTrue(instant.isoformat(timespec='seconds').endswith('-03:00'))

    def test_duplicate_cda02_does_not_overwrite_history(self):
        inserts = [n.value for n in ast.walk(TREE)
                   if isinstance(n, ast.Constant) and isinstance(n.value, str)
                   and n.value.startswith('INSERT INTO passagens(')]
        self.assertEqual(len(inserts), 1)
        self.assertIn("ON CONFLICT (data,area,operacao,turno) WHERE operacao='CDA 02' DO NOTHING",
                      inserts[0])
        self.assertNotIn('DO UPDATE', inserts[0])
        class Cursor:
            def execute(self, sql, params): self.sql = sql
            def fetchone(self): return None
        cursor = Cursor()
        wrapped = scope['PgCursor'](cursor)
        wrapped.execute(inserts[0])
        self.assertIsNone(wrapped.lastrowid)
        self.assertTrue(cursor.sql.endswith(' RETURNING id'))
        cursor.fetchone = lambda: (123,)
        wrapped.execute(inserts[0])
        self.assertEqual(wrapped.lastrowid, 123)

    def test_no_automatic_historical_date_migration(self):
        automatic = ast.Module(body=[n for n in TREE.body
                                     if not (isinstance(n, ast.FunctionDef)
                                             and n.name == 'salvar_edicao_historico')], type_ignores=[])
        sqls = [n.value.upper() for n in ast.walk(automatic)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        self.assertFalse(any('UPDATE PASSAGENS' in sql or 'ALTER TABLE PASSAGENS' in sql
                             for sql in sqls))

if __name__ == '__main__':
    unittest.main()
