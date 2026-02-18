import os
import json
import time
import gspread
from pathlib import Path
from google.oauth2.service_account import Credentials

# --- CONFIGURATION ---
SPREADSHEET_NAME = "Part level strategy"

PARTS = ["msc_step_1", "PM0289-020-01", "NIST_Part1", "NIST_Part2"]
VERSIONS = ["v5"]
FLOWS = ["m2"]
RUNS_TO_COMPARE = ["1", "2"]

PART_FILES_MAP = {
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

BASE_DIR = Path(__file__).resolve().parent.parent
INPUTS_DIR = os.path.join(BASE_DIR, "inputs")
OUTPUTS_ROOT = os.path.join(BASE_DIR, "outputs", "tool_and_params")

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
    if data is None:
        return ""
    if indent > 50:
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


def truncate_cell(data, limit=49000):
    if not isinstance(data, str):
        data = str(data)
    if len(data) > limit:
        return data[: limit - 100] + "\n... [TRUNCATED]"
    return data


def col_idx_to_letter(n):
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
        file_config = PART_FILES_MAP.get(part)
        if not file_config:
            print(f"Skipping {part}: Missing config.")
            continue

        # Load Contexts
        features_path = os.path.join(INPUTS_DIR, file_config["features"])
        part_ctx_path = os.path.join(INPUTS_DIR, file_config["part_context"])
        mach_ctx_path = os.path.join(INPUTS_DIR, file_config["machine_context"])

        features_list = read_json_obj(features_path)
        part_ctx = read_json_obj(part_ctx_path)
        mach_ctx = read_json_obj(mach_ctx_path)

        if not features_list or not isinstance(features_list, list):
            print(f"Skipping {part}: Invalid features file.")
            continue

        for version in VERSIONS:
            for flow in FLOWS:
                sheet_title = f"{part}_{version}_{flow}_tools"
                print(f"Processing {sheet_title}...")
                
                results_dir = os.path.join(OUTPUTS_ROOT, flow)
                
                # --- DELAY 1: Before creating/deleting sheet ---
                time.sleep(2) 

                try:
                    existing_ws = sh.worksheet(sheet_title)
                    sh.del_worksheet(existing_ws)
                    time.sleep(1) # Delay after delete
                except gspread.WorksheetNotFound:
                    pass

                col_headers = ["FEATURE INFO"] + [f"RUN {r} STRATEGY" for r in RUNS_TO_COMPARE]
                total_cols = len(col_headers)
                
                start_data_row = 5
                total_rows = start_data_row + len(features_list) + 2

                ws = sh.add_worksheet(title=sheet_title, rows=total_rows, cols=total_cols)
                
                # --- DELAY 2: After creating sheet ---
                time.sleep(1)

                # --- BUILD GRID ---
                grid_data = []
                grid_data.append(["PART CONTEXT", format_for_human(part_ctx)] + [""] * (total_cols - 2))
                grid_data.append(["MACHINE CONTEXT", format_for_human(mach_ctx)] + [""] * (total_cols - 2))
                grid_data.append([""] * total_cols)
                grid_data.append(col_headers)

                run_strategies = []
                for run in RUNS_TO_COMPARE:
                    filename = f"part_strategy_final_{part}_{version}_run_{run}.json"
                    file_path = os.path.join(results_dir, filename)
                    data = read_json_obj(file_path)
                    
                    if data and "error" not in data:
                        run_strategies.append(format_for_human(data))
                    else:
                        run_strategies.append(f"File not found or Error:\n{data}")

                for idx, feature in enumerate(features_list):
                    row = []
                    row.append(format_for_human(feature))
                    if idx == 0:
                        row.extend(run_strategies)
                    else:
                        row.extend([""] * len(RUNS_TO_COMPARE))
                    grid_data.append(row)

                safe_grid = [[truncate_cell(c) for c in r] for r in grid_data]
                last_col_char = col_idx_to_letter(total_cols - 1)
                last_data_row = start_data_row + len(features_list) - 1

                try:
                    ws.update(
                        range_name=f"A1:{last_col_char}{len(safe_grid)}",
                        values=safe_grid
                    )
                    # --- DELAY 3: After massive write ---
                    print("  > Data written. Pausing...")
                    time.sleep(3) 
                except Exception as e:
                    print(f"Error writing {sheet_title}: {e}")
                    continue

                # --- MERGING ---
                try:
                    ws.merge_cells(f"B1:{last_col_char}1")
                    time.sleep(0.5) # Short pause between merges
                    ws.merge_cells(f"B2:{last_col_char}2")
                    time.sleep(0.5)

                    if len(features_list) > 1:
                        for i in range(len(RUNS_TO_COMPARE)):
                            col_idx = 1 + i 
                            col_char = col_idx_to_letter(col_idx)
                            ws.merge_cells(f"{col_char}{start_data_row}:{col_char}{last_data_row}")
                            # --- DELAY 4: Inside loop to avoid rapid-fire API calls ---
                            time.sleep(1.5) 
                except Exception as e:
                    print(f"  ! Merge warning: {e}")

                # --- FORMATTING ---
                try:
                    ws.format(f"A1:A2", {"textFormat": {"bold": True}})
                    time.sleep(0.5)

                    ws.format(f"A4:{last_col_char}4", {
                        "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
                        "backgroundColor": {"red": 0.2, "green": 0.2, "blue": 0.2},
                        "horizontalAlignment": "CENTER"
                    })
                    time.sleep(0.5)

                    ws.format(f"A5:{last_col_char}{last_data_row}", {
                        "wrapStrategy": "WRAP",
                        "verticalAlignment": "TOP",
                        "textFormat": {"fontFamily": "Consolas", "fontSize": 9}
                    })
                    # --- DELAY 5: Before resizing ---
                    time.sleep(1)
                except Exception as e:
                    print(f"  ! Format warning: {e}")

                sh.batch_update({
                    "requests": [
                        {
                            "updateDimensionProperties": {
                                "range": {"sheetId": ws.id, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 1},
                                "properties": {"pixelSize": 300},
                                "fields": "pixelSize"
                            }
                        },
                        {
                            "updateDimensionProperties": {
                                "range": {"sheetId": ws.id, "dimension": "COLUMNS", "startIndex": 1, "endIndex": total_cols},
                                "properties": {"pixelSize": 600},
                                "fields": "pixelSize"
                            }
                        }
                    ]
                })
                # --- DELAY 6: Final pause before next sheet ---
                print(f"  > Finished {sheet_title}. Cooling down...")
                time.sleep(3)

    print("Done. Sheets updated.")


if __name__ == "__main__":
    compile_data()