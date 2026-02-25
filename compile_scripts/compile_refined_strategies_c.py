import os
import json
import time
import yaml
import gspread
from pathlib import Path
from google.oauth2.service_account import Credentials

# --- CONFIGURATION ---
SPREADSHEET_NAME = "LLM Refined Feature Strategies"

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


# --- BATCH REQUEST HELPERS ---


def add_dropdown_requests(requests_list, sheet_id, row_index, start_col=3, end_col=5):
    requests_list.append(
        {
            "setDataValidation": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": row_index,
                    "endRowIndex": row_index + 1,
                    "startColumnIndex": start_col,
                    "endColumnIndex": end_col,
                },
                "rule": {
                    "condition": {
                        "type": "ONE_OF_LIST",
                        "values": [
                            {"userEnteredValue": "Acceptable"},
                            {"userEnteredValue": "Rejected"},
                        ],
                    },
                    "showCustomUi": True,
                    "strict": True,
                },
            }
        }
    )


def add_conditional_formatting(
    requests_list, sheet_id, start_row, end_row, start_col=3, end_col=5
):
    # Rule for "Acceptable" (Green)
    requests_list.append(
        {
            "addConditionalFormatRule": {
                "rule": {
                    "ranges": [
                        {
                            "sheetId": sheet_id,
                            "startRowIndex": start_row,
                            "endRowIndex": end_row,
                            "startColumnIndex": start_col,
                            "endColumnIndex": end_col,
                        }
                    ],
                    "booleanRule": {
                        "condition": {
                            "type": "TEXT_EQ",
                            "values": [{"userEnteredValue": "Acceptable"}],
                        },
                        "format": {
                            "backgroundColor": {
                                "red": 0.85,
                                "green": 0.92,
                                "blue": 0.83,
                            },
                            "textFormat": {
                                "foregroundColor": {
                                    "red": 0.2,
                                    "green": 0.4,
                                    "blue": 0.2,
                                },
                                "bold": True,
                            },
                        },
                    },
                },
                "index": 0,
            }
        }
    )
    # Rule for "Rejected" (Red/Grey)
    requests_list.append(
        {
            "addConditionalFormatRule": {
                "rule": {
                    "ranges": [
                        {
                            "sheetId": sheet_id,
                            "startRowIndex": start_row,
                            "endRowIndex": end_row,
                            "startColumnIndex": start_col,
                            "endColumnIndex": end_col,
                        }
                    ],
                    "booleanRule": {
                        "condition": {
                            "type": "TEXT_EQ",
                            "values": [{"userEnteredValue": "Rejected"}],
                        },
                        "format": {
                            "backgroundColor": {"red": 0.95, "green": 0.8, "blue": 0.8},
                            "textFormat": {
                                "foregroundColor": {
                                    "red": 0.6,
                                    "green": 0.1,
                                    "blue": 0.1,
                                },
                                "bold": True,
                            },
                        },
                    },
                },
                "index": 1,
            }
        }
    )


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

        # We need exactly 2 runs to compare side-by-side
        if not runs or len(runs) < 2 or not file_config:
            continue

        run_id_1 = runs[0]
        run_id_2 = runs[1]

        features_path = os.path.join(INPUTS_DIR, file_config["features"])
        features_list = read_json_obj(features_path)
        if not features_list:
            continue

        for version in VERSIONS:
            tab_title = f"{part}_{version}_Refined"
            print(f"Processing Tab: {tab_title}...")

            strat_file_1 = os.path.join(
                OUTPUTS_DIR, version, f"refined_strategies_run_{run_id_1}.json"
            )
            strat_file_2 = os.path.join(
                OUTPUTS_DIR, version, f"refined_strategies_run_{run_id_2}.json"
            )

            strat_data_1 = read_json_obj(strat_file_1) or {}
            strat_data_2 = read_json_obj(strat_file_2) or {}

            if not strat_data_1 and not strat_data_2:
                print(
                    f"  [Skip] No refined strategy data found for runs {run_id_1} and {run_id_2}"
                )
                continue

            # --- BUILD SHEET DATA ---
            sheet_data = []

            # 1. HEADERS
            headers = [
                "Feature Details",
                f"Run {run_id_1} Strategy",
                f"Run {run_id_2} Strategy",
                f"Run {run_id_1} Status",
                f"Run {run_id_2} Status",
                "Comments",
            ]
            sheet_data.append(headers)

            # 2. FEATURE ROWS
            for feat in features_list:
                fid = feat.get("feature_id")

                # Format Columns
                col_feature = format_feature_details(feat)
                col_strat_1 = format_refined_strategy(strat_data_1.get(fid, {}))
                col_strat_2 = format_refined_strategy(strat_data_2.get(fid, {}))

                row = [
                    col_feature,
                    col_strat_1,
                    col_strat_2,
                    "",  # Run 1 Dropdown
                    "",  # Run 2 Dropdown
                    "",  # Comments
                ]
                sheet_data.append(row)

            # --- WRITE TO GOOGLE SHEET ---
            try:
                existing_ws = sh.worksheet(tab_title[:100])
                sh.del_worksheet(existing_ws)
                time.sleep(1)
            except gspread.WorksheetNotFound:
                pass

            ws = sh.add_worksheet(
                title=tab_title[:100], rows=len(sheet_data) + 10, cols=6
            )
            ws.update(range_name=f"A1:F{len(sheet_data)}", values=sheet_data)

            # --- BATCH FORMATTING ---
            batch_requests = []

            # 1. Validation Dropdowns (Columns D and E, which are indexes 3 and 4)
            for row_idx in range(1, len(sheet_data)):
                add_dropdown_requests(
                    batch_requests, ws.id, row_idx, start_col=3, end_col=5
                )

            # 2. Conditional Formatting (Columns D and E)
            add_conditional_formatting(
                batch_requests, ws.id, 1, len(sheet_data), start_col=3, end_col=5
            )

            # 3. Header Style
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

            # 4. Text Alignment & Wrapping (All Columns)
            batch_requests.append(
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": ws.id,
                            "startRowIndex": 1,
                            "endRowIndex": len(sheet_data),
                            "startColumnIndex": 0,
                            "endColumnIndex": 6,
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

            # 5. Column Widths
            widths = [350, 450, 450, 120, 120, 250]
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

            # 6. Borders (Solid grid)
            batch_requests.append(
                {
                    "updateBorders": {
                        "range": {
                            "sheetId": ws.id,
                            "startRowIndex": 0,
                            "endRowIndex": len(sheet_data),
                            "startColumnIndex": 0,
                            "endColumnIndex": 6,
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
