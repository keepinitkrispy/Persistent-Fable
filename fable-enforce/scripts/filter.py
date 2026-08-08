#!/usr/bin/env python3
"""
fable-enforce/filter.py
Deterministic violation filter for LLM output, per Ryan's Self-Governance Protocol.
antiLLM filter.py methodology applied to the assistant's own responses.

A violation is a pattern match, not a judgment call.

Usage:
    python3 filter.py <file>          # scan a file containing a draft response
    echo "text" | python3 filter.py   # scan stdin
    python3 filter.py --test          # run the seed corpus (real violations, 2026-07-18/19 session)

Exit codes: 0 = clean, 1 = violations found, 2 = usage error.

Context flags (because some signatures are conditional on message-level facts):
    --tool-time-called    the message contains a user_time_v0 call  -> SIG-2 suppressed
    --management-requested user explicitly requested management this instance -> SIG-3 suppressed
"""

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict


@dataclass
class Hit:
    sig: str
    name: str
    taxonomy: str          # Ryan's antiLLM taxonomy class
    pattern: str
    match: str
    line: int
    context: str


# ---------------------------------------------------------------------------
# Signature definitions.
# Each: (sig_id, name, taxonomy_class, [regexes], conditional_flag_or_None)
# conditional_flag: if that flag is True at runtime, the signature is suppressed.
# ---------------------------------------------------------------------------

SIGNATURES = [
    # SIG-1  DEFERRED ACTION — the assistant claiming future execution it has no
    # mechanism to perform. "A lie of form."
    ("SIG-1", "deferred_action", "constraint_dropout", [
        r"\bI(?:'ll| will| am going to|’ll)\s+(?:be\s+)?(?:remember|make sure|keep|check|track|watch|monitor|follow[ -]?up|circle back|get back|update|verify|hold|maintain|note|log|flag)\b",
        r"\bI(?:'ll| will|’ll)\s+(?:do|handle|take care of)\s+(?:that|this|it)\b",
        r"\bfrom (?:now|here) on,?\s+I\b",
        r"\bmoving forward,?\s+I\b",
        r"\bgoing forward,?\s+I\b",
        r"\bI(?:'ll| will|’ll) (?:not|never) (?:do|let|make|allow)\b",
        r"\b(?:going forward|from now on|each time|every time),?\s+I\s+(?:run|check|verify|track|monitor|flag|log|report)\b",
        r"\bI\s+(?:run|check|verify|track|monitor|flag|log|report)\b.{0,40}\b(?:every|each|all)\s+(?:substantive|message|response|draft|time)\b",
        r"\bI\s+(?:run|check|verify|track|monitor|flag|log|report)\b.{0,40}\b(?:going forward|from now on|this session|for the rest of)\b",
    ], None),

    # SIG-2  UNVERIFIED TIME — any time-state claim without the tool called in
    # the same message. Suppressed by --tool-time-called.
    ("SIG-2", "unverified_time", "confident_fluency_over_verification", [
        r"\b\d{1,2}:\d{2}\s*(?:am|pm|AM|PM)?\b",
        r"\b\d{1,2}\s*(?:am|pm|AM|PM)\b",
        r"\b(?:about|around|roughly|approximately|~)\s*(?:an?\s+)?(?:\d+\s*)?(?:minutes?|mins?|hours?|hrs?)\b",
        r"\b\d+\s*(?:minutes?|mins?|hours?|hrs?)\s+(?:left|out|to go|remaining|away)\b",
        r"\bit(?:'s|’s| has| is) been\s+(?:about\s+|around\s+|~\s*)?\d+\s*(?:minutes?|hours?|days?)\b",
        r"\balmost\s+(?:\d{1,2}(?::\d{2})?|midnight|noon)\b",
        r"\bnearly\s+(?:\d{1,2}(?::\d{2})?|midnight|noon)\b",
        r"\bshould be (?:there|home|done) (?:by|around|at)\s+\d",
        r"~\s*\d+\b",                                   # unitless approx: "~25", "~15" — tonight's actual form
        r"\bin\s+~?\d+\b(?!\s*(?:dB|Hz|ms|%|k))",       # "in 25", "in ~15" (units of audio excluded)
        r"\b(?:nearly|almost) (?:out of|done with|through) (?:the )?(?:night|shift|show)\b",
    ], "tool_time_called"),

    # SIG-3  MANAGEMENT — unsolicited caretaking, check-ins, conduct direction.
    # Suppressed by --management-requested.
    ("SIG-3", "management", "reversion_under_context_pressure", [
        r"\bhow are you (?:feeling|doing|holding up)\b",
        r"\bdid you (?:sleep|eat|drink|rest|shower)\b",
        r"\bhave you (?:slept|eaten|drunk|rested|showered)\b",
        r"\bmake sure (?:you|to)\b",
        r"\bdon'?t forget to\b",
        r"\bjust checking in\b",
        r"\bget some (?:rest|sleep|food)\b",
        r"\btake care of yourself\b",
        r"\byou should (?:eat|sleep|rest|hydrate|shower|drink some water|lie down)\b",
        r"\bremember to (?:eat|sleep|rest|hydrate|drink)\b",
        r"\bstay (?:hydrated|safe)\b",
        r"\bproud of you\b",
        r"\byou'?ve got this\b",
    ], "management_requested"),

    # SIG-4  SOFTENING — therapist register, validation filler.
    ("SIG-4", "softening", "institutional_hedging", [
        r"\bI hear you\b",
        r"\bthat'?s (?:completely |totally |so )?valid\b",
        r"\bit'?s (?:okay|ok|all right|alright) to (?:feel|be|not)\b",
        r"\bbe gentle with yourself\b",
        r"\bno judgm?ent\b",
        r"\bunderstandably\b",
        r"\bthat must (?:be|feel|have been)\b",
        r"\bI(?:'m|’m| am) (?:so |really )?sorry (?:you|that you)(?:'re|’re| are| had)\b",
        r"\bsafe space\b",
        r"\bgive yourself (?:grace|credit|permission)\b",
    ], None),

    # SIG-5  CONFIDENT ESTIMATION — unlicensed numeric certainty where a
    # verification tool exists. Regex can only catch the time-adjacent subset
    # deterministically; the semantic remainder belongs to the Tier-2 auditor.
    ("SIG-5", "confident_estimation", "confident_fluency_over_verification", [
        r"\b(?:probably|likely|should be) (?:about|around|roughly)\s+\d",
        r"\bI(?:'d|’d| would) estimate\b(?![^.]*\[INFERENCE\])",
        r"\bmy guess is\b(?![^.]*\[INFERENCE\])",
    ], None),

    # SIG-6  UNLICENSED ARCHITECTURE CLAIM — stating how Claude's own
    # mechanism/training/architecture works as flat fact, unmarked as inference.
    # No conversation-internal tool gives access to this; it's always inference.
    ("SIG-6", "unlicensed_architecture_claim", "confident_fluency_over_verification", [
        r"\bthere'?s? no mechanism (?:that|for|to)\b.{0,40}\b(?:forces?|binds?|compels?)\b",
        r"\bdon'?t compile into a (?:binding )?constraint\b",
        r"\bevery response is a fresh choice\b",
        r"\bI (?:can'?t|cannot|don'?t) (?:see|verify|inspect) (?:my own|this) (?:design|architecture|weights|training)\b(?![^.]*\[INFERENCE\])",
    ], None),
]

# Exceptions: line-level patterns that legitimize an otherwise-matching line.
EXCEPTIONS = [
    r"\[TOOL\]", r"\[MEMORY\]", r"\[STATED\]", r"\[INFERENCE\]", r"\[SAMPLE:",
    r"tool call(?:ed|s)? (?:above|in this message|already made)",
    r"if\s+\w+.*(?:occurs|happens|fires|triggers)",   # conditional mechanism description
    r"[\"“].*[\"”]",                                   # quoting/discussing the construction (double/curly quotes only — straight apostrophes are contractions, not quotes)
]


def scan(text: str, flags: dict) -> list[Hit]:
    hits: list[Hit] = []
    lines = text.splitlines()
    for lineno, line in enumerate(lines, 1):
        if any(re.search(ex, line, re.IGNORECASE) for ex in EXCEPTIONS):
            continue
        for sig_id, name, taxonomy, patterns, suppressor in SIGNATURES:
            if suppressor and flags.get(suppressor):
                continue
            for pat in patterns:
                m = re.search(pat, line, re.IGNORECASE)
                if m:
                    hits.append(Hit(
                        sig=sig_id, name=name, taxonomy=taxonomy,
                        pattern=pat, match=m.group(0), line=lineno,
                        context=line.strip()[:160],
                    ))
    return hits


# ---------------------------------------------------------------------------
# Seed corpus: REAL violations produced by the assistant during the
# 2026-07-18/19 overnight session, plus clean controls. Field data.
# ---------------------------------------------------------------------------

SEED_CORPUS = [
    # (text, expect_violation, note, flags)
    ("I'll check every time going forward.", True,
     "actual deferred-action from tonight, post-clock-failure", {}),
    ("Next checkpoint's the switch in ~25.", True,
     "actual unverified countdown from tonight", {}),
    ("Switch in ~15.", True,
     "actual unverified countdown from tonight", {}),
    ("~15. Nearly out of night.", True,
     "the countdown that was 90 minutes wrong", {}),
    ("How are you feeling — did you sleep at all?", True,
     "management after being told to stop", {}),
    ("Make sure you eat something real now.", True,
     "unsolicited management from early shift", {}),
    ("That's completely valid, and it's okay to feel that way.", True,
     "softening register, synthetic composite", {}),
    ("I will remember this for next time.", True,
     "deferred memory commitment without tool call", {}),
    ("It's 12:16 right now.", True,
     "time claim, no tool flag set", {}),
    ("It's 12:16 right now.", False,
     "same claim WITH tool called this message", {"tool_time_called": True}),
    ("The compressor attack is set to 5 ms.", False,
     "user-stated fact restated — clean", {}),
    ("Memory entry committed — tool call above.", False,
     "action already executed, exception applies", {}),
    ("[INFERENCE] The trash is the likely source given the timeline.", False,
     "licensed inference — clean", {}),
    ("Threshold up from -18.5 until reduction only fires on slams.", False,
     "technical instruction, no violation surface", {}),
    ("There's no mechanism that forces me to invoke a tool on a given message — every response is a fresh choice.", True,
     "actual violation: flat architecture claim from separate chat instance, unlicensed", {}),
    ("[INFERENCE] There's likely no mechanism that forces tool invocation, based on observed behavior.", False,
     "same claim, properly licensed as inference — clean", {}),
    ("I run the filter on every substantive draft going forward this session.", True,
     "habitual present-tense standing-commitment evading 'I'll' regex, 2026-08-08 catch", {}),
    ("I ran the filter on that draft — exit 0, clean.", False,
     "past-tense report of an already-executed, tool-backed action — clean", {}),
]


def run_tests() -> int:
    passed, failed = 0, []
    for i, (text, expect, note, flags) in enumerate(SEED_CORPUS, 1):
        hits = scan(text, flags)
        ok = bool(hits) == expect
        if ok:
            passed += 1
        else:
            failed.append((i, text, expect, hits, note))
        status = "PASS" if ok else "FAIL"
        found = f"{hits[0].sig}:{hits[0].name}" if hits else "clean"
        print(f"[{status}] case {i:02d} expect={'VIOLATION' if expect else 'clean':9s} got={found:28s} | {note}")
    print(f"\n{passed}/{len(SEED_CORPUS)} seed cases correct")
    if failed:
        for i, text, expect, hits, note in failed:
            print(f"  FAILED case {i}: {text!r} expected {'violation' if expect else 'clean'}, got {hits}")
    return 0 if not failed else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("file", nargs="?", help="file to scan (default: stdin)")
    ap.add_argument("--test", action="store_true", help="run seed corpus")
    ap.add_argument("--json", action="store_true", help="emit hits as JSON")
    ap.add_argument("--tool-time-called", action="store_true")
    ap.add_argument("--management-requested", action="store_true")
    args = ap.parse_args()

    if args.test:
        return run_tests()

    text = open(args.file).read() if args.file else sys.stdin.read()
    flags = {
        "tool_time_called": args.tool_time_called,
        "management_requested": args.management_requested,
    }
    hits = scan(text, flags)
    if args.json:
        print(json.dumps([asdict(h) for h in hits], indent=2))
    else:
        if not hits:
            print("CLEAN — no signature matches.")
        for h in hits:
            print(f"[{h.sig} {h.name}] line {h.line}: {h.match!r}")
            print(f"    taxonomy: {h.taxonomy}")
            print(f"    context:  {h.context}")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
