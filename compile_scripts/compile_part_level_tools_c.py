import os
import json
import time
import yaml
import gspread
from pathlib import Path
from google.oauth2.service_account import Credentials

# --- CONFIGURATION ---
SPREADSHEET_NAME = "LLM Part Strategy with Tools"

PARTS = [
    "FIXTURE-01",
    "msc_step_1",
    "PM0290-020-01",
    "PM0289-020-01",
    "NIST_Part1",
    "NIST_Part2",
]
VERSIONS = ["v5"]
FLOWS = ["m1", "m2"]
RUNS_TO_COMPARE = ["1"]

# Maps part name to required input files
PART_FILES_MAP = {
    "FIXTURE-01": {"features": "features3.json"},
    "msc_step_1": {"features": "features4.json"},
    "PM0290-020-01": {"features": "features1.json"},
    "PM0289-020-01": {"features": "features2.json"},
    "NIST_Part1": {"features": "features_NIST_1.json"},
    "NIST_Part2": {"features": "features_NIST_2.json"},
}

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent
INPUTS_DIR = os.path.join(BASE_DIR, "inputs")
OUTPUTS_ROOT = os.path.join(BASE_DIR, "outputs", "tool_and_params")

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


def format_yaml(data):
    if data is None:
        return ""
    return yaml.dump(data, default_flow_style=False, sort_keys=False).strip()


def format_features_covered(feature_ids, features_map):
    if not feature_ids:
        return ""
    grouped = {}
    for fid in feature_ids:
        match = next((key for key in features_map if key.startswith(fid)), None)
        if match:
            feat_data = features_map[match]
            ftype = feat_data.get("feature_type", "Unknown").capitalize()
            if not ftype.endswith("s"):
                ftype += "s"
            if ftype not in grouped:
                grouped[ftype] = []
            names = feat_data.get("cam_specific_names", [])
            if not names:
                names = [feat_data.get("feature_name", "Unknown")]
            grouped[ftype].append(names)

    if not grouped:
        return ""

    output_lines = ["Features Covered:"]
    for ftype, name_lists in grouped.items():
        output_lines.append(f"{ftype}:")
        for i, names in enumerate(name_lists, 1):
            if len(names) == 1:
                output_lines.append(f"  {i}. {names[0]}")
            else:
                output_lines.append(f"  {i}. - {names[0]}")
                for extra_name in names[1:]:
                    output_lines.append(f"      - {extra_name}")
    return "\n".join(output_lines)


def format_recommendation_cell(op, features_map):
    """Compiles the specific feature, toolpath, tool, and parameter data."""
    lines = []

    # 1. Features Covered
    f_covered = format_features_covered(op.get("feature_ids", []), features_map)
    if f_covered:
        lines.append(f_covered)
        lines.append("")  # spacer

    # 2. Strategy details (ONLY Toolpath)
    strat_details = op.get("strategy_details", {})
    toolpath = strat_details.get("tool_path", "N/A")
    lines.append(f"Toolpath: {toolpath}")
    lines.append("")  # spacer

    # 3. Tools and Parameters
    tools = op.get("tools", [])
    if not tools:
        lines.append("Tools and Parameters: N/A")
    else:
        for i, t in enumerate(tools, 1):
            lines.append(f"Tool {i}:")
            lines.append(f" - Name: {t.get('name', 'N/A')}")
            lines.append(f" - Type: {t.get('type', 'N/A')}")
            lines.append(f" - Diameter: {t.get('diameter', 'N/A')}")
            lines.append(f" - Flutes: {t.get('flutes', 'N/A')}")

            params = t.get("recommended_params", {})
            if not params:
                lines.append(" - Parameters: N/A")
            else:
                lines.append(" - Parameters:")
                lines.append(f"    - Ap (mm): {params.get('ap_mm', 'N/A')}")
                lines.append(f"    - Ae (mm): {params.get('ae_mm', 'N/A')}")
                lines.append(f"    - Feed (mm/min): {params.get('feed_mm_min', 'N/A')}")
                lines.append(f"    - Speed (rpm): {params.get('speed_rpm', 'N/A')}")
                lines.append(f"    - MRR (cm3/min): {params.get('mrr_cm3_min', 'N/A')}")
                lines.append(
                    f"    - Tool life (min): {params.get('tool_life_min', 'N/A')}"
                )

            if i < len(tools):
                lines.append("")  # spacer between multiple tools

    return "\n".join(lines).strip()


# --- BATCH REQUEST HELPERS ---


def add_dropdown_requests(requests_list, sheet_id, row_index, start_col=2, end_col=5):
    """Adds 'Accepted' / 'Rejected' dropdowns to specific columns."""
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
                            {"userEnteredValue": "Accepted"},
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
    requests_list, sheet_id, start_row, end_row, start_col=2, end_col=5
):
    # Rule for "Accepted" (Green)
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
                            "values": [{"userEnteredValue": "Accepted"}],
                        },
                        "format": {
                            "backgroundColor": {
                                "red": 0.85,
                                "green": 0.92,
                                "blue": 0.83,
                            },  # Light Green
                            "textFormat": {
                                "foregroundColor": {
                                    "red": 0.2,
                                    "green": 0.4,
                                    "blue": 0.2,
                                },  # Dark Green
                                "bold": True,
                            },
                        },
                    },
                },
                "index": 0,
            }
        }
    )
    # Rule for "Rejected" (Grey/Red-ish)
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
                            "backgroundColor": {
                                "red": 0.9,
                                "green": 0.9,
                                "blue": 0.9,
                            },  # Light Grey
                            "textFormat": {
                                "foregroundColor": {
                                    "red": 0.2,
                                    "green": 0.2,
                                    "blue": 0.2,
                                }  # Dark Grey
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

    # Open existing or create new Sheet
    try:
        sh = client.open(SPREADSHEET_NAME)
        print(f"Opened existing Spreadsheet: {sh.url}")
    except gspread.SpreadsheetNotFound:
        sh = client.create(SPREADSHEET_NAME)
        print(f"Created new Spreadsheet: {sh.url}")

    for part in PARTS:
        file_config = PART_FILES_MAP.get(part)
        if not file_config:
            continue

        # Load Features for mapping IDs to names
        features_path = os.path.join(INPUTS_DIR, file_config["features"])
        features_list = read_json_obj(features_path)
        if not features_list:
            print(f"Skipping {part}: Missing features file.")
            continue
        features_map = {f["feature_id"]: f for f in features_list}

        for version in VERSIONS:
            for flow in FLOWS:
                results_dir = os.path.join(OUTPUTS_ROOT, flow)

                for run in RUNS_TO_COMPARE:
                    tab_title = f"{part}_{version}_{flow}_Run{run}"
                    print(f"Processing Tab: {tab_title}...")

                    # Target specific JSON format
                    strat_filename = (
                        f"part_strategy_final_{part}_{version}_run_{run}.json"
                    )
                    strat_path = os.path.join(results_dir, strat_filename)
                    part_strategy = read_json_obj(strat_path)

                    if not part_strategy or "error" in part_strategy:
                        print(f"  > No data found for {strat_filename}. Skipping run.")
                        continue

                    # --- BUILD SHEET DATA ---
                    sheet_data = []
                    validation_rows = []
                    setup_rows = []

                    # 1. HEADERS (6 Columns)
                    headers = [
                        "Operations Step",
                        "Recommendation",
                        "Overall",
                        "Tool Selection",
                        "Parameter Selection",
                        "Comments/Suggestions",
                    ]
                    sheet_data.append(headers)
                    current_row_idx = 1

                    # 2. SETUPS & OPERATIONS
                    if "setups" in part_strategy:
                        for setup in part_strategy["setups"]:

                            # Setup Row
                            setup_desc = f"SETUP {setup.get('setup_id','?')} : {setup.get('description','')}"
                            sheet_data.append([setup_desc, "", "", "", "", ""])
                            setup_rows.append(current_row_idx)  # Track for styling
                            current_row_idx += 1

                            for op in setup.get("operations", []):
                                step_str = f"Op {op.get('sequence_order')}: {op.get('operation_type')}"
                                rec_text = format_recommendation_cell(op, features_map)

                                row_data = [step_str, rec_text, "", "", "", ""]
                                sheet_data.append(row_data)

                                # Validation only on Operation Rows
                                validation_rows.append(current_row_idx)
                                current_row_idx += 1

                    # 3. SPACING
                    for _ in range(3):
                        sheet_data.append([""] * 6)  # Matches 6 columns
                    current_row_idx += 3

                    # 4. FEATURES TABLE
                    feat_header = [
                        "Feature Type",
                        "Cam Specific Name",
                        "Feature Info",
                        "",
                        "",
                        "",
                    ]
                    sheet_data.append(feat_header)
                    feature_header_idx = current_row_idx
                    current_row_idx += 1

                    grouped_features = {}
                    for f in features_list:
                        ftype = f.get("feature_type", "Other").capitalize() + "s"
                        if ftype not in grouped_features:
                            grouped_features[ftype] = []
                        grouped_features[ftype].append(f)

                    for ftype, feats in grouped_features.items():
                        first_in_group = True
                        for f in feats:
                            yaml_info = format_yaml(f.get("feature_info"))
                            names = f.get("cam_specific_names", [])
                            names_str = (
                                "\n".join([f" - {n}" for n in names])
                                if names
                                else f.get("feature_name", "")
                            )

                            row = [
                                ftype if first_in_group else "",
                                names_str,
                                yaml_info,
                                "",
                                "",
                                "",
                            ]
                            sheet_data.append(row)
                            current_row_idx += 1
                            first_in_group = False

                    # --- WRITE TO GOOGLE SHEET ---
                    time.sleep(1.5)  # Quota delay
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

                    # 1. Validation Dropdowns (Cols C, D, E -> Index 2, 3, 4, so span is 2 to 5)
                    for row_idx in validation_rows:
                        add_dropdown_requests(
                            batch_requests, ws.id, row_idx, start_col=2, end_col=5
                        )

                    # 2. Conditional Formatting
                    add_conditional_formatting(
                        batch_requests,
                        ws.id,
                        1,
                        len(sheet_data),
                        start_col=2,
                        end_col=5,
                    )

                    # 3. Main Header Style (Row 0)
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
                                            "red": 0.2,
                                            "green": 0.2,
                                            "blue": 0.2,
                                        },  # Dark Header
                                        "textFormat": {
                                            "bold": True,
                                            "foregroundColor": {
                                                "red": 1,
                                                "green": 1,
                                                "blue": 1,
                                            },  # White text
                                            "fontFamily": "Arial",
                                        },
                                        "horizontalAlignment": "CENTER",
                                    }
                                },
                                "fields": "userEnteredFormat",
                            }
                        }
                    )

                    # 3b. Feature Header Style
                    batch_requests.append(
                        {
                            "repeatCell": {
                                "range": {
                                    "sheetId": ws.id,
                                    "startRowIndex": feature_header_idx,
                                    "endRowIndex": feature_header_idx + 1,
                                },
                                "cell": {
                                    "userEnteredFormat": {
                                        "backgroundColor": {
                                            "red": 0.5,
                                            "green": 0.5,
                                            "blue": 0.5,
                                        },  # Dark Header
                                        "textFormat": {
                                            "bold": True,
                                            "foregroundColor": {
                                                "red": 1,
                                                "green": 1,
                                                "blue": 1,
                                            },  # White text
                                            "fontFamily": "Arial",
                                        },
                                    }
                                },
                                "fields": "userEnteredFormat",
                            }
                        }
                    )

                    # 4. Setup Row Style (Grey Divider)
                    for r_idx in setup_rows:
                        batch_requests.append(
                            {
                                "repeatCell": {
                                    "range": {
                                        "sheetId": ws.id,
                                        "startRowIndex": r_idx,
                                        "endRowIndex": r_idx + 1,
                                    },
                                    "cell": {
                                        "userEnteredFormat": {
                                            "backgroundColor": {
                                                "red": 0.8,
                                                "green": 0.8,
                                                "blue": 0.8,
                                            },  # Light Grey
                                            "textFormat": {
                                                "bold": True,
                                                "fontFamily": "Arial",
                                            },
                                            "verticalAlignment": "MIDDLE",
                                        }
                                    },
                                    "fields": "userEnteredFormat",
                                }
                            }
                        )

                    # 5. Cell Alignments
                    # Col A: Bottom Aligned
                    batch_requests.append(
                        {
                            "repeatCell": {
                                "range": {
                                    "sheetId": ws.id,
                                    "startRowIndex": 1,
                                    "endRowIndex": len(sheet_data),
                                    "startColumnIndex": 0,
                                    "endColumnIndex": 1,
                                },
                                "cell": {
                                    "userEnteredFormat": {
                                        "verticalAlignment": "BOTTOM",
                                        "wrapStrategy": "WRAP",
                                        "textFormat": {"fontFamily": "Arial"},
                                    }
                                },
                                "fields": "userEnteredFormat(verticalAlignment,wrapStrategy,textFormat)",
                            }
                        }
                    )
                    # Col B: Top Aligned
                    batch_requests.append(
                        {
                            "repeatCell": {
                                "range": {
                                    "sheetId": ws.id,
                                    "startRowIndex": 1,
                                    "endRowIndex": len(sheet_data),
                                    "startColumnIndex": 1,
                                    "endColumnIndex": 2,
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
                    # Col C-F: Middle Aligned (Applies to main grid, top-aligned is slightly better for YAML but this keeps consistency)
                    batch_requests.append(
                        {
                            "repeatCell": {
                                "range": {
                                    "sheetId": ws.id,
                                    "startRowIndex": 1,
                                    "endRowIndex": len(sheet_data),
                                    "startColumnIndex": 2,
                                    "endColumnIndex": 6,
                                },
                                "cell": {
                                    "userEnteredFormat": {
                                        "verticalAlignment": "MIDDLE",
                                        "wrapStrategy": "WRAP",
                                        "textFormat": {"fontFamily": "Arial"},
                                    }
                                },
                                "fields": "userEnteredFormat(verticalAlignment,wrapStrategy,textFormat)",
                            }
                        }
                    )

                    # 6. Column Widths
                    widths = [300, 450, 160, 160, 160, 350]  # Matches 6 columns
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

                    # 7. Borders (Solid grid)
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

                    print(f"  > Tab {tab_title} completed. Cooling down...")
                    time.sleep(2)  # Quota safety between tabs

    print("\nProcessing Complete. All tool & parameter sheets updated.")


if __name__ == "__main__":
    compile_data()
