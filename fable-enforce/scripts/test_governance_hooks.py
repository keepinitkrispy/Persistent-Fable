"""Integration tests execute the commands registered in .claude/settings.json."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from test_objective_gate import state as objective_fixture

SOURCE = Path(__file__).resolve().parents[2]

class HookTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='governance-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        shutil.copytree(SOURCE / '.claude', self.root / '.claude')
        scripts = self.root / 'fable-enforce/scripts'
        scripts.mkdir(parents=True)
        for name in ('governance_hook.py', 'stop_guard.py', 'filter.py', 'kernel_check.py', 'objective_gate.py'):
            shutil.copy(SOURCE / 'fable-enforce/scripts' / name, scripts / name)
        self.settings = json.loads((self.root / '.claude/settings.json').read_text())
        self.session = 'test-session'
        self.folder = self.root / '.fable/runtime' / hashlib.sha256(self.session.encode()).hexdigest()[:24]
        self.call('UserPromptSubmit', prompt='Install the requested checks.')

    def call(self, name, **fields):
        command = self.settings['hooks'][name][0]['hooks'][0]['command']
        result = subprocess.run(command, shell=True, cwd=self.root,
            env={**os.environ, 'CLAUDE_PROJECT_DIR': str(self.root)},
            input=json.dumps({'hook_event_name': name, 'session_id': self.session, **fields}),
            text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def trace(self):
        turn = json.loads((self.folder / 'turn.json').read_text())
        trace = {'turn_id': turn['turn_id'], 'decision': 'Install requested checks',
                 'selected_option': 'install', 'options': [
                     {'id': 'install', 'evidence': [{'claim': 'Installation was requested', 'license': 'STATED', 'weight': 1}]},
                     {'id': 'delay', 'evidence': [{'claim': 'Delaying leaves installation undone', 'license': 'INFERENCE', 'weight': 0}]}],
                 'baseline_rows': ['continuation', 'delay'], 'boundary': None, 'superseded_premises': []}
        self.save_trace(trace)
        return trace

    def save_trace(self, trace):
        (self.folder / 'decision_trace.json').write_text(json.dumps(trace))

    def stop(self, text='Requested installation completed.', **fields):
        raw = self.call('Stop', last_assistant_message=text, **fields)
        return json.loads(raw) if raw.strip() else {}

    def test_start_loads_exact_contract_and_writes_receipt(self):
        out = self.call('SessionStart', source='compact')
        self.assertIn((self.root / '.claude/rules/execution-contract.md').read_text(), out)
        receipt = json.loads((self.folder / 'receipts.jsonl').read_text().splitlines()[-1])
        self.assertEqual(receipt['status'], 'loaded')
        self.assertIn('contract_sha256', receipt)

    def test_clean_current_trace_and_response_allowed(self):
        self.trace()
        self.assertEqual(self.stop(), {})
        receipt = json.loads((self.folder / 'receipts.jsonl').read_text().splitlines()[-1])
        self.assertEqual(receipt['status'], 'allowed')
        self.assertEqual(receipt['objective_status'], 'not_configured')

    def test_missing_objective_does_not_disable_response_filter(self):
        self.trace()
        result = self.stop("I'll check every time going forward.")
        self.assertEqual(result['decision'], 'block')
        self.assertIn('SIG-1', result['reason'])

    def test_active_stop_hook_is_not_bypass(self):
        self.trace()
        self.assertEqual(self.stop("I'll check every time going forward.", stop_hook_active=True)['decision'], 'block')

    def test_missing_trace_blocks(self):
        self.assertEqual(self.stop()['decision'], 'block')

    def test_previous_turn_trace_blocks(self):
        self.trace()
        self.call('UserPromptSubmit', prompt='Continue with the next objective.')
        self.assertIn('stale', self.stop()['reason'])

    def test_unknown_weight_blocks(self):
        trace = self.trace()
        trace['options'][0]['evidence'][0].update(license='UNKNOWN', weight=1)
        self.save_trace(trace)
        self.assertIn('K-1', self.stop()['reason'])

    def test_empty_canned_trace_blocks(self):
        trace = self.trace()
        for option in trace['options']:
            option['evidence'] = []
        self.save_trace(trace)
        self.assertIn('evidence claims', self.stop()['reason'])

    def test_missing_response_blocks(self):
        self.trace()
        self.assertEqual(json.loads(self.call('Stop'))['decision'], 'block')

    def test_malformed_state_blocks(self):
        self.trace()
        (self.root / '.fable/active_objective.json').write_text('{invalid')
        self.assertEqual(self.stop()['decision'], 'block')

    def test_unmet_objective_still_blocks(self):
        self.trace()
        (self.root / '.fable/active_objective.json').write_text(json.dumps(objective_fixture(after='0')))
        self.assertIn('Objective remains OPEN', self.stop()['reason'])

    def test_met_objective_with_clean_checks_allowed(self):
        self.trace()
        (self.root / '.fable/active_objective.json').write_text(json.dumps(objective_fixture(status='PASS')))
        self.assertEqual(self.stop(), {})

    def test_stop_request_honored_without_marking_objective_complete(self):
        objective_path = self.root / '.fable/active_objective.json'
        objective_path.write_text(json.dumps(objective_fixture(after='0')))
        before = objective_path.read_text()
        self.call('UserPromptSubmit', prompt='Stop.')
        self.assertEqual(self.stop('Stopped.'), {})
        self.assertEqual(objective_path.read_text(), before)
        receipt = json.loads((self.folder / 'receipts.jsonl').read_text().splitlines()[-1])
        self.assertEqual(receipt['status'], 'user_stopped')

    def test_missing_dependency_blocks(self):
        self.trace()
        (self.root / 'fable-enforce/scripts/kernel_check.py').unlink()
        self.assertEqual(self.stop()['decision'], 'block')

    def test_missing_hook_entrypoint_returns_blocking_exit(self):
        (self.root / 'fable-enforce/scripts/stop_guard.py').unlink()
        command = self.settings['hooks']['Stop'][0]['hooks'][0]['command']
        result = subprocess.run(command, shell=True, cwd=self.root,
            env={**os.environ, 'CLAUDE_PROJECT_DIR': str(self.root)},
            input='{}', text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 2)
        self.assertIn('checks did not pass', result.stderr)

    def test_another_session_cannot_reuse_record(self):
        self.trace()
        self.session = 'other-session'
        self.assertEqual(self.stop()['decision'], 'block')

if __name__ == '__main__':
    unittest.main()
