import os
import json
import time
import yaml
import gspread
from pathlib import Path
from google.oauth2.service_account import Credentials

# --- CONFIGURATION ---
SPREADSHEET_NAME = "RAG Refined Strategies"

PARTS = ["NIST_Part1"]
VERSIONS = ["v6"]

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
                lines.append(
                    f"    - Toolpath Style: {tp.get('tool_path_style', 'N/A')}"
                )

                tools = tp.get("tool_types", [])
                if tools:
                    lines.append(f"    - Tool Types: {', '.join(tools)}")
        lines.append("")  # Spacer between passes

    return "\n".join(lines).strip()


# --- CORE LOGIC ---


def compile_data():
    client = get_client()

    # Open existing or create new (Quota Safe)
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

        # Rule 1: Always use the first run for the refined strategies column
        run_id_1 = runs[0]

        # Read Feature JSON
        features_path = os.path.join(INPUTS_DIR, file_config["features"])
        features_list = read_json_obj(features_path)
        if not features_list:
            continue

        # Read Rationale JSON (KB Strategies + Rationale)
        rationale_path = os.path.join(RATIONALE_DIR, f"{part}_rationale.json")
        rationale_data = read_json_obj(rationale_path) or {}
        if not rationale_data:
            print(
                f"  [Warn] No rationale data found for part {part}. Will leave KB columns blank."
            )

        for version in VERSIONS:
            tab_title = f"{part}_{version}_strategies"
            print(f"Processing Tab: {tab_title}...")

            # Read Refined Strategies JSON (Column 4)
            strat_file_1 = os.path.join(
                OUTPUTS_DIR, version, f"refined_strategies_run_{run_id_1}.json"
            )
            strat_data_1 = read_json_obj(strat_file_1) or {}

            # --- BUILD SHEET DATA ---
            sheet_data = []

            # 1. HEADERS
            headers = [
                "Feature Details",
                "KB Strategies",
                "Rationale generated",
                "Refined strategies",
            ]
            sheet_data.append(headers)

            # 2. FEATURE ROWS
            for feat in features_list:
                fid = feat.get("feature_id")

                # Get the data for the specific feature ID
                kb_feature_data = rationale_data.get(fid, {})
                refined_feature_data = strat_data_1.get(fid, {})

                # Format Columns
                col_feature = format_feature_details(feat)

                # The format_refined_strategy expects an object with a "passes" key,
                # which aligns perfectly with how the kb_feature_data is structured.
                col_kb_strat = format_refined_strategy(kb_feature_data)

                # Extract the rationale directly
                col_rationale = kb_feature_data.get(
                    "rationale", "No rationale available."
                )

                # Format the refined strategy
                col_refined_strat = format_refined_strategy(refined_feature_data)

                row = [col_feature, col_kb_strat, col_rationale, col_refined_strat]
                sheet_data.append(row)

            # --- WRITE TO GOOGLE SHEET ---
            try:
                existing_ws = sh.worksheet(tab_title[:100])
                sh.del_worksheet(existing_ws)
                time.sleep(1)
            except gspread.WorksheetNotFound:
                pass

            ws = sh.add_worksheet(
                title=tab_title[:100], rows=len(sheet_data) + 10, cols=4
            )
            ws.update(range_name=f"A1:D{len(sheet_data)}", values=sheet_data)

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
                            "endColumnIndex": 4,
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
            widths = [300, 400, 450, 400]
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
                            "endColumnIndex": 4,
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

            time.sleep(1.5)

    print("\nProcessing Complete.")


if __name__ == "__main__":
    compile_data()
