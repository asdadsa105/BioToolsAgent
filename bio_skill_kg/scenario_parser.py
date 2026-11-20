"""Source-grounded application-scenario recovery for consistently structured Skill Markdown.

Distinct application contexts must not be confused with different command-line
executables. This parser only annotates *existing* Operations, never invents
new Operations, inputs, outputs, or direct tool-chain edges.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata


def _slug(label: str) -> str:
    text = unicodedata.normalize('NFKC', label).strip().casefold()
    text = re.sub(r'[^\w]+', '_', text).strip('_')
    # Use an ASCII hash rather than embedding Chinese in a graph identity.
    return 'usage_' + hashlib.sha256(text.encode('utf-8')).hexdigest()[:12]


def _fenced_commands(body: str) -> list[str]:
    return [m.group(1).strip() for m in re.finditer(
        r'^\s*```(?:bash|sh|shell|console)?\s*\n(.*?)^\s*```', body,
        re.I | re.M | re.S) if m.group(1).strip()]


def _has_operation(commands: list[str], operation_name: str) -> bool:
    """Match whole executable names, not arbitrary mentions in prose."""
    name = re.escape(operation_name.strip())
    pattern = re.compile(r'(?<![\w.])' + name + r'(?![\w.])', re.I)
    return any(pattern.search(command) for command in commands)


def source_application_scenarios(source_text: str, operation_name: str, source_file: str) -> list[dict]:
    """Get each explicit '7.x 场景N' template whose CLI contains the Operation.

    The section heading, descriptions and command example are all original
    document substrings and can therefore be independently audited.
    """
    text = str(source_text or '').replace('\r\n', '\n')
    lines = text.splitlines()
    section_header = re.compile(r'^###\s+(7\.\d+)\s+场景\s*\d*\s*[:：]\s*(.+?)\s*$')
    top_header = re.compile(r'^#{1,3}\s+(?:\d+\.\s+|\d+\.\d+\s+)?')
    candidates = []
    for i, line in enumerate(lines):
        m = section_header.match(line)
        if not m:
            continue
        end = next((j for j in range(i+1, len(lines)) if top_header.match(lines[j])), len(lines))
        body = '\n'.join(lines[i+1:end])
        commands = _fenced_commands(body)
        # Omit unrelated scenarios for other subcommands in the same document.
        if not _has_operation(commands, operation_name):
            continue
        label = m.group(2).strip()
        evidence = line  # Literal source quote; never an LLM-generated paraphrase.
        use = re.search(r'^\s*\*\*适用场景\*\*\s*[:：]\s*(.+?)\s*$', body, re.M)
        inputs = re.search(r'^\s*\*\*输入数据\*\*\s*[:：]\s*(.+?)\s*$', body, re.M)
        outputs_block = re.search(r'^\s*\*\*预期输出\*\*\s*[:：]\s*\n((?:\s*[-*]\s+[^\n]+\n?)+)', body, re.M)
        # Scenario parameters are cited as a command example rather than
        # copied to every Operation global parameter; this preserves context.
        cmd = next((x for x in commands if _has_operation([x], operation_name)), '')
        output_lines = [re.sub(r'^\s*[-*]\s+', '', ln).strip()
                        for ln in (outputs_block.group(1).splitlines() if outputs_block else [])]
        candidates.append({
            'scenario_id': _slug(label), 'name': label, 'scenario_kind': 'application',
            'description': use.group(1).strip() if use else None,
            'documented_input': inputs.group(1).strip() if inputs else None,
            'documented_outputs': output_lines,
            'recommended_command': cmd or None,
            'evidence_quote': evidence,
            'evidence_quotes': [evidence],
            'source_files': [source_file],
            'source_sections': [f'{source_file} §{m.group(1)} 场景{label}'],
        })
    return candidates
