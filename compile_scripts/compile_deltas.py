import os
import json
import time
import yaml
import gspread
from pathlib import Path
from google.oauth2.service_account import Credentials

# --- CONFIGURATION ---
SPREADSHEET_NAME = "Delta of Feature level Strategies"

PARTS = [
    "NIST_Part1",
    "NIST_Part2",
    "PM0290-020-01",
    "PM0289-020-01",
    "FIXTURE-01",
    "msc_step_1",
]

PART_RUN_MAP = {
    "PM0290-020-01": ["1", "2"],
    "PM0289-020-01": ["3", "4"],
    "FIXTURE-01": ["5", "6"],
    "msc_step_1": ["7", "8"],
    "NIST_Part1": ["9", "10"],
    "NIST_Part2": ["11", "12"],
}

PART_FILES_MAP = {
    "PM0290-020-01": {"features": "features1.json"},
    "PM0289-020-01": {"features": "features2.json"},
    "FIXTURE-01": {"features": "features3.json"},
    "msc_step_1": {"features": "features4.json"},
    "NIST_Part1": {"features": "features_NIST_1.json"},
    "NIST_Part2": {"features": "features_NIST_2.json"},
}

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent
INPUTS_DIR = os.path.join(BASE_DIR, "inputs")
OUTPUTS_DIR = os.path.join(BASE_DIR, "outputs")
RATIONALE_DIR = os.path.join(OUTPUTS_DIR, "rationale", "wo_files")
DELTA_DIR = os.path.join(OUTPUTS_DIR, "delta")
V5_DIR = os.path.join(OUTPUTS_DIR, "v5")
V6_DIR = os.path.join(OUTPUTS_DIR, "v6")

# Auth
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def get_client():
    creds_path = os.path.join(BASE_DIR, "credentials.json")
    if not os.path.exists(creds_path):
        raise FileNotFoundError(
            f"CRITICAL: 'credentials.json' not found at {creds_path}"
        )
    creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    return gspread.authorize(creds)


def read_json_obj(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"  [Warn] File not found: {path}")
        return None
    except Exception as e:
        print(f"  [Error] Reading {path}: {e}")
        return None


# --- FORMATTING HELPERS ---


def format_feature_details(feat_data):
    if not feat_data:
        return ""

    ftype = feat_data.get("feature_type", "Unknown").capitalize()
    fname = feat_data.get("feature_name", "Unknown")
    cam_names = feat_data.get("cam_specific_names", [])
    info = feat_data.get("feature_info", {})

    lines = [f"Feature Type: {ftype}", f"Feature Name: {fname}"]

    if cam_names:
        lines.append(f"CAM Specific Names: {', '.join(cam_names)}")

    if info:
        lines.append("\nFeature Info:")
        lines.append(yaml.dump(info, default_flow_style=False, sort_keys=False).strip())

    return "\n".join(lines)


def format_refined_strategy(strategy_obj):
    if not strategy_obj or "passes" not in strategy_obj or not strategy_obj["passes"]:
        return "No passes / Empty strategy."

    lines = []
    for i, p in enumerate(strategy_obj["passes"], start=1):
        lines.append(f"Pass {i}: {p.get('pass', 'Unknown')}")
        for op in p.get("operations", []):
            lines.append(
                f"  Operation: {op.get('operation', 'Unknown')} ({op.get('location', 'Unknown')})"
            )
            for tp in op.get("tool_paths", []):
                lines.append(f"    - Toolpath: {tp.get('tool_path', 'N/A')}")
                lines.append(f"    - Toolpath Type: {tp.get('tool_path_type', 'N/A')}")
                lines.append(
                    f"    - Toolpath Syntax: {tp.get('tool_path_syntax', 'N/A')}"
                )
                style = tp.get("tool_path_style")
                if style:
                    lines.append(f"    - Toolpath Style: {style}")

                tools = tp.get("tool_types", [])
                if tools:
                    lines.append(f"    - Tool Types: {', '.join(tools)}")
        lines.append("")  # Spacer between passes

    return "\n".join(lines).strip()


# --- CORE LOGIC ---


def compile_data():
    client = get_client()

    # Open existing or create new Sheet
    try:
        sh = client.open(SPREADSHEET_NAME)
        print(f"Opened existing Spreadsheet: {sh.url}")
    except gspread.SpreadsheetNotFound:
        sh = client.create(SPREADSHEET_NAME)
        print(f"Created new Spreadsheet: {sh.url}")

    for part in PARTS:
        runs = PART_RUN_MAP.get(part)
        file_config = PART_FILES_MAP.get(part)

        if not runs or not file_config:
            continue

        run_id = runs[0]
        tab_title = f"{part}_Deltas"
        print(f"Processing Tab: {tab_title}...")

        # 1. Load Files
        features_path = os.path.join(INPUTS_DIR, file_config["features"])
        features_list = read_json_obj(features_path)
        if not features_list:
            continue

        kb_path = os.path.join(RATIONALE_DIR, f"{part}_rationale.json")
        v5_path = os.path.join(V5_DIR, f"refined_strategies_run_{run_id}.json")
        v6_path = os.path.join(V6_DIR, f"refined_strategies_run_{run_id}.json")
        delta_path = os.path.join(DELTA_DIR, f"{part}_delta.json")

        kb_data = read_json_obj(kb_path) or {}
        v5_data = read_json_obj(v5_path) or {}
        v6_data = read_json_obj(v6_path) or {}
        delta_data = read_json_obj(delta_path) or {}

        # --- BUILD SHEET DATA ---
        sheet_data = []

        # Headers
        headers = [
            "Feature details",
            "KB Strategies",
            "Rationale",
            "Refined Strategy (without using rationale)",
            "Refined Strategy (using rationale)",
            "Delta 1 (KB vs Refined without rationale)",
            "Delta 2 (KB vs Refined using rationale)",
            "Delta 3 (Refined w/o rationale vs Refined w/ rationale)",
        ]
        sheet_data.append(headers)

        # Populate Rows
        for feat in features_list:
            fid = feat.get("feature_id")

            # Extract Data Maps
            kb_feature = kb_data.get(fid, {})
            v5_feature = v5_data.get(fid, {})
            v6_feature = v6_data.get(fid, {})
            delta_feature = delta_data.get(fid, {})

            # Format individual columns
            col_feature = format_feature_details(feat)
            col_kb = format_refined_strategy(kb_feature)
            col_rationale = kb_feature.get("rationale", "No rationale available.")
            col_v5 = format_refined_strategy(v5_feature)
            col_v6 = format_refined_strategy(v6_feature)

            col_delta1 = delta_feature.get("delta_1", "N/A")
            col_delta2 = delta_feature.get("delta_2", "N/A")
            col_delta3 = delta_feature.get("delta_3", "N/A")

            row = [
                col_feature,
                col_kb,
                col_rationale,
                col_v5,
                col_v6,
                col_delta1,
                col_delta2,
                col_delta3,
            ]
            sheet_data.append(row)

        # --- WRITE TO GOOGLE SHEET ---
        time.sleep(1.5)  # Quota delay
        try:
            existing_ws = sh.worksheet(tab_title[:100])
            sh.del_worksheet(existing_ws)
            time.sleep(1)
        except gspread.WorksheetNotFound:
            pass

        ws = sh.add_worksheet(title=tab_title[:100], rows=len(sheet_data) + 10, cols=8)
        ws.update(range_name=f"A1:H{len(sheet_data)}", values=sheet_data)

        # --- BATCH FORMATTING ---
        batch_requests = []

        # 1. Header Style
        batch_requests.append(
            {
                "repeatCell": {
                    "range": {
                        "sheetId": ws.id,
                        "startRowIndex": 0,
                        "endRowIndex": 1,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": {
                                "red": 0.9,
                                "green": 0.9,
                                "blue": 0.9,
                            },
                            "textFormat": {
                                "bold": True,
                                "fontSize": 11,
                                "fontFamily": "Arial",
                            },
                            "horizontalAlignment": "CENTER",
                        }
                    },
                    "fields": "userEnteredFormat",
                }
            }
        )

        # 2. Text Alignment & Wrapping (All Columns)
        batch_requests.append(
            {
                "repeatCell": {
                    "range": {
                        "sheetId": ws.id,
                        "startRowIndex": 1,
                        "endRowIndex": len(sheet_data),
                        "startColumnIndex": 0,
                        "endColumnIndex": 8,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "verticalAlignment": "TOP",
                            "wrapStrategy": "WRAP",
                            "textFormat": {"fontFamily": "Arial"},
                        }
                    },
                    "fields": "userEnteredFormat(verticalAlignment,wrapStrategy,textFormat)",
                }
            }
        )

        # 3. Column Widths
        widths = [250, 300, 300, 300, 300, 280, 280, 280]
        for i, w in enumerate(widths):
            batch_requests.append(
                {
                    "updateDimensionProperties": {
                        "range": {
                            "sheetId": ws.id,
                            "dimension": "COLUMNS",
                            "startIndex": i,
                            "endIndex": i + 1,
                        },
                        "properties": {"pixelSize": w},
                        "fields": "pixelSize",
                    }
                }
            )

        # 4. Borders (Solid grid)
        batch_requests.append(
            {
                "updateBorders": {
                    "range": {
                        "sheetId": ws.id,
                        "startRowIndex": 0,
                        "endRowIndex": len(sheet_data),
                        "startColumnIndex": 0,
                        "endColumnIndex": 8,
                    },
                    "top": {
                        "style": "SOLID",
                        "width": 1,
                        "color": {"red": 0.8, "green": 0.8, "blue": 0.8},
                    },
                    "bottom": {
                        "style": "SOLID",
                        "width": 1,
                        "color": {"red": 0.8, "green": 0.8, "blue": 0.8},
                    },
                    "left": {
                        "style": "SOLID",
                        "width": 1,
                        "color": {"red": 0.8, "green": 0.8, "blue": 0.8},
                    },
                    "right": {
                        "style": "SOLID",
                        "width": 1,
                        "color": {"red": 0.8, "green": 0.8, "blue": 0.8},
                    },
                    "innerHorizontal": {
                        "style": "SOLID",
                        "width": 1,
                        "color": {"red": 0.8, "green": 0.8, "blue": 0.8},
                    },
                    "innerVertical": {
                        "style": "SOLID",
                        "width": 1,
                        "color": {"red": 0.8, "green": 0.8, "blue": 0.8},
                    },
                }
            }
        )

        if batch_requests:
            sh.batch_update({"requests": batch_requests})

        print(f"  > Tab {tab_title} format applied successfully.")

    print("\nProcessing Complete. Spreadsheet generated.")


if __name__ == "__main__":
    compile_data()
