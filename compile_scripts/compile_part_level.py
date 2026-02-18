import os
import json
import time
import yaml
import gspread
from pathlib import Path
from google.oauth2.service_account import Credentials

# --- CONFIGURATION ---
SPREADSHEET_NAME = "LLM Part level Strategy"

PARTS = ["msc_step_1", "PM0289-020-01", "NIST_Part1", "NIST_Part2"]
VERSIONS = ["v5"]

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


def format_yaml(data):
    if data is None:
        return ""
    return yaml.dump(data, default_flow_style=False, sort_keys=False).strip()


def format_strategy_details(details):
    if not details:
        return ""
    lines = ["Strategy details:"]
    keys_order = ["tool_path", "tool_path_type", "tool_path_syntax", "tool_path_style"]
    for k in keys_order:
        if k in details:
            lines.append(f" - {k.replace('_', ' ').title()}: {details[k]}")
    if "tool_types" in details and details["tool_types"]:
        lines.append(" - Tool Types:")
        for t in details["tool_types"]:
            lines.append(f"    - {t}")
    return "\n".join(lines)


def format_features_covered(feature_ids, features_map):
    grouped = {}
    for fid in feature_ids:
        if fid in features_map:
            feat_data = features_map[fid]
            ftype = feat_data.get("feature_type", "Unknown").capitalize()
            if not ftype.endswith("s"):
                ftype += "s"
            if ftype not in grouped:
                grouped[ftype] = []
            names = feat_data.get("cam_specific_names", [])
            if not names:
                names = [feat_data.get("feature_name", "Unknown")]
            grouped[ftype].append(names)

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


# --- BATCH REQUEST HELPERS ---


def add_dropdown_requests(requests_list, sheet_id, row_index, start_col=2, end_col=5):
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
    requests_list, sheet_id, start_row, end_row, start_col, end_col
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
                            },  # Light Green
                            "textFormat": {
                                "foregroundColor": {
                                    "red": 0.2,
                                    "green": 0.4,
                                    "blue": 0.2,
                                },
                                "bold": True,
                            },  # Dark Green Text
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
                                }
                            },  # Dark Grey Text
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
        if not runs or not file_config:
            continue

        features_path = os.path.join(INPUTS_DIR, file_config["features"])
        features_list = read_json_obj(features_path)
        if not features_list:
            continue
        features_map = {f["feature_id"]: f for f in features_list}

        for version in VERSIONS:
            for run_id in runs:
                tab_title = f"{part}_{version}_Run{run_id}"
                print(f"Processing Tab: {tab_title}...")

                strat_filename = f"part_strategy_run_{run_id}.json"
                strat_path = os.path.join(OUTPUTS_DIR, version, strat_filename)
                part_strategy = read_json_obj(strat_path)
                if not part_strategy:
                    continue

                # --- BUILD SHEET DATA ---
                sheet_data = []
                validation_rows = []
                setup_rows = []  # Track setup row indices for formatting

                # 1. HEADERS
                headers = [
                    "Operation Step",
                    "Recommendation",
                    "Overall",
                    "Features clustered",
                    "Strategy Coverage",
                    "Suggested Refinements",
                    "Reasons",
                ]
                sheet_data.append(headers)
                current_row_idx = 1

                # 2. SETUPS & OPERATIONS
                if "setups" in part_strategy:
                    for setup in part_strategy["setups"]:
                        # Setup Row
                        setup_desc = f"SETUP {setup.get('setup_id','?')} : {setup.get('description','')}"
                        sheet_data.append([setup_desc, "", "", "", "", "", ""])
                        setup_rows.append(
                            current_row_idx
                        )  # Mark this row for Grey styling
                        current_row_idx += 1

                        for op in setup.get("operations", []):
                            step_str = f"Op {op.get('sequence_order')}: {op.get('operation_type')}"
                            f_covered = format_features_covered(
                                op.get("feature_ids", []), features_map
                            )
                            s_details = format_strategy_details(
                                op.get("strategy_details", {})
                            )
                            rec_text = f"{f_covered}\n\n{s_details}"

                            row_data = [step_str, rec_text, "", "", "", "", ""]
                            sheet_data.append(row_data)

                            # Validation only on Operation Rows
                            validation_rows.append(current_row_idx)
                            current_row_idx += 1

                # 3. SPACING
                for _ in range(3):
                    sheet_data.append([""] * 7)
                current_row_idx += 3

                # 4. FEATURES TABLE
                feat_header = [
                    "Feature Type",
                    "Cam Specific Name",
                    "Feature Info",
                    "",
                    "",
                    "",
                    "",
                ]
                sheet_data.append(feat_header)

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
                            "",
                        ]
                        sheet_data.append(row)
                        first_in_group = False

                # --- WRITE TO GOOGLE SHEET ---
                try:
                    existing_ws = sh.worksheet(tab_title[:100])
                    sh.del_worksheet(existing_ws)
                    time.sleep(1)
                except gspread.WorksheetNotFound:
                    pass

                ws = sh.add_worksheet(
                    title=tab_title[:100], rows=len(sheet_data) + 10, cols=7
                )
                ws.update(range_name=f"A1:G{len(sheet_data)}", values=sheet_data)

                # --- BATCH FORMATTING ---
                batch_requests = []

                # 1. Validation Dropdowns
                for row_idx in validation_rows:
                    add_dropdown_requests(batch_requests, ws.id, row_idx)

                # 2. Conditional Formatting (Green/Red chips)
                add_conditional_formatting(
                    batch_requests, ws.id, 1, len(sheet_data), 2, 5
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
                                        "red": 1.0,
                                        "green": 1.0,
                                        "blue": 1.0,
                                    },  # White bg
                                    "textFormat": {
                                        "bold": True,
                                        "fontSize": 10,
                                        "fontFamily": "Arial",
                                    },
                                    "horizontalAlignment": "CENTER",
                                }
                            },
                            "fields": "userEnteredFormat",
                        }
                    }
                )

                # 4. Setup Row Style (Dark Grey Divider)
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
                                            "red": 0.7,
                                            "green": 0.7,
                                            "blue": 0.7,
                                        },  # Dark Grey
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

                # 5. Operation Rows Alignment
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
                # Col C-G: Middle Aligned
                batch_requests.append(
                    {
                        "repeatCell": {
                            "range": {
                                "sheetId": ws.id,
                                "startRowIndex": 1,
                                "endRowIndex": len(sheet_data),
                                "startColumnIndex": 2,
                                "endColumnIndex": 7,
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
                widths = [350, 450, 200, 200, 200, 250, 250]
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
                                "endColumnIndex": 7,
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
