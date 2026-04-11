#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import re
import shutil
import ssl
import sys
from dataclasses import dataclass
from html import unescape
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

import certifi
import pandas as pd

DEFAULT_CYCLE = "2017-2018"
HTTP_TIMEOUT_SECONDS = 120
USER_AGENT = "FHIR-nhanes-seeds/0.1"

PATIENT_FIELDS: tuple[str, ...] = (
    "RIAGENDR",
    "RIDAGEYR",
    "RIDRETH3",
    "DMDBORN4",
    "DMDCITZN",
    "DMDMARTL",
    "RIDEXPRG",
)

PATIENT_JSON_KEYS = {
    "RIAGENDR": "gender",
    "RIDAGEYR": "age_years",
    "RIDRETH3": "race_ethnicity",
    "DMDBORN4": "country_of_birth",
    "DMDCITZN": "citizenship_status",
    "DMDMARTL": "marital_status",
    "RIDEXPRG": "pregnancy_status",
}

SKIP_LABEL_FRAGMENTS = (
    "comment",
    "status code",
    "component status",
    "sample weight",
    "cuff size",
    "arm selected",
    "pulse regular or irregular",
    "pulse type",
    "enhancement used",
    "maximum inflation",
    "respondent sequence number",
)

NON_INFORMATIVE_CODES = {
    "refused",
    "don't know",
    "cannot be determined",
    "cannot be assessed",
    "missing",
    "blank but applicable",
}

OBSERVATION_CAUTION_NOTES = {
    ("BIOPRO_J", "LBXSGL"): (
        "NHANES analytic notes prefer the reference-method glucose file (GLU_J) over the "
        "standard biochemistry glucose value."
    ),
    ("BIOPRO_J", "LBXSCH"): (
        "NHANES analytic notes prefer the reference-method cholesterol file (TCHOL_J) over "
        "the standard biochemistry cholesterol value."
    ),
    ("BIOPRO_J", "LBXSTR"): (
        "NHANES analytic notes prefer the reference-method triglyceride file (TRIGLY_J) over "
        "the standard biochemistry triglyceride value."
    ),
}


@dataclass(frozen=True)
class SourceFileConfig:
    component: str
    file_code: str
    title: str
    likely_fhir_resource: str


@dataclass(frozen=True)
class CycleConfig:
    cycle: str
    release_path: str
    files: tuple[SourceFileConfig, ...]


@dataclass
class VariableMetadata:
    variable_name: str
    label: str
    english_text: str
    unit: str
    code_map: dict[str, str]


CYCLE_CONFIGS = {
    "2017-2018": CycleConfig(
        cycle="2017-2018",
        release_path="https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2017/DataFiles",
        files=(
            SourceFileConfig(
                component="Demographics",
                file_code="DEMO_J",
                title="Demographic Variables and Sample Weights",
                likely_fhir_resource="Patient",
            ),
            SourceFileConfig(
                component="Examination",
                file_code="BMX_J",
                title="Body Measures",
                likely_fhir_resource="Observation",
            ),
            SourceFileConfig(
                component="Examination",
                file_code="BPX_J",
                title="Blood Pressure",
                likely_fhir_resource="Observation",
            ),
            SourceFileConfig(
                component="Laboratory",
                file_code="GHB_J",
                title="Glycohemoglobin",
                likely_fhir_resource="Observation",
            ),
            SourceFileConfig(
                component="Laboratory",
                file_code="TCHOL_J",
                title="Total Cholesterol",
                likely_fhir_resource="Observation",
            ),
            SourceFileConfig(
                component="Laboratory",
                file_code="BIOPRO_J",
                title="Standard Biochemistry Profile",
                likely_fhir_resource="Observation",
            ),
        ),
    )
}


def get_cycle_config(cycle: str) -> CycleConfig:
    if cycle not in CYCLE_CONFIGS:
        raise ValueError(f"Unsupported cycle: {cycle}")
    return CYCLE_CONFIGS[cycle]


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def cycle_slug(cycle: str) -> str:
    return cycle.lower().replace(" ", "_").replace("-", "_")


def raw_cycle_dir(cycle: str) -> Path:
    return repo_root() / "data" / "raw" / "nhanes" / cycle_slug(cycle)


def processed_cycle_dir(cycle: str) -> Path:
    return repo_root() / "data" / "processed" / "nhanes" / cycle_slug(cycle)


def outputs_dir() -> Path:
    return repo_root() / "outputs" / "nhanes"


def ensure_standard_directories(cycle: str) -> None:
    raw_cycle_dir(cycle).mkdir(parents=True, exist_ok=True)
    processed_cycle_dir(cycle).mkdir(parents=True, exist_ok=True)
    outputs_dir().mkdir(parents=True, exist_ok=True)


def local_paths_for_source(cycle: str, source: SourceFileConfig) -> dict[str, Path]:
    base_dir = raw_cycle_dir(cycle) / source.component.lower()
    base_dir.mkdir(parents=True, exist_ok=True)
    return {
        "xpt": base_dir / f"{source.file_code}.xpt",
        "doc": base_dir / f"{source.file_code}.htm",
    }


def source_urls(cycle: str, source: SourceFileConfig) -> dict[str, str]:
    config = get_cycle_config(cycle)
    base = config.release_path
    return {
        "xpt": f"{base}/{source.file_code}.xpt",
        "doc": f"{base}/{source.file_code}.htm",
    }


def download_url(url: str, destination: Path, force: bool = False) -> None:
    if destination.exists() and not force:
        return

    destination.parent.mkdir(parents=True, exist_ok=True)
    request = Request(url, headers={"User-Agent": USER_AGENT})
    verified_context = ssl.create_default_context(cafile=certifi.where())

    try:
        with urlopen(request, timeout=HTTP_TIMEOUT_SECONDS, context=verified_context) as response, destination.open(
            "wb"
        ) as handle:
            shutil.copyfileobj(response, handle)
        return
    except URLError as error:
        root_cause = getattr(error, "reason", error)
        if not isinstance(root_cause, ssl.SSLError):
            raise
        print(
            f"warning: verified SSL download failed for {url}; retrying with unverified SSL for this public NHANES file",
            file=sys.stderr,
        )

    insecure_context = ssl._create_unverified_context()
    with urlopen(request, timeout=HTTP_TIMEOUT_SECONDS, context=insecure_context) as response, destination.open(
        "wb"
    ) as handle:
        shutil.copyfileobj(response, handle)


def load_xpt_frame(cycle: str, source: SourceFileConfig) -> pd.DataFrame:
    xpt_path = local_paths_for_source(cycle, source)["xpt"]
    if not xpt_path.exists():
        raise FileNotFoundError(f"Missing NHANES data file: {xpt_path}")

    frame = pd.read_sas(str(xpt_path), format="xport", encoding="utf-8")
    frame.columns = [decode_text(column) for column in frame.columns]
    return frame


def decode_text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="ignore")
    return str(value)


def clean_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def clean_html_fragment(fragment: str, preserve_newlines: bool = False) -> str:
    text = re.sub(r"(?i)<br\s*/?>", "\n", fragment)
    text = re.sub(r"(?i)</(p|div|li|tr|h1|h2|h3|h4|h5|h6|td|th)>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    if preserve_newlines:
        text = re.sub(r"\r", "", text)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()
    return clean_whitespace(text)


def load_doc_metadata(cycle: str, source: SourceFileConfig) -> dict[str, VariableMetadata]:
    doc_path = local_paths_for_source(cycle, source)["doc"]
    if not doc_path.exists():
        raise FileNotFoundError(f"Missing NHANES documentation file: {doc_path}")

    html = doc_path.read_text(encoding="utf-8", errors="ignore")
    heading_matches = list(re.finditer(r"<h[1-6][^>]*>\s*(.*?)\s*</h[1-6]>", html, re.IGNORECASE | re.DOTALL))

    metadata: dict[str, VariableMetadata] = {}
    for index, match in enumerate(heading_matches):
        heading_text = clean_html_fragment(match.group(1))
        if " - " not in heading_text:
            continue

        variable_name, heading_label = [part.strip() for part in heading_text.split(" - ", 1)]
        if not re.fullmatch(r"[A-Z0-9_]+", variable_name):
            continue

        next_start = heading_matches[index + 1].start() if index + 1 < len(heading_matches) else len(html)
        block = html[match.end() : next_start]
        code_map = extract_code_map(block)
        english_text = extract_named_text(block, "English Text") or heading_label
        label = extract_named_text(block, "SAS Label") or heading_label
        unit = extract_unit_from_label(label)

        metadata[variable_name] = VariableMetadata(
            variable_name=variable_name,
            label=clean_whitespace(label),
            english_text=clean_whitespace(english_text),
            unit=unit,
            code_map=code_map,
        )

    return metadata


def extract_named_text(block: str, field_name: str) -> str:
    pattern = re.compile(
        rf"<dt[^>]*>\s*{re.escape(field_name)}:\s*</dt>\s*<dd[^>]*>(.*?)</dd>",
        re.IGNORECASE | re.DOTALL,
    )
    match = pattern.search(block)
    if not match:
        return ""
    return clean_html_fragment(match.group(1))


def extract_code_map(block: str) -> dict[str, str]:
    rows: list[list[str]] = []
    for table_html in re.findall(r"<table[^>]*>(.*?)</table>", block, re.IGNORECASE | re.DOTALL):
        table_rows: list[list[str]] = []
        for row_html in re.findall(r"<tr[^>]*>(.*?)</tr>", table_html, re.IGNORECASE | re.DOTALL):
            cells = [
                clean_html_fragment(cell)
                for cell in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row_html, re.IGNORECASE | re.DOTALL)
            ]
            cells = [cell for cell in cells if cell]
            if cells:
                table_rows.append(cells)

        if not table_rows:
            continue

        header = [cell.lower() for cell in table_rows[0]]
        if "code or value" in header[0] and any("value description" in cell for cell in header):
            rows = table_rows[1:]
            break

    code_map: dict[str, str] = {}
    for row in rows:
        if len(row) < 2:
            continue
        key = clean_whitespace(row[0])
        value = clean_whitespace(row[1])
        if key and value:
            code_map[key] = value
    return code_map


def looks_like_unit(candidate: str) -> bool:
    if not candidate:
        return False
    candidate = candidate.strip()
    if len(candidate) > 20:
        return False
    unit_markers = ("/", "%", "kg", "cm", "mm", "g", "mol", "eq", "iu", "u/", "hg", "dl", "l")
    lowered = candidate.lower()
    return any(marker in lowered for marker in unit_markers)


def extract_unit_from_label(label: str) -> str:
    match = re.search(r"\(([^()]+)\)\s*$", label)
    if match and looks_like_unit(match.group(1)):
        return match.group(1).replace("**", "^").strip()

    tail_match = re.search(
        r"(mm Hg|mg/dL|mmol/L|g/dL|g/L|ug/dL|ug/L|ng/mL|pg/mL|IU/L|U/L|mEq/L|cm|kg|%)$",
        label,
        re.IGNORECASE,
    )
    if tail_match:
        return tail_match.group(1)
    return ""


def label_without_unit(label: str, unit: str) -> str:
    if not unit:
        return clean_whitespace(label)

    escaped_unit = re.escape(unit).replace(r"\ ", r"\s+")
    label = re.sub(rf"\s*\({escaped_unit}\)\s*$", "", label, flags=re.IGNORECASE)
    label = re.sub(rf"\s+{escaped_unit}\s*$", "", label, flags=re.IGNORECASE)
    return clean_whitespace(label.replace("kg/m**2", "kg/m^2"))


def canonical_measure_name(label: str, variable_name: str, unit: str) -> str:
    name = label_without_unit(label or variable_name, unit)
    name = re.sub(r"\((?:1st|2nd|3rd|4th)\s+rdg\)", "", name, flags=re.IGNORECASE)
    name = clean_whitespace(name.strip(" :-"))
    return name or variable_name


def normalize_scalar(value: Any) -> Any:
    if value is None:
        return None

    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass

    if hasattr(value, "item"):
        try:
            value = value.item()
        except ValueError:
            pass

    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="ignore")

    if isinstance(value, str):
        value = clean_whitespace(value)
        return value or None

    if isinstance(value, float):
        if math.isnan(value):
            return None
        if value.is_integer():
            return int(value)
        return round(value, 4)

    return value


def participant_id_from_value(value: Any) -> str:
    normalized = normalize_scalar(value)
    if normalized is None:
        return ""
    if isinstance(normalized, float) and normalized.is_integer():
        normalized = int(normalized)
    return str(normalized)


def decode_categorical_value(raw_value: Any, metadata: VariableMetadata | None) -> Any:
    normalized = normalize_scalar(raw_value)
    if normalized is None:
        return None

    if not metadata or not metadata.code_map:
        return normalized

    candidate_keys = {str(normalized)}
    if isinstance(normalized, int):
        candidate_keys.add(f"{normalized}.0")
    if isinstance(normalized, float) and normalized.is_integer():
        candidate_keys.add(str(int(normalized)))

    for key in candidate_keys:
        if key in metadata.code_map:
            return metadata.code_map[key]
    return normalized


def is_non_informative_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        lowered = value.lower()
        return any(token in lowered for token in NON_INFORMATIVE_CODES)
    return False


def is_numeric_value(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def should_keep_observation_variable(
    source: SourceFileConfig,
    variable_name: str,
    series: pd.Series,
    metadata: VariableMetadata | None,
) -> tuple[bool, str]:
    label = (metadata.label if metadata else variable_name).lower()
    upper_name = variable_name.upper()

    if upper_name == "SEQN":
        return False, "participant_id"
    if not pd.api.types.is_numeric_dtype(series):
        return False, "non_numeric"
    if upper_name.endswith("LC"):
        return False, "comment_code"
    if source.component == "Laboratory" and upper_name.endswith("SI"):
        return False, "derived_si_duplicate"
    if upper_name.startswith(("WT", "WTS", "SDMV", "PEASC", "BPAEN", "BPACS", "BPAARM", "BMD", "BMI")):
        return False, "context_or_weight"
    if any(fragment in label for fragment in SKIP_LABEL_FRAGMENTS):
        return False, "context_label"
    return True, "selected"


def measurement_review_note(source: SourceFileConfig, variable_name: str) -> str:
    if (source.file_code, variable_name) in OBSERVATION_CAUTION_NOTES:
        return OBSERVATION_CAUTION_NOTES[(source.file_code, variable_name)]
    if variable_name.startswith(("BPXSY", "BPXDI")):
        return "Keep the original NHANES reading index so repeated blood pressure readings stay distinct."
    return ""


def observation_needs_linked_context(source: SourceFileConfig, variable_name: str) -> bool:
    return (source.file_code, variable_name) in OBSERVATION_CAUTION_NOTES


def measurement_mapping_notes(source: SourceFileConfig, variable_name: str, measure_name: str) -> str:
    note = (
        f"Observation candidate from {source.file_code} ({source.title}); "
        f"retain the NHANES source variable {variable_name} and semi-structured measurement phrasing."
    )
    if variable_name.startswith(("BPXSY", "BPXDI")):
        return note + " Preserve the reading index during later pairing."
    return note


def build_patient_candidates(
    cycle: str,
    source: SourceFileConfig,
    frame: pd.DataFrame,
    metadata: dict[str, VariableMetadata],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    available_fields = [field for field in PATIENT_FIELDS if field in frame.columns]

    for _, record in frame.iterrows():
        participant_id = participant_id_from_value(record.get("SEQN"))
        if not participant_id:
            continue

        structured_payload: dict[str, Any] = {}
        display_parts: list[str] = []
        review_parts: list[str] = []

        for field in available_fields:
            raw_value = record.get(field)
            field_meta = metadata.get(field)
            decoded = decode_categorical_value(raw_value, field_meta)
            if is_non_informative_value(decoded):
                continue

            label = field_meta.label if field_meta else field
            json_key = PATIENT_JSON_KEYS.get(field, field.lower())

            if field == "RIDAGEYR":
                age_value = normalize_scalar(raw_value)
                if age_value is None:
                    continue
                structured_payload[json_key] = age_value
                display_parts.append(f"{label}={age_value} years")
                if age_value == 80:
                    review_parts.append("RIDAGEYR is top-coded at 80 in the public NHANES release.")
                continue

            structured_payload[json_key] = decoded
            display_parts.append(f"{label}={decoded}")

        has_core_demographics = "gender" in structured_payload or "age_years" in structured_payload
        if len(structured_payload) < 3 or not has_core_demographics:
            continue

        json_ready = True
        needs_linked_context = len(structured_payload) < 4
        good_for_pairing = (
            len(structured_payload) >= 4
            and "gender" in structured_payload
            and "age_years" in structured_payload
        )
        complexity_guess = "low" if len(structured_payload) >= 5 else "medium"
        mapping_notes = (
            "Partial Patient seed from NHANES demographics; keep age as source-side realism "
            "because public NHANES does not expose full birth dates."
        )

        rows.append(
            {
                "candidate_id": f"patient-{source.file_code}-{participant_id}",
                "source_component": source.component,
                "source_file": f"{source.file_code}.xpt",
                "variable_name_or_measure_name": "patient_demographics_bundle",
                "participant_id_if_available": participant_id,
                "likely_fhir_resource": "Patient",
                "candidate_text_snippet": " | ".join(
                    [f"cycle={cycle}", f"participant={participant_id}", *display_parts]
                ),
                "structured_value": json.dumps(structured_payload, ensure_ascii=True, sort_keys=True),
                "unit_if_available": "",
                "json_ready": json_ready,
                "likely_numeric": False,
                "needs_linked_context": needs_linked_context,
                "complexity_guess": complexity_guess,
                "good_for_pairing": good_for_pairing,
                "mapping_notes": mapping_notes,
                "review_notes": " ".join(review_parts),
            }
        )

    return rows


def build_observation_candidates(
    cycle: str,
    source: SourceFileConfig,
    frame: pd.DataFrame,
    metadata: dict[str, VariableMetadata],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for variable_name in frame.columns:
        field_meta = metadata.get(
            variable_name,
            VariableMetadata(
                variable_name=variable_name,
                label=variable_name,
                english_text=variable_name,
                unit="",
                code_map={},
            ),
        )

        keep, _ = should_keep_observation_variable(source, variable_name, frame[variable_name], field_meta)
        if not keep:
            continue

        measure_name = canonical_measure_name(field_meta.label, variable_name, field_meta.unit)
        review_note = measurement_review_note(source, variable_name)
        needs_linked_context = observation_needs_linked_context(source, variable_name)

        for row_index, raw_value in frame[variable_name].items():
            normalized = normalize_scalar(raw_value)
            if normalized is None:
                continue

            participant_id = participant_id_from_value(frame.at[row_index, "SEQN"]) if "SEQN" in frame.columns else ""
            structured_payload = {
                "cycle": cycle,
                "participant_id": participant_id,
                "source_file": source.file_code,
                "source_variable": variable_name,
                "measure_name": measure_name,
                "value": normalized,
            }
            if field_meta.unit:
                structured_payload["unit"] = field_meta.unit

            json_ready = True
            good_for_pairing = bool(
                is_numeric_value(normalized)
                and field_meta.unit
                and not needs_linked_context
            )
            complexity_guess = "low" if good_for_pairing else "medium"

            candidate_parts = [
                f"cycle={cycle}",
                f"participant={participant_id}" if participant_id else "",
                f"file={source.file_code}",
                f"variable={variable_name}",
                f"measure={measure_name}",
                f"value={normalized}",
            ]
            if field_meta.unit:
                candidate_parts.append(f"unit={field_meta.unit}")

            rows.append(
                {
                    "candidate_id": f"obs-{source.file_code}-{variable_name}-{participant_id or row_index}",
                    "source_component": source.component,
                    "source_file": f"{source.file_code}.xpt",
                    "variable_name_or_measure_name": f"{variable_name}: {measure_name}",
                    "participant_id_if_available": participant_id,
                    "likely_fhir_resource": "Observation",
                    "candidate_text_snippet": " | ".join(part for part in candidate_parts if part),
                    "structured_value": json.dumps(structured_payload, ensure_ascii=True, sort_keys=True),
                    "unit_if_available": field_meta.unit,
                    "json_ready": json_ready,
                    "likely_numeric": is_numeric_value(normalized),
                    "needs_linked_context": needs_linked_context,
                    "complexity_guess": complexity_guess,
                    "good_for_pairing": good_for_pairing,
                    "mapping_notes": measurement_mapping_notes(source, variable_name, measure_name),
                    "review_notes": review_note,
                }
            )

    return rows


def variable_name_from_display(value: str) -> str:
    if value == "patient_demographics_bundle":
        return value
    if ":" not in value:
        return value
    return value.split(":", 1)[0].strip()


def measure_name_from_display(value: str) -> str:
    if value == "patient_demographics_bundle":
        return value
    if ":" not in value:
        return value
    return value.split(":", 1)[1].strip()


def build_variable_profile_rows(
    cycle: str,
    source: SourceFileConfig,
    frame: pd.DataFrame,
    metadata: dict[str, VariableMetadata],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    if source.component == "Demographics":
        for field in PATIENT_FIELDS:
            if field not in frame.columns:
                continue
            field_meta = metadata.get(
                field,
                VariableMetadata(
                    variable_name=field,
                    label=field,
                    english_text=field,
                    unit="",
                    code_map={},
                ),
            )
            series = frame[field]
            rows.append(
                {
                    "cycle": cycle,
                    "source_component": source.component,
                    "source_file": f"{source.file_code}.xpt",
                    "variable_name": field,
                    "variable_label": field_meta.label,
                    "unit_if_available": field_meta.unit,
                    "likely_fhir_resource": "Patient",
                    "non_null_count": int(series.notna().sum()),
                    "unique_non_null_count": int(series.dropna().nunique()),
                    "default_json_ready": True,
                    "default_needs_linked_context": False,
                    "default_complexity_guess": "medium",
                    "default_good_for_pairing": field in {"RIAGENDR", "RIDAGEYR", "RIDRETH3", "DMDBORN4"},
                    "selection_reason": "Bundled into a Patient-like demographic slice rather than emitted alone.",
                    "mapping_notes": "Used as part of the Patient demographics bundle.",
                }
            )
        return rows

    for variable_name in frame.columns:
        field_meta = metadata.get(
            variable_name,
            VariableMetadata(
                variable_name=variable_name,
                label=variable_name,
                english_text=variable_name,
                unit="",
                code_map={},
            ),
        )
        keep, selection_reason = should_keep_observation_variable(source, variable_name, frame[variable_name], field_meta)
        if not keep:
            continue

        review_note = measurement_review_note(source, variable_name)
        needs_linked_context = observation_needs_linked_context(source, variable_name)
        measure_name = canonical_measure_name(field_meta.label, variable_name, field_meta.unit)
        series = frame[variable_name]

        rows.append(
            {
                "cycle": cycle,
                "source_component": source.component,
                "source_file": f"{source.file_code}.xpt",
                "variable_name": variable_name,
                "variable_label": measure_name,
                "unit_if_available": field_meta.unit,
                "likely_fhir_resource": "Observation",
                "non_null_count": int(series.notna().sum()),
                "unique_non_null_count": int(series.dropna().nunique()),
                "default_json_ready": True,
                "default_needs_linked_context": needs_linked_context,
                "default_complexity_guess": "low" if field_meta.unit and not needs_linked_context else "medium",
                "default_good_for_pairing": bool(field_meta.unit and not needs_linked_context),
                "selection_reason": selection_reason,
                "mapping_notes": review_note or measurement_mapping_notes(source, variable_name, measure_name),
            }
        )

    return rows


def collect_cycle_artifacts(cycle: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    config = get_cycle_config(cycle)
    candidate_rows: list[dict[str, Any]] = []
    variable_profile_rows: list[dict[str, Any]] = []

    for source in config.files:
        frame = load_xpt_frame(cycle, source)
        metadata = load_doc_metadata(cycle, source)
        variable_profile_rows.extend(build_variable_profile_rows(cycle, source, frame, metadata))

        if source.component == "Demographics":
            candidate_rows.extend(build_patient_candidates(cycle, source, frame, metadata))
        else:
            candidate_rows.extend(build_observation_candidates(cycle, source, frame, metadata))

    return candidate_rows, variable_profile_rows
