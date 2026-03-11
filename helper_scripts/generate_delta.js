require("dotenv").config();

const {
  mkdirSync,
  createWriteStream,
  readFileSync,
  writeFileSync,
  existsSync,
} = require("fs");
const path = require("path");
const { GoogleGenerativeAI } = require("@google/generative-ai");

// DELTA 1 (KB vs Refined v5)
// DELTA 2 (KB vs Refined v6)
// DELTA 3 (Refined v5 vs Refined v6)

/* =========================
   CONFIG
========================= */

const BASE_DIR = path.resolve(__dirname, "..");

const PART = process.argv[2];
if (!PART) {
  console.error(
    "Please provide a PART_NAME. Usage: node scripts/generate_deltas.js <PART_NAME>",
  );
  process.exit(1);
}

const PART_RUN_MAP = {
  "PM0290-020-01": "1",
  "PM0289-020-01": "3",
  "FIXTURE-01": "5",
  msc_step_1: "7",
  NIST_Part1: "9",
  NIST_Part2: "11",
};

const RUN_ID = PART_RUN_MAP[PART];
if (!RUN_ID) {
  console.error(`Invalid part name or no run ID mapped for part: ${PART}`);
  process.exit(1);
}

const PART_FILES_MAP = {
  "PM0290-020-01": { features: "features1.json" },
  "PM0289-020-01": { features: "features2.json" },
  "FIXTURE-01": { features: "features3.json" },
  msc_step_1: { features: "features4.json" },
  NIST_Part1: { features: "features_NIST_1.json" },
  NIST_Part2: { features: "features_NIST_2.json" },
};

const CONFIG = {
  FEATURES_FILE_PATH: path.join(
    BASE_DIR,
    `inputs/${PART_FILES_MAP[PART].features}`,
  ),
  KB_STRATEGY_PATH: path.join(
    BASE_DIR,
    `outputs/rationale/wo_files/${PART}_rationale.json`,
  ),
  REFINED_V5_PATH: path.join(
    BASE_DIR,
    `outputs/v5/refined_strategies_run_${RUN_ID}.json`,
  ),
  REFINED_V6_PATH: path.join(
    BASE_DIR,
    `outputs/v6/refined_strategies_run_${RUN_ID}.json`,
  ),
  OUTPUT_DIR: path.join(BASE_DIR, "outputs/delta"),
  LOG_DIR: path.join(BASE_DIR, "logs/delta"),

  PROMPT_PATH: path.join(
    BASE_DIR,
    "prompts/helper_prompts/generate_delta.prompt.txt",
  ),

  MODEL_NAME: "gemini-pro-latest",
  API_KEY: process.env.GEMINI_API_KEY,
};

/* =========================
   VALIDATION
========================= */

if (!CONFIG.API_KEY) {
  throw new Error("Missing GEMINI_API_KEY. Please set it in a .env file.");
}

/* =========================
   DIRECTORY SETUP
========================= */

mkdirSync(CONFIG.LOG_DIR, { recursive: true });
mkdirSync(CONFIG.OUTPUT_DIR, { recursive: true });

const RUN_LOG_FILE = path.join(CONFIG.LOG_DIR, `${PART}_delta_log.txt`);
const PROMPT_DUMP_DIR = path.join(CONFIG.LOG_DIR, `${PART}_prompts`);
const DELTA_OUTPUT_FILE = path.join(CONFIG.OUTPUT_DIR, `${PART}_delta.json`);

mkdirSync(PROMPT_DUMP_DIR, { recursive: true });

/* =========================
   LOGGER
========================= */

function createLogger(filePath, echo = true) {
  const stream = createWriteStream(filePath, { flags: "a" });

  function log(...args) {
    const msg = args
      .map((v) => (typeof v === "string" ? v : JSON.stringify(v, null, 2)))
      .join(" ");
    const line = `[${new Date().toISOString()}] ${msg}\n`;
    stream.write(line);
    if (echo) console.log(msg);
  }

  function section(title) {
    log("\n======================================");
    log(title);
    log("======================================\n");
  }

  return { log, section };
}

const logger = createLogger(RUN_LOG_FILE);

/* =========================
   GEMINI CLIENT
========================= */

const genAI = new GoogleGenerativeAI(CONFIG.API_KEY);
const model = genAI.getGenerativeModel({ model: CONFIG.MODEL_NAME });

async function generateWithGemini(prompt, label) {
  logger.log(`\nSending prompt to Gemini for ${label}...`);

  try {
    const result = await model.generateContent({
      contents: [{ role: "user", parts: [{ text: prompt }] }],
      generationConfig: {
        responseMimeType: "application/json", // Enforce JSON response
      },
    });

    const response = result.response.text();
    return safeJsonParse(response);
  } catch (error) {
    logger.log(
      `[ERROR] Gemini generation failed for ${label}: ${error.message}`,
    );
    return null;
  }
}

/* =========================
   FILE & GENERIC UTILS
========================= */

function readJson(filePath) {
  if (!existsSync(filePath)) {
    logger.log(`[WARN] File not found: ${filePath}`);
    return null;
  }
  return JSON.parse(readFileSync(filePath, "utf-8"));
}

function writeJson(filePath, data) {
  writeFileSync(filePath, JSON.stringify(data, null, 2), "utf-8");
  logger.log(`Saved file → ${filePath}`);
}

function safeJsonParse(text) {
  try {
    return JSON.parse(text);
  } catch {
    logger.log("Invalid JSON received from model");
    return null;
  }
}

function loadPromptTemplate(filePath) {
  if (!existsSync(filePath)) {
    throw new Error(`Prompt template not found at ${filePath}`);
  }
  return readFileSync(filePath, "utf-8");
}

function renderPrompt(template, variables) {
  let output = template;
  for (const [key, value] of Object.entries(variables)) {
    // Stringify objects if they aren't strings already
    const strValue =
      typeof value === "object" ? JSON.stringify(value, null, 2) : value;
    output = output.replace(new RegExp(`{{${key}}}`, "g"), strValue);
  }
  return output;
}

function savePrompt(label, content) {
  const filePath = path.join(PROMPT_DUMP_DIR, `${label}.txt`);
  writeFileSync(filePath, content, "utf-8");
  logger.log(`Saved prompt → ${filePath}`);
}

/* =========================
   MAIN PIPELINE
========================= */

async function run() {
  const startTime = Date.now();

  logger.section("RUN METADATA");
  logger.log({
    part: PART,
    run_id: RUN_ID,
    model: CONFIG.MODEL_NAME,
    start_time: new Date(startTime).toISOString(),
  });

  // 1. Load Data
  let features = readJson(CONFIG.FEATURES_FILE_PATH) || [];
  const kbData = readJson(CONFIG.KB_STRATEGY_PATH) || {};
  const v5Data = readJson(CONFIG.REFINED_V5_PATH) || {};
  const v6Data = readJson(CONFIG.REFINED_V6_PATH) || {};

//   features = [features[0]];

  logger.log(`Loaded ${features.length} features for processing.`);

  const promptTemplate = loadPromptTemplate(CONFIG.PROMPT_PATH);
  const finalOutput = {};

  // 2. Iterate Features
  for (const [index, feat] of features.entries()) {
    const fid = feat.feature_id;
    logger.log(`\nProcessing feature ${index + 1}/${features.length}: ${fid}`);

    const kbEntry = kbData[fid] || {};
    const kbStrategy = kbEntry.passes ? { passes: kbEntry.passes } : null;
    const rationale = kbEntry.rationale || null;
    const refinedV5 = v5Data[fid] ? { passes: v5Data[fid].passes } : null;
    const refinedV6 = v6Data[fid] ? { passes: v6Data[fid].passes } : null;

    // Check for missing strategies to handle hardcoded delta strings
    let missingOverrides = {};
    if (!kbStrategy) {
      missingOverrides.delta_1 = "No KB strategy available to compute delta.";
      missingOverrides.delta_2 = "No KB strategy available to compute delta.";
    }
    if (!refinedV5) {
      missingOverrides.delta_1 =
        "No v5 (without rationale) strategy available to compute delta.";
      missingOverrides.delta_3 =
        "No v5 (without rationale) strategy available to compute delta.";
    }
    if (!refinedV6) {
      missingOverrides.delta_2 =
        "No v6 (with rationale) strategy available to compute delta.";
      missingOverrides.delta_3 =
        "No v6 (with rationale) strategy available to compute delta.";
    }

    // If ALL are missing, just apply overrides and skip LLM
    if (!kbStrategy && !refinedV5 && !refinedV6) {
      finalOutput[fid] = {
        delta_1: missingOverrides.delta_1,
        delta_2: missingOverrides.delta_2,
        delta_3: missingOverrides.delta_3,
      };
      continue;
    }

    // 3. Build Prompt
    const prompt = renderPrompt(promptTemplate, {
      FEATURE_INFO: feat.feature_info || "N/A",
      KB_STRATEGY: kbStrategy || "MISSING",
      RATIONALE: rationale || "MISSING",
      REFINED_V5: refinedV5 || "MISSING",
      REFINED_V6: refinedV6 || "MISSING",
    });

    savePrompt(`feature_${fid}`, prompt);

    // 4. Call Gemini
    const result = await generateWithGemini(prompt, `Feature: ${fid}`);

    // 5. Apply Overrides for missing data & Save
    if (result) {
      finalOutput[fid] = {
        delta_1: missingOverrides.delta_1 || result.delta_1 || "N/A",
        delta_2: missingOverrides.delta_2 || result.delta_2 || "N/A",
        delta_3: missingOverrides.delta_3 || result.delta_3 || "N/A",
      };
    } else {
      finalOutput[fid] = {
        delta_1: missingOverrides.delta_1 || "Error generating delta.",
        delta_2: missingOverrides.delta_2 || "Error generating delta.",
        delta_3: missingOverrides.delta_3 || "Error generating delta.",
      };
    }

    // Small delay to prevent rate limiting
    await new Promise((resolve) => setTimeout(resolve, 1500));
  }

  // 6. Output Results
  logger.section("SAVING RESULTS");
  writeJson(DELTA_OUTPUT_FILE, finalOutput);

  const endTime = Date.now();
  logger.log(
    `\nRun Complete. Total time: ${((endTime - startTime) / 1000).toFixed(2)} seconds.`,
  );
}

run().catch((err) => {
  console.error("FATAL ERROR:");
  console.error(err);
});
