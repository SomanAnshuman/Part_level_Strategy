import os
import json
import time
import yaml
import gspread
from pathlib import Path
from google.oauth2.service_account import Credentials

# --- CONFIGURATION ---
SPREADSHEET_NAME = "LLM PLS with Tools&Params"

PARTS = ["NIST_Part1"]
VERSIONS = ["v6"]
FLOWS = ["m2"]
RUN_TO_USE = "1"

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
        return "N/A"
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
        return "N/A"

    output_lines = []
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


def format_strategy_cell(details):
    if not details:
        return "N/A"
    lines = []
    if "tool_path" in details:
        lines.append(f"Toolpath: {details['tool_path']}")
    if "tool_path_type" in details:
        lines.append(f"Toolpath Type: {details['tool_path_type']}")
    if "tool_path_syntax" in details:
        lines.append(f"Toolpath Syntax: {details['tool_path_syntax']}")
    if "tool_path_style" in details and details["tool_path_style"]:
        lines.append(f"Toolpath Style: {details['tool_path_style']}")
    if "tool_types" in details and details["tool_types"]:
        lines.append(f"Tool Types: {', '.join(details['tool_types'])}")
    return "\n".join(lines).strip()


def format_tool_cell(tools_list):
    if not tools_list:
        return "N/A"
    t = tools_list[0]
    lines = [
        f"Tool Name: {t.get('name', 'N/A')}",
        f"Tool Type: {t.get('type', 'N/A')}",
        f"Diameter: {t.get('diameter', 'N/A')} mm",
        f"Flutes: {t.get('flutes', 'N/A')}",
    ]
    if "reason" in t and t["reason"]:
        lines.append(f"\nReason: {t['reason']}")
    return "\n".join(lines).strip()


def format_params_cell(tools_list):
    if not tools_list:
        return "N/A"
    params = tools_list[0].get("recommended_params", {})
    if not params:
        return "N/A"
    lines = [
        f"Ap: {params.get('ap_mm', 'N/A')} mm",
        f"Ae: {params.get('ae_mm', 'N/A')} mm",
        f"Feed: {params.get('feed_mm_min', 'N/A')} mm/min",
        f"Speed: {params.get('speed_rpm', 'N/A')} rpm",
        f"MRR: {params.get('mrr_cm3_min', 'N/A')} cm3/min",
        f"Tool life: {params.get('tool_life_min', 'N/A')} min",
    ]
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

                tab_title = f"{part}_{version}_{flow}_results"
                print(f"Processing Tab: {tab_title}...")

                strat_filename = (
                    f"part_strategy_final_{part}_{version}_run_{RUN_TO_USE}.json"
                )
                strat_path = os.path.join(results_dir, strat_filename)
                part_strategy = read_json_obj(strat_path)

                if not part_strategy or "error" in part_strategy:
                    print(f"  > No data found for {strat_filename}. Skipping flow.")
                    continue

                # --- BUILD SHEET DATA ---
                sheet_data = []
                setup_rows = []

                # 1. HEADERS (5 Columns)
                headers = [
                    "Operation",
                    "Features clustered",
                    "Strategy recommended",
                    "Tool recommended",
                    "Params recommended",
                ]
                sheet_data.append(headers)
                current_row_idx = 1

                # 2. SETUPS & OPERATIONS
                if "setups" in part_strategy:
                    for setup in part_strategy["setups"]:

                        # Setup Row
                        setup_desc = f"SETUP {setup.get('setup_id','?')} : {setup.get('description','')}"
                        sheet_data.append([setup_desc, "", "", "", ""])
                        setup_rows.append(current_row_idx)  # Track for styling
                        current_row_idx += 1

                        for op in setup.get("operations", []):
                            step_str = f"Op {op.get('sequence_order')}: {op.get('operation_type')}"
                            col_features = format_features_covered(
                                op.get("feature_ids", []), features_map
                            )
                            col_strategy = format_strategy_cell(
                                op.get("strategy_details", {})
                            )
                            col_tool = format_tool_cell(op.get("tools", []))
                            col_params = format_params_cell(op.get("tools", []))

                            row_data = [
                                step_str,
                                col_features,
                                col_strategy,
                                col_tool,
                                col_params,
                            ]
                            sheet_data.append(row_data)
                            current_row_idx += 1

                # 3. SPACING
                for _ in range(3):
                    sheet_data.append([""] * 5)  # Matches 5 columns
                current_row_idx += 3

                # 4. FEATURES TABLE
                feat_header = [
                    "Feature Type",
                    "Cam Specific Name",
                    "Feature Info",
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
                    title=tab_title[:100], rows=len(sheet_data) + 10, cols=5
                )
                ws.update(range_name=f"A1:E{len(sheet_data)}", values=sheet_data)

                # --- BATCH FORMATTING ---
                batch_requests = []

                # 1. Main Header Style (Row 0)
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

                # 2. Feature Header Style
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

                # 3. Setup Row Style (Grey Divider)
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

                # 4. Cell Alignments
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
                # Col C-E: Middle Aligned
                batch_requests.append(
                    {
                        "repeatCell": {
                            "range": {
                                "sheetId": ws.id,
                                "startRowIndex": 1,
                                "endRowIndex": len(sheet_data),
                                "startColumnIndex": 2,
                                "endColumnIndex": 5,
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

                # 5. Column Widths (5 Columns)
                widths = [250, 350, 250, 250, 200]
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
                                "endColumnIndex": 5,
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
