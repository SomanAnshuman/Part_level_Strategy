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

const PART = "FIXTURE-01";
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
      `prompts/tools_and_params/m2/tool_rec_part.prompt.txt`,
    ),
    PARAM_REC: path.join(
      BASE_DIR,
      `prompts/tools_and_params/m2/param_rec_part.prompt.txt`,
    ),
  },
  OUTPUT_DIR: path.join(BASE_DIR, `outputs/tool_and_params/m2`),
  LOG_DIR: path.join(BASE_DIR, `logs/tool_and_params/m2`),
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
  logger.section(`STARTING RUN: ${RUN_VERSION} Part Level`);

  // 1. Load Contexts
  const features = readJson(CONFIG.INPUTS.FEATURES);
  const partContext = readJson(CONFIG.INPUTS.PART);
  const machineContext = readJson(CONFIG.INPUTS.MACHINE);
  const strategyInput = readJson(CONFIG.INPUTS.PART_STRATEGY);

  logger.log(`Loaded Strategy with ${strategyInput.setups.length} setups.`);

  // 2. Generate Tools
  let strategyWithTools;
  strategyWithTools = await step1_GenerateTools_PartLevel(
    strategyInput,
    features,
    partContext,
    machineContext,
  );

  writeOutput(OUTPUT_FILE_TOOLS, strategyWithTools);

  // 3. Generate Parameters
  let finalStrategy;
  finalStrategy = await step2_GenerateParams_PartLevel(
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
  PART LEVEL FLOW (Single Call for Whole Part)
========================================================= */

async function step1_GenerateTools_PartLevel(
  strategyData,
  allFeatures,
  partContext,
  machineContext,
) {
  logger.section("STEP 1: TOOL RECOMMENDATION (PART LEVEL)");
  const promptTemplate = loadPrompt(CONFIG.PROMPTS.TOOL_REC);

  // 1. Aggregate ENTIRE Strategy Context
  const fullContext = strategyData.setups.map((setup) => ({
    setup_id: setup.setup_id,
    description: setup.description,
    orientation: setup.orientation_vector,
    workholding: setup.workholding_note,
    operations: setup.operations.map((op) => ({
      sequence_order: op.sequence_order,
      operation_type: op.operation_type,
      strategy_details: op.strategy_details,
      feature_summary: summarizeFeatures(
        findFeatures(op.feature_ids, allFeatures),
      ),
    })),
  }));

  // 2. Prompt
  const prompt = renderPrompt(promptTemplate, {
    MACHINE_CONTEXT: JSON.stringify(machineContext),
    PART_CONTEXT: JSON.stringify(partContext),
    FULL_STRATEGY: JSON.stringify(fullContext),
  });

  // 3. LLM Call (Expect this to take longer due to token output size)
  const responseText = await generateWithGemini(
    prompt,
    `tools_part_level`,
    `run_${RUN_VERSION}`,
  );
  const globalToolMap = safeJsonParse(responseText) || [];
  // Expecting format: [{ setup_id: 1, operations: [{ sequence_order: 10, selected_tool: {...} }] }]

  // 4. Merge Data
  const enrichedSetups = strategyData.setups.map((setup) => {
    const setupRec = globalToolMap.find((s) => s.setup_id === setup.setup_id);
    if (!setupRec) return setup;

    const enrichedOps = setup.operations.map((op) => {
      const opRec = setupRec.operations?.find(
        (o) => o.sequence_order === op.sequence_order,
      );
      return {
        ...op,
        tools: opRec ? [opRec.selected_tool] : [],
      };
    });
    return { ...setup, operations: enrichedOps };
  });

  return { ...strategyData, setups: enrichedSetups };
}

async function step2_GenerateParams_PartLevel(
  strategyData,
  allFeatures,
  partContext,
  machineContext,
) {
  logger.section("STEP 2: PARAMETERS (PART LEVEL)");
  const promptTemplate = loadPrompt(CONFIG.PROMPTS.PARAM_REC);

  // 1. Context: Setups -> Operations (that have tools)
  const fullContext = strategyData.setups
    .map((setup) => ({
      setup_id: setup.setup_id,
      operations: setup.operations
        .filter((op) => op.tools && op.tools.length > 0)
        .map((op) => ({
          sequence_order: op.sequence_order,
          operation_type: op.operation_type,
          selected_tool: op.tools[0],
          feature_summary: summarizeFeatures(
            findFeatures(op.feature_ids, allFeatures),
          ),
        })),
    }))
    .filter((s) => s.operations.length > 0);

  // 2. Prompt
  const prompt = renderPrompt(promptTemplate, {
    MACHINE_CONTEXT: JSON.stringify(machineContext),
    PART_CONTEXT: JSON.stringify(partContext),
    FULL_STRATEGY_WITH_TOOLS: JSON.stringify(fullContext),
  });

  // 3. LLM Call
  const responseText = await generateWithGemini(
    prompt,
    `params_part_level`,
    `run_${RUN_VERSION}`,
  );
  const globalParamMap = safeJsonParse(responseText) || [];

  // 4. Merge
  const finalSetups = strategyData.setups.map((setup) => {
    const setupRec = globalParamMap.find((s) => s.setup_id === setup.setup_id);
    if (!setupRec) return setup;

    const finalOps = setup.operations.map((op) => {
      const opRec = setupRec.operations?.find(
        (o) => o.sequence_order === op.sequence_order,
      );
      if (opRec && op.tools.length > 0) {
        const toolWithParams = {
          ...op.tools[0],
          recommended_params: opRec.parameters,
        };
        return { ...op, tools: [toolWithParams] };
      }
      return op;
    });
    return { ...setup, operations: finalOps };
  });

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
