#!/usr/bin/env python3
"""Claude Code lifecycle integration; standard library only, no model calls."""
from __future__ import annotations
import hashlib
import json
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()

def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
    tmp.replace(path)

def receipt(folder, event, status, **fields):
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / 'receipts.jsonl').open('a', encoding='utf-8') as stream:
        stream.write(json.dumps({'at': datetime.now(timezone.utc).isoformat(),
                                 'event': event, 'status': status, **fields}) + '\n')

def block(reason):
    print(json.dumps({'decision': 'block', 'reason': reason}))
    return 0

def handle(event):
    from filter import scan
    from kernel_check import check
    from objective_gate import check_state, completion_state
    name = event.get('hook_event_name')
    session = event.get('session_id')
    if not isinstance(session, str) or not session.strip():
        raise ValueError('Hook input has no session_id; cannot bind checks to this session.')
    folder = ROOT / '.fable' / 'runtime' / digest(session)[:24]
    trace_path = folder / 'decision_trace.json'
    turn_path = folder / 'turn.json'
    contract = (ROOT / '.claude/rules/execution-contract.md').read_text(encoding='utf-8')
    if name == 'SessionStart':
        receipt(folder, name, 'loaded', contract_sha256=digest(contract))
        print(contract)
        print('\nRead fable-enforce/HOOKS.md. Local receipts record actual hook invocation. '
              'Use short factual decision records, not private reasoning transcripts.')
        return 0
    if name == 'UserPromptSubmit':
        prompt = event.get('prompt')
        if not isinstance(prompt, str):
            raise ValueError('UserPromptSubmit has no prompt string.')
        turn = {'turn_id': uuid.uuid4().hex, 'prompt_sha256': digest(prompt),
                'user_stopped': bool(re.fullmatch(r'\s*(?:stop|stop working|cancel|cancel (?:the )?task)[.!\s]*', prompt, re.I))}
        write_json(turn_path, turn)
        receipt(folder, name, 'user_stopped' if turn['user_stopped'] else 'started', turn_id=turn['turn_id'])
        if turn['user_stopped']:
            print('The user explicitly stopped this turn. Stop work. This is not objective completion.')
        else:
            print('Apply .claude/rules/execution-contract.md before choosing actions. '
                  f'Write a brief factual decision record to {trace_path}. '
                  f'It must have turn_id={turn["turn_id"]}, decision, selected_option, options with '
                  'named ids and evidence rows containing claim/license/weight, baseline_rows including '
                  'continuation and delay, boundary if asserted, and superseded_premises. '
                  'Use actual alternatives and evidence; do not copy a canned passing trace. '
                  'Stop automatically scans the final response and validates this current-turn record. '
                  'An active .fable/active_objective.json is also checked. Missing/invalid records block stopping. '
                  'Receipt status allowed is not objective PASS.')
        return 0
    if name != 'Stop':
        raise ValueError(f'Unsupported hook event: {name}')
    turn = json.loads(turn_path.read_text(encoding='utf-8'))
    if turn.get('user_stopped') is True:
        receipt(folder, name, 'user_stopped', turn_id=turn['turn_id'])
        return 0
    text = event.get('last_assistant_message')
    if not isinstance(text, str) or not text.strip():
        raise ValueError('Stop input has no last_assistant_message. Response was not checked; use a Claude Code version providing this field.')
    findings = [f'{hit.sig}:{hit.name} line {hit.line}' for hit in scan(text, {})]
    try:
        trace = json.loads(trace_path.read_text(encoding='utf-8'))
        if not isinstance(trace, dict) or trace.get('turn_id') != turn['turn_id']:
            findings.append('K-0 missing/stale current-turn decision record')
        else:
            findings.extend(f'{code}:{label}: {detail}' for code, label, detail in check(trace))
            options = trace.get('options', [])
            options = options if isinstance(options, list) else []
            ids = [opt.get('id') for opt in options if isinstance(opt, dict)]
            if not isinstance(trace.get('decision'), str) or not trace['decision'].strip():
                findings.append('K-0 decision is missing')
            if not trace.get('selected_option') or trace['selected_option'] not in ids:
                findings.append('K-0 selected_option must identify an actual option')
            for opt in options:
                if not isinstance(opt, dict):
                    continue
                rows = opt.get('evidence')
                if not isinstance(rows, list) or not rows or any(
                        not isinstance(row, dict) or not isinstance(row.get('claim'), str)
                        or not row['claim'].strip() for row in rows):
                    findings.append('K-0 each alternative needs factual evidence claims')
    except (OSError, ValueError, TypeError) as exc:
        findings.append(f'K-0 decision record cannot be checked: {exc}. Write {trace_path}')
    state_path = ROOT / '.fable/active_objective.json'
    objective_status = 'not_configured'
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding='utf-8'))
        result = completion_state(state)
        objective_status = result['status']
        findings.extend(f'{code}:{label}: {detail}' for code, label, detail in check_state(state))
        if not result['pass']:
            findings.append('Objective remains OPEN: continue the next executable state transition; do not claim PASS.')
    receipt(folder, name, 'blocked' if findings else 'allowed',
            turn_id=turn['turn_id'], response_sha256=digest(text),
            objective_status=objective_status, findings=findings)
    if findings:
        return block('Governance checks failed. Correct these findings and continue the task: ' + '; '.join(findings))
    return 0

def main():
    event = {}
    try:
        event = json.load(sys.stdin)
        if not isinstance(event, dict):
            raise ValueError('Hook input must be a JSON object.')
        return handle(event)
    except Exception as exc:
        reason = f'Governance hook could not verify this event: {type(exc).__name__}: {exc}'
        if isinstance(event, dict) and event.get('hook_event_name') in ('SessionStart', 'UserPromptSubmit'):
            print(reason, file=sys.stderr)
            return 2
        return block(reason)

if __name__ == '__main__':
    raise SystemExit(main())
