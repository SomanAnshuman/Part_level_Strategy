require("dotenv").config();
const path = require("path");
const {
  mkdirSync,
  createWriteStream,
  readFileSync,
  writeFileSync,
  existsSync,
} = require("fs");
const { GoogleGenerativeAI } = require("@google/generative-ai");

/* =========================
   CONFIG
========================= */
const BASE_DIR = path.resolve(__dirname, "..");

const PART = "msc_step_1";
const PART_STRATEGY_FLOW = "v5";

const PART_FILES_MAP = {
  "FIXTURE-01": {
    features: "features3.json",
    part_context: "part_context3.json",
    machine_context: "machine_context3.json",
    part_level_strategy: `${PART_STRATEGY_FLOW}/part_strategy_run_6.json`,
  },
  msc_step_1: {
    features: "features4.json",
    part_context: "part_context4.json",
    machine_context: "machine_context4.json",
    part_level_strategy: `${PART_STRATEGY_FLOW}/part_strategy_run_7.json`,
  },
};

function getRunVersion() {
  const arg = process.argv.find((a) => a.startsWith("--run="));
  return arg ? arg.split("=")[1] : "1";
}
const RUN_VERSION = getRunVersion();

const CONFIG = {
  INPUTS: {
    FEATURES: path.join(BASE_DIR, `inputs/${PART_FILES_MAP[PART].features}`),
    PART: path.join(BASE_DIR, `inputs/${PART_FILES_MAP[PART].part_context}`),
    MACHINE: path.join(
      BASE_DIR,
      `inputs/${PART_FILES_MAP[PART].machine_context}`,
    ),
    // Assuming the input strategy is the one provided in your prompt
    PART_STRATEGY: path.join(
      BASE_DIR,
      `outputs/${PART_FILES_MAP[PART].part_level_strategy}`,
    ),
  },
  PROMPTS: {
    // We will use dynamic prompt loading or specific files based on mode
    TOOL_REC: path.join(
      BASE_DIR,
      `prompts/tools_and_params/m1/tool_rec_setup.prompt.txt`,
    ),
    PARAM_REC: path.join(
      BASE_DIR,
      `prompts/tools_and_params/m1/param_rec_setup.prompt.txt`,
    ),
  },
  OUTPUT_DIR: path.join(BASE_DIR, `outputs/tool_and_params/m1`),
  LOG_DIR: path.join(BASE_DIR, `logs/tool_and_params/m1`),
  MODEL_NAME: "gemini-pro-latest",
  API_KEY: process.env.GEMINI_API_KEY,
};

/* =========================
   SETUP & UTILS
========================= */
if (!CONFIG.API_KEY) throw new Error("Missing GEMINI_API_KEY");

mkdirSync(CONFIG.LOG_DIR, { recursive: true });
mkdirSync(CONFIG.OUTPUT_DIR, { recursive: true });

const logger = createLogger(
  path.join(CONFIG.LOG_DIR, `run_${RUN_VERSION}.log`),
);
const genAI = new GoogleGenerativeAI(CONFIG.API_KEY);
const model = genAI.getGenerativeModel({
  model: CONFIG.MODEL_NAME,
  generationConfig: { responseMimeType: "application/json" }, // Force JSON mode
});

const OUTPUT_FILE_TOOLS = path.join(
  CONFIG.OUTPUT_DIR,
  `part_strategy_tools_${PART}_${PART_STRATEGY_FLOW}_run_${RUN_VERSION}.json`,
);
const OUTPUT_FILE_PARAMS = path.join(
  CONFIG.OUTPUT_DIR,
  `part_strategy_final_${PART}_${PART_STRATEGY_FLOW}_run_${RUN_VERSION}.json`,
);

/* =========================
   CORE PIPELINE
========================= */
async function run() {
  const startTime = Date.now();
  logger.section(`STARTING RUN: ${RUN_VERSION} Setup Level`);

  // 1. Load Contexts
  const features = readJson(CONFIG.INPUTS.FEATURES);
  const partContext = readJson(CONFIG.INPUTS.PART);
  const machineContext = readJson(CONFIG.INPUTS.MACHINE);
  const strategyInput = readJson(CONFIG.INPUTS.PART_STRATEGY);

  logger.log(`Loaded Strategy with ${strategyInput.setups.length} setups.`);

  // 2. Generate Tools
  let strategyWithTools;

  strategyWithTools = await step1_GenerateTools_SetupLevel(
    strategyInput,
    features,
    partContext,
    machineContext,
  );
  writeOutput(OUTPUT_FILE_TOOLS, strategyWithTools);

  // 3. Generate Parameters
  let finalStrategy;

  finalStrategy = await step2_GenerateParams_SetupLevel(
    strategyWithTools,
    features,
    partContext,
    machineContext,
  );
  writeOutput(OUTPUT_FILE_PARAMS, finalStrategy);

  const endTime = Date.now();
  logger.section("RUN COMPLETE");
  logger.log({ total_time_seconds: ((endTime - startTime) / 1000).toFixed(2) });
}

/* =========================================================
  SETUP LEVEL FLOW (Batch per Setup)
========================================================= */

async function step1_GenerateTools_SetupLevel(
  strategyData,
  allFeatures,
  partContext,
  machineContext,
) {
  logger.section("STEP 1: TOOL RECOMMENDATION (SETUP LEVEL)");
  const promptTemplate = loadPrompt(CONFIG.PROMPTS.TOOL_REC);
  const enrichedSetups = [];

  for (const setup of strategyData.setups) {
    logger.log(
      `Processing Setup ${setup.setup_id}: ${setup.operations.length} operations`,
    );

    // 1. Prepare Context for ALL operations in this setup
    const opsContext = setup.operations.map((op) => ({
      sequence_order: op.sequence_order,
      operation_type: op.operation_type,
      strategy_details: op.strategy_details,
      feature_summary: summarizeFeatures(
        findFeatures(op.feature_ids, allFeatures),
      ),
    }));

    // 2. Construct Prompt
    const prompt = renderPrompt(promptTemplate, {
      MACHINE_CONTEXT: JSON.stringify(machineContext),
      PART_CONTEXT: JSON.stringify(partContext),
      SETUP_DESC: setup.description,
      ORIENTATION: JSON.stringify(setup.orientation_vector),
      WORKHOLDING: setup.workholding_note,
      OPERATIONS_LIST: JSON.stringify(opsContext),
    });

    // 3. Call LLM
    const responseText = await generateWithGemini(
      prompt,
      `tools_setup_${setup.setup_id}`,
      `run_${RUN_VERSION}`,
    );
    const recommendedToolsMap = safeJsonParse(responseText) || [];

    // 4. Map results back to operations
    const enrichedOps = setup.operations.map((op) => {
      // Find the tool recommendation for this specific sequence
      const rec = recommendedToolsMap.find(
        (r) => r.sequence_order === op.sequence_order,
      );
      return {
        ...op,
        // We only want a single tool now, but keeping array format for compatibility if needed
        tools: rec ? [rec.selected_tool] : [],
      };
    });

    enrichedSetups.push({ ...setup, operations: enrichedOps });
  }

  return { ...strategyData, setups: enrichedSetups };
}

async function step2_GenerateParams_SetupLevel(
  strategyData,
  allFeatures,
  partContext,
  machineContext,
) {
  logger.section("STEP 2: PARAMETERS (SETUP LEVEL)");
  const promptTemplate = loadPrompt(CONFIG.PROMPTS.PARAM_REC);
  const finalSetups = [];

  for (const setup of strategyData.setups) {
    // Filter only ops that have tools
    const validOps = setup.operations.filter(
      (op) => op.tools && op.tools.length > 0,
    );
    if (validOps.length === 0) {
      finalSetups.push(setup);
      continue;
    }

    // 1. Prepare Context
    const opsContext = validOps.map((op) => ({
      sequence_order: op.sequence_order,
      operation_type: op.operation_type,
      selected_tool: op.tools[0], // Taking the single selected tool
      feature_summary: summarizeFeatures(
        findFeatures(op.feature_ids, allFeatures),
      ),
    }));

    // 2. Prompt
    const prompt = renderPrompt(promptTemplate, {
      MACHINE_CONTEXT: JSON.stringify(machineContext),
      PART_CONTEXT: JSON.stringify(partContext),
      SETUP_DESC: setup.description,
      OPERATIONS_WITH_TOOLS: JSON.stringify(opsContext),
    });

    // 3. LLM
    const responseText = await generateWithGemini(
      prompt,
      `params_setup_${setup.setup_id}`,
      `run_${RUN_VERSION}`,
    );
    const paramsMap = safeJsonParse(responseText) || [];

    // 4. Merge
    const finalOps = setup.operations.map((op) => {
      const pRec = paramsMap.find(
        (p) => p.sequence_order === op.sequence_order,
      );
      if (pRec && op.tools.length > 0) {
        const toolWithParams = {
          ...op.tools[0],
          recommended_params: pRec.parameters,
        };
        return { ...op, tools: [toolWithParams] };
      }
      return op;
    });

    finalSetups.push({ ...setup, operations: finalOps });
  }

  return { ...strategyData, setups: finalSetups };
}

/* =========================
   HELPERS
========================= */
function findFeatures(ids, allFeatures) {
  if (!ids || !Array.isArray(ids)) return [];
  return allFeatures.filter((f) => ids.includes(f.feature_id));
}

function summarizeFeatures(features) {
  return features.map((f) => ({
    feature_id: f.feature_id,
    feature_type: f.feature_type,
    // Sending slightly more info now as context is aggregated
    dimensions: f.feature_info,
    coordinate_system: f.coordinate_system,
  }));
}

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

async function generateWithGemini(prompt, label, subfolder) {
  const folderPath = path.join(CONFIG.LOG_DIR, subfolder);
  if (!existsSync(folderPath)) mkdirSync(folderPath, { recursive: true });

  writeFileSync(path.join(folderPath, `${label}.prompt.txt`), prompt);

  try {
    const result = await model.generateContent(prompt);
    const txt = result.response.text();
    writeFileSync(path.join(folderPath, `${label}.response.txt`), txt);
    return txt;
  } catch (e) {
    logger.log(`API Error on ${label}: ${e.message}`);
    return "[]";
  }
}

function readJson(p) {
  return JSON.parse(readFileSync(p, "utf-8"));
}
function writeOutput(p, d) {
  writeFileSync(p, JSON.stringify(d, null, 2));
  logger.log(`Saved ${p}`);
}
function loadPrompt(p) {
  return readFileSync(p, "utf-8");
}
function renderPrompt(t, v) {
  let out = t;
  for (const [k, val] of Object.entries(v))
    out = out.replace(new RegExp(`{{${k}}}`, "g"), val);
  return out;
}
function cleanMarkdownJson(t) {
  return t
    .replace(/```json\s*/gi, "")
    .replace(/```/g, "")
    .trim();
}
function safeJsonParse(t) {
  try {
    return JSON.parse(cleanMarkdownJson(t));
  } catch {
    return null;
  }
}

// Run
run().catch(console.error);
