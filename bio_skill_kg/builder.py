"""Legacy rule-based BioSkillKG builder and shared incremental Graph model.

Use build_graph() for the backward-compatible profiles.json mode. The new
DeepSeek mode is implemented in llm_extractor.py + auto_builder.py and reuses
Graph, merge_graphs, IDs, relation types, and the BioSkillKG-v2 JSON schema.
"""
from __future__ import annotations

import json
import re
import hashlib
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

BASE = Path(__file__).resolve().parent
LABELS = {"Tool", "Operation", "Task", "DataType", "FileFormat"}
RELATIONS = {
    "HAS_OPERATION", "PERFORMS", "REQUIRES_INPUT", "PRODUCES", "HAS_FORMAT",
    "IS_SUBTYPE_OF", "RECOMMENDED_BEFORE", "DOCUMENTED_DOWNSTREAM",
    "DOCUMENTED_PREREQUISITE", "PARTIALLY_ALTERNATIVE_TO"
}


def load_aliases(path: str | Path | None = None) -> dict[str, str]:
    """Explicit aliases only; no fuzzy matching of unrelated software names."""
    path = Path(path) if path else BASE / 'tool_aliases.json'
    raw = json.loads(path.read_text(encoding='utf-8'))
    return {unicodedata.normalize('NFKC', k).casefold().strip():
            unicodedata.normalize('NFKC', v).casefold().strip()
            for k, v in raw.items()}


def canonical_tool_name(raw_name: str, aliases: dict[str, str]) -> str:
    name = unicodedata.normalize('NFKC', raw_name or '')
    name = re.sub(r'\s*[(（].*$', '', name).strip().casefold()
    name = re.sub(r'\s+', ' ', name)
    return aliases.get(name, name)


def scalar(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"\*\*|`", "", text or "")).strip()


def field(body: str, name: str) -> str:
    hit = re.search(r"^\s*\*\*" + re.escape(name) + r"\*\*\s*[:：]\s*(.+)$", body, re.M)
    return scalar(hit.group(1)) if hit else ""


def numbered_section(body: str, section: int) -> str:
    m = re.search(rf"^##\s+{section}\.\s+", body, re.M)
    if not m:
        return ""
    end = re.search(r"^##\s+\d+\.\s+", body[m.end():], re.M)
    return body[m.start():m.end() + end.start()] if end else body[m.start():]


def collect_resources(body: str) -> dict:
    section = numbered_section(body, 4)
    result = {}
    for heading, prefix, unit in [('CPU需求', 'cpu_cores', '核'), ('内存需求', 'memory_gb', 'GB')]:
        match = re.search(r"^###\s+4\.\d+\s+" + heading + r"\s*$", section, re.M)
        if not match:
            continue
        end = re.search(r"^###\s+4\.\d+\s+", section[match.end():], re.M)
        sub = section[match.end():match.end() + end.start()] if end else section[match.end():]
        for cn, en in [('最小', 'min'), ('推荐', 'recommended'), ('最大', 'max')]:
            m = re.search(r"^\s*-\s*\*\*" + cn + r"\*\*\s*[:：]\s*(\d+(?:\.\d+)?)\s*" + unit, sub, re.M | re.I)
            if m:
                value = float(m.group(1))
                result[f'{prefix}_{en}'] = int(value) if value.is_integer() else value
    return result



def collect_optional_reference_sections(body: str) -> dict:
    """Keep raw resource/parameter sections as reviewable text, not executable flags."""
    params = numbered_section(body, 2)
    resource = numbered_section(body, 4)
    result = {}
    if params:
        result['parameter_reference_markdown'] = params[:12000]
    if resource:
        result['resource_reference_markdown'] = resource[:12000]
    return result

def find_operations(body: str, tool_key: str) -> tuple[set[str], list[str]]:
    """Extract command mentions, not all are assumed valid operations."""
    sections = numbered_section(body, 7) + '\n' + numbered_section(body, 9)
    found = set()
    for line in sections.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if tool_key in {'bcftools', 'bedtools', 'bwa'}:
            for match in re.finditer(r'\b' + re.escape(tool_key) + r'\s+([a-z][a-z0-9_-]*)\b', line, re.I):
                found.add(f'{tool_key} {match.group(1).lower()}')
        elif tool_key == 'annovar':
            if re.search(r'\btable_annovar\.pl\b', line):
                found.add('table_annovar.pl')
    return found, []


def split_tools(text: str) -> list[str]:
    text = re.split(r'[（(]', text, maxsplit=1)[0]
    text = text.split('等')[0]
    text = text.replace('、', ',').replace('，', ',')
    vals = [v.strip().lstrip('等') for v in text.split(',')]
    return [v for v in vals if v and v not in {'无', '自定义脚本', '其他bedtools命令', '无（直接处理各种基因组数据文件）'}]


def related_tools(body: str) -> list[tuple[str, str, str, str]]:
    """(relation, other-tool-name, evidence-section, direction), conservative."""
    part = numbered_section(body, 6)
    results = []
    section_id = ''
    for line in part.splitlines():
        if re.match(r'^###\s+6\.1\b', line): section_id = '6.1'
        if re.match(r'^###\s+6\.2\b', line): section_id = '6.2'
        if re.match(r'^###\s+6\.3\b', line): section_id = '6.3'
        if section_id == '6.1':
            for token, relation in [('必需前置工具', 'DOCUMENTED_PREREQUISITE'), ('推荐前置工具', 'RECOMMENDED_BEFORE')]:
                m = re.match(r'^\s*-\s*\*\*' + token + r'\*\*\s*[:：]\s*(.+)', line)
                if m:
                    for name in split_tools(m.group(1)):
                        results.append((relation, name, section_id, 'prior'))
        elif section_id == '6.2' and line.strip().startswith('|'):
            columns = [v.strip() for v in line.strip().strip('|').split('|')]
            if len(columns) >= 3 and columns[0] not in {'工具名称', '---------', ''} and not all(set(x)<=set('-: ') for x in columns):
                name = columns[0]
                if name not in {'其他bedtools命令'}:
                    results.append(('DOCUMENTED_DOWNSTREAM', name, section_id, 'downstream'))
        elif section_id == '6.3':
            m = re.match(r'^\s*-\s*\*\*(?:互斥工具|替代工具)\*\*\s*[:：]\s*(.+)', line)
            if m:
                for name in split_tools(m.group(1)):
                    results.append(('PARTIALLY_ALTERNATIVE_TO', name, section_id, 'downstream'))
    return list(dict.fromkeys(results))


class Graph:
    """Canonical, append-only graph with source provenance and conflict review.

    The same typed node ID is reused across different Markdown documents and
    import batches. Conflicting non-empty fields are reviewed instead of
    silently replacing data unless conflict_policy='prefer-incoming'.
    """

    def __init__(self, *, aliases: dict[str, str] | None = None,
                 conflict_policy: str = 'keep-existing'):
        if conflict_policy not in {'keep-existing', 'prefer-incoming'}:
            raise ValueError('Unsupported conflict policy')
        self.nodes: dict[str, dict] = {}
        self.edges: dict[tuple[str, str, str], dict] = {}
        self.review: list[dict] = []
        self.documents: dict[str, str] = {}
        self.aliases = aliases if aliases is not None else load_aliases()
        self.conflict_policy = conflict_policy

    @staticmethod
    def _decode_json_list(value: Any) -> list:
        if isinstance(value, list):
            return value
        if isinstance(value, str) and value.strip():
            try:
                parsed = json.loads(value)
                return parsed if isinstance(parsed, list) else []
            except (TypeError, ValueError):
                return []
        return []

    @staticmethod
    def _merge_description_claims(existing: Any, incoming: Any) -> str:
        claims = Graph._decode_json_list(existing)
        for claim in Graph._decode_json_list(incoming):
            if not isinstance(claim, dict):
                continue
            fingerprint = json.dumps(claim, sort_keys=True, ensure_ascii=False)
            if all(json.dumps(x, sort_keys=True, ensure_ascii=False) != fingerprint for x in claims):
                claims.append(claim)
        return json.dumps(claims, ensure_ascii=False, sort_keys=True)

    @staticmethod
    def _decode_json_records(value: Any) -> list[dict]:
        if isinstance(value, list):
            return [dict(x) for x in value if isinstance(x, dict)]
        if isinstance(value, str) and value.strip():
            try:
                parsed = json.loads(value)
                if isinstance(parsed, list):
                    return [dict(x) for x in parsed if isinstance(x, dict)]
            except (TypeError, ValueError):
                return []
        return []

    @staticmethod
    def _operation_record_key(item: dict, kind: str) -> tuple:
        if kind == "scenarios_json":
            return (str(item.get("scenario_id") or item.get("name") or "").casefold(),)
        return (
            str(item.get("raw_data_type") or item.get("data_type_id") or item.get("data_type_key") or item.get("data_type") or "").casefold(),
            str(item.get("role") or "").casefold(),
            str(item.get("flag") or "").casefold(),
            str(item.get("scenario_id") or "").casefold(),
            str(item.get("condition") or "").casefold(),
        )

    def _merge_operation_json_records(self, existing: Any, incoming: Any, kind: str) -> str:
        """Merge JSON-list Operation properties without collapsing distinct ports.

        These attributes are JSON strings because Neo4j properties cannot store
        nested maps/lists. Their merge identity deliberately includes role,
        CLI flag and scenario so two ports of the same DataType remain distinct.
        """
        result = self._decode_json_records(existing)
        for item in self._decode_json_records(incoming):
            key = self._operation_record_key(item, kind)
            current = next((x for x in result if self._operation_record_key(x, kind) == key), None)
            if current is None:
                result.append(item)
                continue
            # A later curated resolution supersedes a pending candidate with
            # the same raw port identity. Never let stale candidate state win.
            if item.get("resolution_status") == "curated" and current.get("resolution_status") == "pending_review":
                result[result.index(current)] = {**current, **item}
                continue
            if current.get("resolution_status") == "curated" and item.get("resolution_status") == "pending_review":
                continue
            for field, value in item.items():
                if field in {"evidence_quotes", "formats", "format_evidence", "source_files", "source_sections"}:
                    old_values = current.get(field, [])
                    if not isinstance(old_values, list):
                        old_values = [old_values] if old_values else []
                    new_values = value if isinstance(value, list) else ([value] if value else [])
                    fingerprints = {json.dumps(x, ensure_ascii=False, sort_keys=True) for x in old_values}
                    for candidate in new_values:
                        fingerprint = json.dumps(candidate, ensure_ascii=False, sort_keys=True)
                        if fingerprint not in fingerprints:
                            old_values.append(candidate)
                            fingerprints.add(fingerprint)
                    current[field] = old_values
                elif current.get(field) in (None, "", [], {}):
                    if value not in (None, "", [], {}):
                        current[field] = value
                elif value not in (None, "", [], {}) and current.get(field) != value:
                    # Keep both evidence variants; other conflicting values
                    # remain reviewable at the graph-build stage.
                    if field == "evidence_quote":
                        quotes = current.setdefault("evidence_quotes", [])
                        for quote in (current.get(field), value):
                            if quote and quote not in quotes:
                                quotes.append(quote)
                    elif field not in {"data_type", "data_type_key", "data_type_id", "port_id"}:
                        self.review.append({
                            "entity_id": "operation_port",
                            "field": field,
                            "reason": "同一 Operation 输入/输出端口的增量属性不一致，需要人工核对",
                            "port_key": list(key),
                            "old_preview": str(current.get(field))[:120],
                            "new_preview": str(value)[:120],
                            "decision": self.conflict_policy,
                        })
                        if self.conflict_policy == "prefer-incoming":
                            current[field] = value
        return json.dumps(result, ensure_ascii=False, sort_keys=True)

    def node(self, id: str, label: str, **props: Any):
        if label not in LABELS:
            raise ValueError(label)
        props = dict(props)
        if label == 'DataType':
            # Preserve each document's own wording and evidence. A differing
            # description is not automatically a semantic contradiction.
            explicit_claim = props.pop('description_claim', None)
            claims = self._decode_json_list(props.get('description_claims_json'))
            if explicit_claim or (props.get('description') and not claims):
                claim_description = str(explicit_claim or props.get('description'))
                claim = {
                    'description': claim_description,
                    'source_file': props.get('source_file'),
                    'source_section': props.get('source_section'),
                    'evidence_quote': props.get('evidence_quote') or '',
                }
                if claim not in claims:
                    claims.append(claim)
            if claims:
                props['description_claims_json'] = json.dumps(claims, ensure_ascii=False, sort_keys=True)
        props = {k: v for k, v in props.items() if v is not None and v != ''}
        if label == 'Tool':
            props.setdefault('stub', False)
        if props.get('source_file'):
            props.setdefault('source_files', [props['source_file']])
        if props.get('source_section') and props.get('source_file'):
            props.setdefault('source_sections', [f"{props['source_file']} §{props['source_section']}"])
        props.pop('source_section', None)
        if props.get('evidence_quote'):
            props.setdefault('evidence_quotes', [props['evidence_quote']])
        props.pop('evidence_quote', None)
        if id not in self.nodes:
            self.nodes[id] = {'id': id, 'label': label, 'properties': dict(props)}
            return
        old = self.nodes[id]
        if old['label'] != label:
            raise ValueError(f'Label conflict for {id}: {old["label"]} != {label}')
        existing = old['properties']
        old_stub = label == 'Tool' and bool(existing.get('stub', False))
        new_stub = label == 'Tool' and bool(props.get('stub', False))
        if label == 'Tool' and old_stub and not new_stub:
            # Upgrade a placeholder to a fully described entity.
            existing['stub'] = False
        for k, v in props.items():
            if label == 'Operation' and k in {'input_specs_json', 'output_specs_json', 'unresolved_input_specs_json', 'unresolved_output_specs_json', 'scenarios_json'}:
                existing[k] = self._merge_operation_json_records(existing.get(k), v, k)
                continue
            if k == 'description_claims_json' and label == 'DataType':
                existing[k] = self._merge_description_claims(existing.get(k), v)
                continue
            if k == 'description' and label == 'DataType':
                # Keep the canonical description already selected, while all
                # source-specific variants are retained in description_claims_json.
                if k not in existing or existing[k] in (None, ''):
                    existing[k] = v
                continue
            if k in {'source_files', 'aliases', 'source_sections', 'evidence_quotes', 'parameter_names', 'parameter_flags', 'formats', 'quality_control_names'}:
                prior = existing.get(k, [])
                existing[k] = list(dict.fromkeys((prior if isinstance(prior, list) else [prior]) +
                                                  (v if isinstance(v, list) else [v])))
                continue
            if k == 'stub':
                existing['stub'] = bool(existing.get('stub', False)) and bool(v)
                continue
            if old_stub and not new_stub:
                existing[k] = v
                continue
            if new_stub and not old_stub:
                # The name from a reference must not downgrade a full Tool.
                continue
            if k not in existing or existing[k] in (None, ''):
                existing[k] = v
            elif existing[k] != v:
                if k == 'source_file':
                    continue  # source_files retains all provenance
                self.review.append({'entity_id': id, 'field': k, 'reason': '实体属性冲突，需要人工核对',
                                    'old_preview': str(existing[k])[:140],
                                    'new_preview': str(v)[:140],
                                    'decision': self.conflict_policy})
                if self.conflict_policy == 'prefer-incoming':
                    existing[k] = v

    def edge(self, source: str, relation: str, target: str,
             source_file: str = '', source_section: str = '',
             status: str = 'documented', evidence_quote: str = ''):
        if relation not in RELATIONS:
            raise ValueError(relation)
        if source not in self.nodes or target not in self.nodes:
            raise ValueError(f'Missing node: {source} or {target}')
        key = (source, relation, target)
        if key not in self.edges:
            self.edges[key] = {'source': source, 'type': relation, 'target': target,
                               'properties': {'source_files': [], 'source_sections': [],
                                              'status': status, 'evidence_quotes': []}}
        attr = self.edges[key]['properties']
        if source_file and source_file not in attr['source_files']:
            attr['source_files'].append(source_file)
        if source_file and source_section:
            ev = f'{source_file} §{source_section}'
            if ev not in attr['source_sections']:
                attr['source_sections'].append(ev)
        if evidence_quote and evidence_quote not in attr.setdefault('evidence_quotes', []):
            attr['evidence_quotes'].append(evidence_quote)

    def ingest(self, graph: dict):
        if graph.get('schema') not in {'BioSkillKG-v1', 'BioSkillKG-v2'}:
            raise ValueError('Unsupported BioSkillKG graph schema')
        remap: dict[str, str] = {}
        for n in graph.get('nodes', []):
            nid, label = n['id'], n['label']
            props = dict(n.get('properties', {}))
            if label == 'Tool':
                # Also canonicalize Tool IDs from old v1 graph files.
                raw = props.get('canonical_name') or nid.removeprefix('tool:')
                canonical = canonical_tool_name(raw, self.aliases)
                nid = f'tool:{canonical}'
                props['canonical_name'] = canonical
            remap[n['id']] = nid
            self.node(nid, label, **props)
        for e in graph.get('edges', []):
            a = remap[e['source']]
            b = remap[e['target']]
            attr = e.get('properties', {})
            sources = attr.get('source_files') or ['']
            sections = attr.get('source_sections') or []
            # Preserve all provenance from the old and new graph without
            # assuming source_files and source_sections align positionally.
            self.edge(a, e['type'], b, status=attr.get('status', 'documented'))
            key = (a, e['type'], b)
            dest = self.edges[key]['properties']
            for file in sources:
                if file and file not in dest['source_files']:
                    dest['source_files'].append(file)
            for section in sections:
                if section not in dest['source_sections']:
                    dest['source_sections'].append(section)
            for quote in attr.get('evidence_quotes', []):
                if quote not in dest.setdefault('evidence_quotes', []):
                    dest['evidence_quotes'].append(quote)
        for item in graph.get('review', []):
            self.review.append(item)
        self.documents.update(graph.get('metadata', {}).get('documents', {}))

    def to_dict(self):
        seen = set()
        review = []
        for item in self.review:
            fingerprint = json.dumps(item, sort_keys=True, ensure_ascii=False)
            if fingerprint not in seen:
                seen.add(fingerprint)
                review.append(item)
        return {'schema': 'BioSkillKG-v2',
                'metadata': {'documents': dict(sorted(self.documents.items()))},
                'nodes': [self.nodes[k] for k in sorted(self.nodes)],
                'edges': [self.edges[k] for k in sorted(self.edges)],
                'review': review}


def merge_graphs(existing: dict, incoming: dict, *,
                 aliases: dict[str, str] | None = None,
                 conflict_policy: str = 'keep-existing') -> dict:
    """Merge an old saved graph with newly parsed documents.

    New docs may enrich placeholder tools and add edges. No deletion is made.
    """
    graph = Graph(aliases=aliases, conflict_policy=conflict_policy)
    graph.ingest(existing)
    graph.ingest(incoming)
    return graph.to_dict()


def build_graph(documents: list, profiles: dict | None = None,
                data_types: dict | None = None,
                aliases: dict[str, str] | None = None) -> dict:
    profiles = profiles if profiles is not None else json.loads((BASE/'profiles.json').read_text('utf-8'))
    data_types = data_types if data_types is not None else json.loads((BASE/'data_types.json').read_text('utf-8'))
    aliases = aliases if aliases is not None else load_aliases()
    g = Graph(aliases=aliases)
    tool_metadata = []
    for doc in documents:
        body = doc.content
        raw_name = field(body, '工具名称')
        tool_key = canonical_tool_name(raw_name, aliases)
        if not raw_name:
            g.review.append({'file':doc.file_path,'reason':'缺少工具名称'}); continue
        tool_metadata.append((doc,tool_key,raw_name))
        source=Path(doc.file_path).name
        fingerprint=hashlib.sha256(body.encode('utf-8')).hexdigest()
        if source in g.documents and g.documents[source] != fingerprint:
            g.review.append({'file': source, 'reason': '同一批次有同名但内容不同的文档，需确认来源'})
        g.documents[source] = fingerprint
        g.node(f'tool:{tool_key}', 'Tool', name=raw_name, canonical_name=tool_key,
               version=field(body,'工具版本'),category=field(body,'工具分类'),
               description=field(body,'工具描述'),source_url=field(body,'工具来源'),
               docker_image=field(body,'Docker镜像'),source_file=source,stub=False,aliases=[raw_name],
               **collect_resources(body),**collect_optional_reference_sections(body))
    # All primary tools are established, then relation targets are unified.
    for doc,key,raw_name in tool_metadata:
        body=doc.content; source=Path(doc.file_path).name
        tool_id=f'tool:{key}'
        operations=profiles.get(key)
        if key == 'bwa' and '错配惩罚' in numbered_section(body,2) and '不匹配得分' in numbered_section(body,2):
            g.review.append({'file':source,'reason':'BWA 的 -B 在参数表中出现不同定义，操作参数需核对官方手册'})
        if key == 'bedtools' and '| 线程数 | -sorted' in numbered_section(body,2):
            g.review.append({'file':source,'reason':'bedtools 参数表中多个选项被标为线程数，需要按子命令核对'})
        if key == 'annovar' and '必需前置工具' in numbered_section(body,6):
            g.review.append({'file':source,'reason':'ANNOVAR 文档声称特定前置工具为必需；仅保留文档来源，不将其当作确定执行依赖'})
        detected, _ = find_operations(body,key)
        if operations is None:
            g.review.append({'file':source,'reason':f'{key} 没有人工审核的操作模板，请补充 profiles.json'})
            operations=[]
        verified_commands={p['command'] for p in operations}
        for command in sorted(detected-verified_commands):
            g.review.append({'file':source,'reason':f'出现未收录或待核对的子命令: {command}（没有自动入图）'})
        for p in operations:
            command = p['command']
            if command not in detected:
                g.review.append({'file':source,'reason':f'操作模板 {command} 在第7/9章没有匹配到命令示例，仍按人工模板生成，请复核'})
            op_key = command.lower().replace(' ','_')
            op_id=f'op:{op_key}'
            g.node(op_id, 'Operation', name=command, description=p['task_name'],
                   min_input_files=p.get('min_input_files',1), notes=p.get('notes',''),
                   source_file=source, validation_status='needs_manual_validation')
            g.edge(tool_id,'HAS_OPERATION',op_id,source,'7/9','curated_from_skill')
            task_id=f'task:{p["task_id"]}'
            g.node(task_id,'Task',name=p['task_name'])
            g.edge(op_id,'PERFORMS',task_id,source,'7','curated_from_skill')
            for rtype, dt_ids in [('REQUIRES_INPUT',p['inputs']),('PRODUCES',p['outputs'])]:
                for dt_id in dt_ids:
                    if dt_id not in data_types: raise ValueError(f'Missing data type {dt_id} in data_types.json')
                    data=data_types[dt_id]
                    did=f'data:{dt_id}'
                    g.node(did,'DataType',name=data['name'])
                    g.edge(op_id,rtype,did,source,'3/5/7','curated_from_skill')
                    for fmt in data.get('formats',[]):
                        fmt_id=f'format:{fmt}'
                        g.node(fmt_id,'FileFormat',name=fmt)
                        g.edge(did,'HAS_FORMAT',fmt_id,source,'5/7','curated_from_skill')
                    parent=data.get('parent')
                    if parent:
                        if parent not in data_types: raise ValueError(f'Missing parent data type {parent}')
                        pid=f'data:{parent}'
                        g.node(pid,'DataType',name=data_types[parent]['name'])
                        g.edge(did,'IS_SUBTYPE_OF',pid,source,'5/7','curated_from_skill')
        for relation, other_name, section, direction in related_tools(body):
            other_name=other_name.strip()
            # 'R' and Excel are software/tool references but not executable here.
            other_key=canonical_tool_name(other_name, aliases)
            if not other_key or other_key == key: continue
            other_id=f'tool:{other_key}'
            if other_id not in g.nodes:
                g.node(other_id,'Tool',name=other_name,canonical_name=other_key,stub=True,aliases=[other_name])
            if direction=='prior':
                g.edge(other_id, relation, tool_id, source,section,'documented_not_validated')
            else:
                g.edge(tool_id, relation, other_id, source,section,'documented_not_validated')
    return g.to_dict()


def summary(graph: dict) -> dict:
    return {'nodes':len(graph['nodes']),'edges':len(graph['edges']),
            'labels':dict(sorted(Counter(n['label'] for n in graph['nodes']).items())),
            'relations':dict(sorted(Counter(e['type'] for e in graph['edges']).items())),
            'review_items':len(graph['review'])}
