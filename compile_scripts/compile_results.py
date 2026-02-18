import os
import json
import time
import gspread
from pathlib import Path
from google.oauth2.service_account import Credentials

# --- CONFIGURATION ---
SPREADSHEET_NAME = "Part level strategy"
PARTS = ["NIST_Part1", "NIST_Part2"]
VERSIONS = ["v5"]

# Map parts to their specific run numbers
PART_RUN_MAP = {
    "PM0290-020-01": ["1", "2"],
    "PM0289-020-01": ["3", "4"],
    "FIXTURE-01": ["5", "6"],
    "msc_step_1": ["7", "8"],
    "NIST_Part1": ["9", "10"],
    "NIST_Part2": ["11", "12"],
}

# Map parts to specific set of input files
PART_FILES_MAP = {
    "PM0290-020-01": {
        "features": "features1.json",
        "part_context": "part_context1.json",
        "machine_context": "machine_context1.json",
    },
    "PM0289-020-01": {
        "features": "features2.json",
        "part_context": "part_context2.json",
        "machine_context": "machine_context2.json",
    },
    "FIXTURE-01": {
        "features": "features3.json",
        "part_context": "part_context3.json",
        "machine_context": "machine_context3.json",
    },
    "msc_step_1": {
        "features": "features4.json",
        "part_context": "part_context4.json",
        "machine_context": "machine_context4.json",
    },
    "NIST_Part1": {
        "features": "features_NIST_1.json",
        "part_context": "part_context_NIST_1.json",
        "machine_context": "machine_context_NIST_1.json",
    },
    "NIST_Part2": {
        "features": "features_NIST_2.json",
        "part_context": "part_context_NIST_2.json",
        "machine_context": "machine_context_NIST_1.json",
    },
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
        return None
    except Exception as e:
        return {"error": str(e)}


def format_for_human(data, indent=0):
    """Recursively formats JSON into clean YAML-like text."""
    if data is None:
        return ""
    if indent > 20:
        return "... (nested too deep)"

    text = ""
    spacer = "  " * indent

    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, (dict, list)):
                text += f"{spacer}{key}:\n{format_for_human(value, indent + 1)}"
            else:
                text += f"{spacer}{key}: {value}\n"
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, (dict, list)):
                text += f"{spacer}-\n{format_for_human(item, indent + 1)}"
            else:
                text += f"{spacer}- {item}\n"
    else:
        text += f"{spacer}{data}\n"
    return text


def truncate_cell(data, limit=45000):
    """Strict truncation to avoid API errors."""
    if not isinstance(data, str):
        data = str(data)
    if len(data) > limit:
        return data[: limit - 100] + "\n... [TRUNCATED]"
    return data


def col_idx_to_letter(n):
    """Converts 0-based index to column letter (0->A, 1->B, etc). Simple version for <26 cols."""
    return chr(65 + n)


def compile_data():
    client = get_client()

    try:
        sh = client.open(SPREADSHEET_NAME)
        print(f"Opened: {SPREADSHEET_NAME}")
    except gspread.SpreadsheetNotFound:
        sh = client.create(SPREADSHEET_NAME)
        print(f"Created: {sh.url}")

    for part in PARTS:
        runs = PART_RUN_MAP.get(part)
        file_config = PART_FILES_MAP.get(part)

        if not runs or len(runs) < 2:
            print(f"Skipping {part}: Missing run configuration.")
            continue
        if not file_config:
            print(f"Skipping {part}: Missing file configuration.")
            continue

        # Load Static Inputs based on Part Map
        features_path = os.path.join(INPUTS_DIR, file_config["features"])
        part_ctx_path = os.path.join(INPUTS_DIR, file_config["part_context"])
        mach_ctx_path = os.path.join(INPUTS_DIR, file_config["machine_context"])

        features_list = read_json_obj(features_path)
        part_ctx = read_json_obj(part_ctx_path)
        mach_ctx = read_json_obj(mach_ctx_path)

        if not features_list or not isinstance(features_list, list):
            print(f"Skipping {part}: Invalid features file at {features_path}")
            continue

        for version in VERSIONS:
            sheet_title = f"{part}_{version}"
            print(f"Processing {sheet_title}...")

            # Rate Limit Pause
            time.sleep(2)

            # Delete & Recreate Worksheet
            try:
                existing_ws = sh.worksheet(sheet_title)
                sh.del_worksheet(existing_ws)
                time.sleep(1)
            except gspread.WorksheetNotFound:
                pass

            # Determine dynamic columns
            # Base columns
            col_structure = ["FEATURE_INFO"]

            # Add Feature Strat cols if v2 or v3
            if version in ["v2", "v3"]:
                col_structure.extend(["FEAT_STRAT_R1", "FEAT_STRAT_R2"])

            # Add Type Strat cols ONLY if v3
            if version == "v3":
                col_structure.extend(["TYPE_STRAT_R1", "TYPE_STRAT_R2"])

            # Always add Part Strat cols
            col_structure.extend(["PART_STRAT_R1", "PART_STRAT_R2"])

            total_cols = len(col_structure)
            total_rows = len(features_list) + 10

            ws = sh.add_worksheet(title=sheet_title, rows=total_rows, cols=total_cols)

            # --- 1. PREPARE HEADERS ---
            grid_data = []

            # Row 1 & 2: Contexts
            grid_data.append(
                ["PART CONTEXT", format_for_human(part_ctx)] + [""] * (total_cols - 2)
            )
            grid_data.append(
                ["MACHINE CONTEXT", format_for_human(mach_ctx)]
                + [""] * (total_cols - 2)
            )
            grid_data.append([""] * total_cols)  # Spacer

            # Row 4: Dynamic Column Headers
            header_row = ["FEATURE INFO"]
            if "FEAT_STRAT_R1" in col_structure:
                header_row.extend(
                    [f"FEAT STRAT (R{runs[0]})", f"FEAT STRAT (R{runs[1]})"]
                )
            if "TYPE_STRAT_R1" in col_structure:
                header_row.extend(
                    [f"TYPE STRAT (R{runs[0]})", f"TYPE STRAT (R{runs[1]})"]
                )
            header_row.extend([f"PART STRAT (R{runs[0]})", f"PART STRAT (R{runs[1]})"])

            grid_data.append(header_row)

            header_row_index = len(grid_data)
            start_data_row = header_row_index + 1

            # --- 2. LOAD RUN DATA ---
            feat_strat_r1 = {}
            feat_strat_r2 = {}
            if version in ["v2", "v3"]:
                feat_strat_r1 = (
                    read_json_obj(
                        os.path.join(
                            OUTPUTS_DIR,
                            version,
                            f"feature_strategies_run_{runs[0]}.json",
                        )
                    )
                    or {}
                )
                feat_strat_r2 = (
                    read_json_obj(
                        os.path.join(
                            OUTPUTS_DIR,
                            version,
                            f"refined_strategies_run_{runs[1]}.json",
                        )
                    )
                    or {}
                )

            type_strat_r1_text = ""
            type_strat_r2_text = ""
            if version == "v3":
                ts1 = read_json_obj(
                    os.path.join(
                        OUTPUTS_DIR,
                        version,
                        f"feature_type_strategies_run_{runs[0]}.json",
                    )
                )
                ts2 = read_json_obj(
                    os.path.join(
                        OUTPUTS_DIR,
                        version,
                        f"feature_type_strategies_run_{runs[1]}.json",
                    )
                )
                type_strat_r1_text = format_for_human(ts1)
                type_strat_r2_text = format_for_human(ts2)

            ps1 = read_json_obj(
                os.path.join(OUTPUTS_DIR, version, f"part_strategy_run_{runs[0]}.json")
            )
            ps2 = read_json_obj(
                os.path.join(OUTPUTS_DIR, version, f"part_strategy_run_{runs[1]}.json")
            )
            part_strat_r1_text = format_for_human(ps1)
            part_strat_r2_text = format_for_human(ps2)

            # --- 3. BUILD DATA ROWS ---
            for idx, feature in enumerate(features_list):
                fid = feature.get("feature_id")

                current_row = []

                # 1. Feature Info
                current_row.append(format_for_human(feature))

                # 2. Feature Strat (v2, v3)
                if "FEAT_STRAT_R1" in col_structure:
                    fs1 = format_for_human(feat_strat_r1.get(fid, ""))
                    fs2 = format_for_human(feat_strat_r2.get(fid, ""))
                    current_row.extend([fs1, fs2])

                # 3. Type Strat (v3)
                if "TYPE_STRAT_R1" in col_structure:
                    # Only populate first row, merge later
                    t1 = type_strat_r1_text if idx == 0 else ""
                    t2 = type_strat_r2_text if idx == 0 else ""
                    current_row.extend([t1, t2])

                # 4. Part Strat (All)
                p1 = part_strat_r1_text if idx == 0 else ""
                p2 = part_strat_r2_text if idx == 0 else ""
                current_row.extend([p1, p2])

                grid_data.append(current_row)

            # Write Data
            last_col_letter = col_idx_to_letter(total_cols - 1)
            safe_grid = [[truncate_cell(c) for c in r] for r in grid_data]

            try:
                ws.update(
                    range_name=f"A1:{last_col_letter}{len(safe_grid)}", values=safe_grid
                )
                time.sleep(2)
            except Exception as e:
                print(f"Error writing to {sheet_title}: {e}")
                continue

            # --- 4. FORMATTING ---

            # Merge Static Headers
            # Part Context: B1 to LastCol
            ws.merge_cells(f"B1:{last_col_letter}1")
            time.sleep(0.5)
            # Machine Context: B2 to LastCol
            ws.merge_cells(f"B2:{last_col_letter}2")
            time.sleep(0.5)

            # Merge Large Columns (Type & Part Strats)
            last_row = len(safe_grid)
            if last_row > start_data_row:
                # Determine indices for merging based on structure
                # The structure list maps 1:1 to columns.
                # Find indices of TYPE_STRAT and PART_STRAT

                indices_to_merge = []

                if "TYPE_STRAT_R1" in col_structure:
                    idx = col_structure.index("TYPE_STRAT_R1")
                    indices_to_merge.extend([idx, idx + 1])  # R1 and R2

                if "PART_STRAT_R1" in col_structure:
                    idx = col_structure.index("PART_STRAT_R1")
                    indices_to_merge.extend([idx, idx + 1])  # R1 and R2

                for col_idx in indices_to_merge:
                    col_char = col_idx_to_letter(col_idx)
                    try:
                        ws.merge_cells(
                            f"{col_char}{start_data_row}:{col_char}{last_row}"
                        )
                    except Exception as e:
                        print(f"Merge error col {col_char}: {e}")
                    time.sleep(0.5)

            # Visuals
            ws.format(
                f"A{header_row_index}:{last_col_letter}{header_row_index}",
                {
                    "textFormat": {
                        "bold": True,
                        "foregroundColor": {"red": 1, "green": 1, "blue": 1},
                    },
                    "backgroundColor": {"red": 0.3, "green": 0.3, "blue": 0.3},
                },
            )
            time.sleep(0.5)

            ws.format(
                f"A1:{last_col_letter}{last_row}",
                {
                    "wrapStrategy": "WRAP",
                    "verticalAlignment": "TOP",
                    "textFormat": {"fontFamily": "Consolas", "fontSize": 9},
                },
            )
            time.sleep(0.5)

            # Column Resizing
            # Col A = 350, Rest = 400
            sh.batch_update(
                {
                    "requests": [
                        {
                            "updateDimensionProperties": {
                                "range": {
                                    "sheetId": ws.id,
                                    "dimension": "COLUMNS",
                                    "startIndex": 0,
                                    "endIndex": 1,
                                },
                                "properties": {"pixelSize": 350},
                                "fields": "pixelSize",
                            }
                        },
                        {
                            "updateDimensionProperties": {
                                "range": {
                                    "sheetId": ws.id,
                                    "dimension": "COLUMNS",
                                    "startIndex": 1,
                                    "endIndex": total_cols,
                                },
                                "properties": {"pixelSize": 400},
                                "fields": "pixelSize",
                            }
                        },
                    ]
                }
            )
            time.sleep(1)

    print("Done.")


if __name__ == "__main__":
    compile_data()
