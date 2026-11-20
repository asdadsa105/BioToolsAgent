"""Schema and source-evidence validation for BioSkillKG LLM extraction."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

SCHEMA_PATH = Path(__file__).resolve().parent / "extraction_schema.json"


def normalize_extraction_shape(obj: dict) -> dict:
    if not isinstance(obj, dict):
        raise ValueError("LLM output must be a JSON object")
    normalized = dict(obj)
    if normalized.get("tool") is None:
        normalized["tool"] = {}
    for key in ("resources", "tool_parameters", "operations", "data_types", "tool_relations", "quality_controls"):
        if normalized.get(key) is None:
            normalized[key] = []
        else:
            normalized.setdefault(key, [])
    # v1.5 adds scenario metadata and port-level constraints. Keep older
    # extraction/cache records readable while presenting a stable shape to
    # downstream code.
    for operation in normalized.get("operations", []):
        if not isinstance(operation, dict):
            continue
        operation.setdefault("scenarios", [])
        for io_key in ("inputs", "outputs"):
            records = operation.get(io_key, [])
            if isinstance(records, list):
                for record in records:
                    if isinstance(record, dict):
                        record.setdefault("role", None)
                        record.setdefault("flag", None)
                        record.setdefault("flag_evidence_quote", None)
                        record.setdefault("required", None)
                        record.setdefault("min_occurs", None)
                        record.setdefault("max_occurs", None)
                        record.setdefault("scenario_id", None)
                        record.setdefault("scenario_name", None)
                        record.setdefault("condition", None)
    return normalized


def validate_extraction_shape(obj: dict) -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    try:
        import jsonschema
        jsonschema.validate(instance=obj, schema=schema)
    except ImportError:
        # Minimal fallback when jsonschema is not installed.
        if not isinstance(obj.get("tool"), dict):
            raise ValueError("tool must be an object")
        for key in ("resources", "tool_parameters", "operations", "data_types", "tool_relations", "quality_controls"):
            if not isinstance(obj.get(key), list):
                raise ValueError(f"{key} must be an array")
    except Exception as exc:
        raise ValueError(f"LLM JSON does not match extraction_schema.json: {str(exc)[:240]}") from exc


def _quote_in_chunk(quote: str, chunk_text: str) -> bool:
    q = _norm_quote(quote)
    t = _norm_quote(chunk_text)
    return bool(q) and q in t


def _norm_quote(value: str) -> str:
    return _norm_quote_basic(value).casefold()


def _norm_quote_basic(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()



def _format_forms(value: str) -> set[str]:
    token = re.sub(r"[^A-Z0-9]+", "_", str(value or "").upper()).strip("_")
    forms = {token}
    forms.add(token.replace("_", "."))
    forms.add(token.replace("_", ""))
    return {x for x in forms if x}


def _expanded_format_forms(value: str) -> set[str]:
    forms = _format_forms(value)
    path = Path(__file__).resolve().parent / "file_formats.json"
    if not path.exists():
        return forms
    try:
        registry = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return forms
    for canonical, item in registry.items():
        group = _format_forms(canonical)
        if isinstance(item, dict):
            for alias in item.get("aliases", []):
                group.update(_format_forms(alias))
        if forms & group:
            return group
    return forms


def _known_format_names() -> set[str]:
    path = Path(__file__).resolve().parent / "file_formats.json"
    if not path.exists():
        return set()
    try:
        registry = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return set()
    names = set()
    for canonical, item in registry.items():
        names.update(_format_forms(canonical))
        if isinstance(item, dict):
            for alias in item.get("aliases", []):
                names.update(_format_forms(alias))
    return names



def _format_mentioned_in_text(value: str, fmt: str) -> bool:
    """Return True only when a canonical format name or registered alias is explicit."""
    text = str(value or "").upper()
    token = str(fmt or "").strip().upper()
    if not token:
        return False
    registry_path = Path(__file__).resolve().parent / "file_formats.json"
    aliases = [token]
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        for canonical, item in registry.items():
            if canonical.upper() == token and isinstance(item, dict):
                aliases.extend(str(x) for x in item.get("aliases", []))
                break
    except Exception:
        pass

    for alias in aliases:
        candidate = alias.strip().upper()
        if not candidate:
            continue
        # Extensions are matched as extensions, not as arbitrary substrings.
        if candidate.startswith("."):
            pattern = re.escape(candidate) + r"(?![A-Z0-9_.])"
        else:
            pattern = r"(?<![A-Z0-9])" + re.escape(candidate) + r"(?![A-Z0-9_.])"
        if re.search(pattern, text):
            return True
    return False


def _semantic_anchors(value: str) -> set[str]:
    text = str(value or "").casefold()
    anchors = (
        "注释", "变异", "覆盖度", "基因组区域", "区域", "信号", "比对",
        "测序", "样本", "参考基因组", "基因注释", "日志", "交集",
        "合并", "差异", "质量分布", "并集", "统计", "annotation",
        "variant", "coverage", "signal", "alignment", "read", "sample",
        "region", "genome", "log", "intersection", "merged", "difference",
    )
    return {x for x in anchors if x in text and x not in {"区域", "统计"}}


def resolve_format_evidence(record: dict, source_text: str,
                            formats: list[str] | None = None) -> tuple[list[str], list[dict]]:
    """Resolve each format to its own source quote.

    Backward compatible with v1.3 extraction records: use the record-level quote
    when it explicitly contains the format; otherwise find a source line that
    mentions both the format and the same semantic concept.
    """
    formats = formats if isinstance(formats, list) else []
    name = str(record.get("name") or record.get("data_type") or "")
    description = str(record.get("description") or "")
    record_quote = str(record.get("evidence_quote") or "").strip()
    supplied = record.get("format_evidence")
    supplied = supplied if isinstance(supplied, list) else []
    anchors = _semantic_anchors(f"{name} {description}")

    verified_formats: list[str] = []
    evidence: list[dict] = []
    for fmt in formats:
        fmt_text = str(fmt or "").strip()
        if not fmt_text:
            continue
        quote = ""

        # 1) Prefer explicit per-format quotes from the LLM.
        for item in supplied:
            if not isinstance(item, dict):
                continue
            item_fmt = str(item.get("format") or "").strip()
            item_quote = str(item.get("evidence_quote") or "").strip()
            if (_format_forms(item_fmt) & _format_forms(fmt_text)
                    and _quote_in_chunk(item_quote, source_text)
                    and _format_mentioned_in_text(item_quote, fmt_text)):
                quote = item_quote
                break

        # 2) The record-level evidence can support more than one format only
        #    when it explicitly names each one.
        if not quote and _quote_in_chunk(record_quote, source_text):
            if _format_mentioned_in_text(record_quote, fmt_text):
                quote = record_quote

        # 3) Legacy extraction may have one quote for the first format only.
        #    Search a nearby source line for the other format, but require a
        #    semantic anchor shared with the DataType description.
        if not quote and anchors:
            for line in str(source_text or "").splitlines():
                candidate = line.strip()
                if not candidate or candidate.startswith("#") or not _format_mentioned_in_text(candidate, fmt_text):
                    continue
                line_anchors = _semantic_anchors(candidate)
                if anchors & line_anchors:
                    quote = candidate
                    break

        if quote:
            verified_formats.append(fmt_text)
            evidence.append({"format": fmt_text, "evidence_quote": quote})

    return verified_formats, evidence


def _collapse_whitespace_with_map(text: str) -> tuple[str, list[int], list[int]]:
    """Collapse whitespace while retaining offsets into the original text."""
    out: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    i = 0
    while i < len(text):
        if text[i].isspace():
            j = i + 1
            while j < len(text) and text[j].isspace():
                j += 1
            out.append(" ")
            starts.append(i)
            ends.append(j)
            i = j
        else:
            out.append(text[i])
            starts.append(i)
            ends.append(i + 1)
            i += 1
    return "".join(out), starts, ends


def locate_evidence(source_text: str, quote: str,
                    fallback_section: str = "",
                    line_hint: int | None = None) -> tuple[str, int | None, int | None]:
    """Locate a verified quote and return its nearest Markdown heading path and lines."""
    source_text = str(source_text or "")
    quote = str(quote or "").strip()
    if not source_text or not quote:
        return fallback_section, None, None
    normalized_quote, _, _ = _collapse_whitespace_with_map(quote)

    # New extraction records carry an exact global source-line hint. Prefer it
    # when available so repeated generic phrases resolve to the correct section.
    search_offset = 0
    if isinstance(line_hint, int) and line_hint > 0:
        line_starts = [0] + [m.end() for m in re.finditer(r"\n", source_text)]
        if line_hint - 1 < len(line_starts):
            search_offset = line_starts[line_hint - 1]

    search_text = source_text[search_offset:]
    normalized_source, starts, ends = _collapse_whitespace_with_map(search_text)
    position = normalized_source.find(normalized_quote)
    if position < 0 and search_offset:
        search_offset = 0
        normalized_source, starts, ends = _collapse_whitespace_with_map(source_text)
        position = normalized_source.find(normalized_quote)
    if position < 0 or not normalized_quote:
        return fallback_section, None, None

    original_start = search_offset + starts[position]
    original_end = search_offset + ends[position + len(normalized_quote) - 1]
    heading_stack: list[tuple[int, str]] = []
    for match in re.finditer(r"^(#{1,6})[ \t]+(.+?)\s*$", source_text[:original_start], re.MULTILINE):
        level = len(match.group(1))
        heading = match.group(2).strip().rstrip("#").strip()
        while heading_stack and heading_stack[-1][0] >= level:
            heading_stack.pop()
        heading_stack.append((level, heading))

    section = " / ".join(x[1] for x in heading_stack) or fallback_section
    line_start = source_text.count("\n", 0, original_start) + 1
    line_end = source_text.count("\n", 0, max(original_start, original_end - 1)) + 1
    return section, line_start, line_end

def _validate_data_type_formats(record: dict, chunk: Any, file_name: str,
                                kind: str, issues: list[dict]) -> dict:
    """Keep only formats that have their own verifiable source evidence."""
    out = dict(record)
    name = str(out.get("name") or out.get("data_type") or "").strip()
    formats = out.get("formats", [])
    if not isinstance(formats, list):
        formats = []

    known = _known_format_names()
    if name and (_format_forms(name) & known):
        if name not in formats:
            formats.append(name)

    verified, evidence = resolve_format_evidence(out, chunk.text, formats)
    dropped = [str(x) for x in formats if str(x) not in verified]
    for fmt in dropped:
        issues.append({
            "file": file_name, "section": chunk.section,
            "reason": f"{kind}文件格式 {fmt} 缺少与该数据语义对应的原文证据，已从候选中移除",
            "record_preview": name[:100],
        })
    out["formats"] = verified
    out["format_evidence"] = evidence
    return out


def validate_chunk_extraction(obj: dict, chunk: Any, file_name: str) -> tuple[dict, list[dict]]:
    """Keep only records with evidence verifiably present in the source chunk."""
    issues: list[dict] = []
    clean = {"tool": obj.get("tool") if isinstance(obj.get("tool"), dict) else {},
             "resources": [], "tool_parameters": [], "operations": [], "data_types": [],
             "tool_relations": [], "quality_controls": []}

    def valid_record(record: Any, kind: str) -> dict | None:
        if not isinstance(record, dict):
            issues.append({"file": file_name, "section": chunk.section, "reason": f"{kind}记录不是对象"})
            return None
        quote = str(record.get("evidence_quote") or "").strip()
        if not _quote_in_chunk(quote, chunk.text):
            issues.append({"file": file_name, "section": chunk.section,
                           "reason": f"{kind}缺少可在原文中验证的 evidence_quote",
                           "record_preview": str(record.get("name") or record.get("target_tool") or "")[:100]})
            return None
        out = dict(record)
        source_section, line_start, line_end = locate_evidence(
            chunk.text, quote, chunk.section
        )
        out["_source_file"] = file_name
        out["_source_section"] = source_section
        out["_start_line"] = chunk.start_line if line_start is None else (chunk.start_line + line_start - 1)
        out["_end_line"] = (chunk.end_line if line_end is None else (chunk.start_line + line_end - 1))
        return out

    for key, kind in [("resources", "资源"), ("tool_parameters", "工具级参数"), ("operations", "Operation"),
                      ("data_types", "DataType"), ("tool_relations", "工具关系"),
                      ("quality_controls", "质量控制")]:
        values = obj.get(key, [])
        if not isinstance(values, list):
            issues.append({"file": file_name, "section": chunk.section, "reason": f"{key}不是数组"})
            continue
        for value in values:
            item = valid_record(value, kind)
            if item is None:
                continue
            if key == "data_types":
                item = _validate_data_type_formats(item, chunk, file_name, kind, issues)
            # Validate nested claims separately. An operation can survive while
            # unsupported input/output/parameter claims are removed.
            if key == "operations":
                op_name = str(item.get("name") or "").strip()
                if op_name and _norm_quote(op_name) not in _norm_quote(str(item.get("evidence_quote") or "")):
                    issues.append({"file": file_name, "section": chunk.section,
                                   "reason": "Operation 名称未出现在其证据原文中，已忽略该候选",
                                   "record_preview": op_name[:100]})
                    continue
                for nested_key, nested_kind in [("inputs", "输入"), ("outputs", "输出"), ("parameters", "参数")]:
                    nested = item.get(nested_key, [])
                    if not isinstance(nested, list):
                        item[nested_key] = []
                        continue
                    checked = []
                    for child in nested:
                        child_item = valid_record(child, f"{item.get('name','Operation')}的{nested_kind}")
                        if child_item is not None:
                            child_item = _validate_data_type_formats(
                                child_item, chunk, file_name, f"{item.get('name','Operation')}的{nested_kind}", issues
                            )
                            if nested_kind == "参数":
                                flag = child_item.get("flag")
                                if flag and _norm_quote(str(flag)) not in _norm_quote(chunk.text):
                                    child_item["flag"] = None
                                    issues.append({"file": file_name, "section": chunk.section,
                                                   "reason": f"参数标记 {flag} 未在原文片段中找到，已清空"})
                            elif nested_kind in {"输入", "输出"}:
                                flag = child_item.get("flag")
                                child_quote = str(child_item.get("evidence_quote") or "")
                                flag_quote = str(child_item.get("flag_evidence_quote") or "")
                                operation_quote = str(item.get("evidence_quote") or "")
                                # Semantic evidence and CLI-flag evidence are two
                                # different claims. Prefer an explicit flag quote;
                                # otherwise accept the exact Operation command quote
                                # when it contains the flag. This prevents valid -o
                                # flags from being dropped just because the output
                                # description itself does not repeat the option.
                                if flag:
                                    if not (_quote_in_chunk(flag_quote, chunk.text) and
                                            _norm_quote(str(flag)) in _norm_quote(flag_quote)):
                                        if (_quote_in_chunk(child_quote, chunk.text) and
                                                _norm_quote(str(flag)) in _norm_quote(child_quote)):
                                            flag_quote = child_quote
                                        elif (_quote_in_chunk(operation_quote, chunk.text) and
                                              _norm_quote(str(flag)) in _norm_quote(operation_quote)):
                                            flag_quote = operation_quote
                                        else:
                                            child_item["flag"] = None
                                            flag_quote = ""
                                            issues.append({
                                                "file": file_name, "section": chunk.section,
                                                "reason": f"{item.get('name','Operation')} 的{nested_kind}端口 flag={flag} 在端口及 Operation 命令证据中均未找到，已清空",
                                                "record_preview": str(child_item.get("data_type") or "")[:100],
                                            })
                                    if flag_quote:
                                        child_item["flag_evidence_quote"] = flag_quote
                                minimum = child_item.get("min_occurs")
                                maximum = child_item.get("max_occurs")
                                if minimum is not None and (not isinstance(minimum, int) or isinstance(minimum, bool) or minimum < 0):
                                    child_item["min_occurs"] = None
                                    issues.append({"file": file_name, "section": chunk.section,
                                                   "reason": f"{nested_kind}端口 min_occurs 非法，已清空"})
                                if maximum is not None and (not isinstance(maximum, int) or isinstance(maximum, bool) or maximum < 0):
                                    child_item["max_occurs"] = None
                                    issues.append({"file": file_name, "section": chunk.section,
                                                   "reason": f"{nested_kind}端口 max_occurs 非法，已清空"})
                                minimum = child_item.get("min_occurs")
                                maximum = child_item.get("max_occurs")
                                if minimum is not None and maximum is not None and maximum < minimum:
                                    child_item["min_occurs"] = None
                                    child_item["max_occurs"] = None
                                    issues.append({"file": file_name, "section": chunk.section,
                                                   "reason": f"{nested_kind}端口 max_occurs 小于 min_occurs，两个数量约束已清空"})
                                scenario_id = child_item.get("scenario_id")
                                if scenario_id is not None and not re.fullmatch(r"[a-z0-9]+(?:_[a-z0-9]+)*", str(scenario_id)):
                                    child_item["scenario_id"] = None
                                    issues.append({"file": file_name, "section": chunk.section,
                                                   "reason": f"{nested_kind}端口 scenario_id 格式非法，已清空"})
                            checked.append(child_item)
                    item[nested_key] = checked
                scenarios = item.get("scenarios", [])
                if not isinstance(scenarios, list):
                    item["scenarios"] = []
                    issues.append({"file": file_name, "section": chunk.section,
                                   "reason": f"{op_name} 的 scenarios 不是数组，已清空"})
                else:
                    checked_scenarios = []
                    for scenario in scenarios:
                        scenario_item = valid_record(scenario, f"{op_name}的场景")
                        if scenario_item is None:
                            continue
                        scenario_id = str(scenario_item.get("scenario_id") or "").strip()
                        if not re.fullmatch(r"[a-z0-9]+(?:_[a-z0-9]+)*", scenario_id):
                            issues.append({"file": file_name, "section": chunk.section,
                                           "reason": f"{op_name} 的场景缺少合法 scenario_id，已忽略该场景"})
                            continue
                        checked_scenarios.append(scenario_item)
                    item["scenarios"] = checked_scenarios
                min_files = item.get("min_input_files")
                if min_files is not None and (not isinstance(min_files, int) or min_files < 1):
                    item["min_input_files"] = None
            elif key == "tool_parameters":
                flag = item.get("flag")
                if flag and _norm_quote(str(flag)) not in _norm_quote(chunk.text):
                    item["flag"] = None
                    issues.append({"file": file_name, "section": chunk.section,
                                   "reason": f"工具级参数标记 {flag} 未在原文片段中找到，已清空"})
            elif key == "tool_relations":
                target = str(item.get("target_tool") or "").strip()
                if target and _norm_quote(target) not in _norm_quote(str(item.get("evidence_quote") or "")):
                    issues.append({"file": file_name, "section": chunk.section,
                                   "reason": f"关系目标 {target} 未出现在证据原文中，忽略该关系"})
                    continue
            clean[key].append(item)

    # Tool fields are accepted only when they can be matched to text in the chunk.
    tool = clean["tool"]
    tool_quote = str(tool.get("evidence_quote") or "").strip()
    if tool_quote and not _quote_in_chunk(tool_quote, chunk.text):
        issues.append({"file": file_name, "section": chunk.section, "reason": "tool 元数据 evidence_quote 未在原文中匹配"})
        tool.clear()
    for key, value in list(tool.items()):
        if value is None or value == "":
            continue
        if not _quote_in_chunk(str(value), chunk.text) and key not in {"description", "evidence_quote"}:
            # Do not reject descriptions because the model may normalize prose;
            # builder still prefers deterministic Markdown fields where present.
            issues.append({"file": file_name, "section": chunk.section,
                           "reason": f"tool.{key} 未能在当前片段中直接匹配，忽略该字段"})
            tool[key] = None
    return clean, issues


