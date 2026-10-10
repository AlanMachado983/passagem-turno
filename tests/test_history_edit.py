import ast
import json
from pathlib import Path
import unittest
from datetime import datetime, timezone

tree=ast.parse((Path(__file__).resolve().parents[1]/'app.py').read_text(encoding='utf-8'))
node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='salvar_edicao_historico')

class FakeConnection:
    def __init__(self, original, conflict=False, fail=False):
        self.original=original; self.conflict=conflict; self.fail=fail
        self.calls=[]; self.committed=False; self.rolled_back=False; self.closed=False
    def cursor(self): return self
    def execute(self, sql, params=()):
        self.calls.append((sql,params))
        if self.fail and sql.startswith('UPDATE passagens'):
            raise RuntimeError('write failed')
    def fetchone(self):
        return (json.dumps(self.original),) if self.calls[-1][0].startswith('SELECT to_jsonb') else ((99,) if self.conflict else None)
    def commit(self): self.committed=True
    def rollback(self): self.rolled_back=True
    def close(self): self.closed=True

class HistoryEditTests(unittest.TestCase):
    def setUp(self):
        self.original={'id':1,'data':'2026-10-10','turno':'T3','operacao':'CDA 02','area':'CDA 02','criado_em':'2026-10-10T06:20:00'}
        self.changes={'data':'2026-10-09','turno':'T3','responsavel':'Alan','ofensor':'Sem ofensor','observacoes':'Corrigido','status':'🟢 Normal'}
    def save(self, connection, original=None, changes=None):
        scope={'conn':lambda:connection,'agora_operacional':lambda:datetime.now(timezone.utc)}
        exec(compile(ast.Module(body=[node],type_ignores=[]),'<edit>','exec'),scope)
        scope['salvar_edicao_historico'](1,original or self.original, changes or self.changes,'Alan','Correção de data')
    def test_audit_and_edit_are_atomic_and_timestamp_is_preserved(self):
        c=FakeConnection(self.original)
        self.save(c)
        audit=next(params for sql,params in c.calls if sql.startswith('INSERT INTO passagens_revisoes'))
        self.assertEqual(json.loads(audit[4]),self.original)
        self.assertEqual(json.loads(audit[5]),self.changes)
        update=next(sql for sql,params in c.calls if sql.startswith('UPDATE passagens'))
        self.assertNotIn('criado_em',update)
        self.assertTrue(c.committed and c.closed)
    def test_conflicting_destination_does_not_write(self):
        c=FakeConnection(self.original,conflict=True)
        with self.assertRaises(ValueError): self.save(c)
        self.assertFalse(any(sql.startswith('UPDATE') or sql.startswith('INSERT') for sql,p in c.calls))
        self.assertTrue(c.rolled_back and c.closed)
    def test_concurrent_edit_is_rejected(self):
        c=FakeConnection(dict(self.original,data='2026-10-08'))
        with self.assertRaises(ValueError): self.save(c)
        self.assertTrue(c.rolled_back)
        self.assertFalse(c.committed)
    def test_failed_update_rolls_back_audit(self):
        c=FakeConnection(self.original,fail=True)
        with self.assertRaises(RuntimeError): self.save(c)
        self.assertTrue(c.rolled_back and c.closed)
        self.assertFalse(c.committed)
    def test_registration_timestamp_cannot_be_edited(self):
        c=FakeConnection(self.original)
        with self.assertRaises(ValueError): self.save(c,changes={'criado_em':'changed'})
        self.assertEqual(c.calls,[])

if __name__=='__main__': unittest.main()
