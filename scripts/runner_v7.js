require("dotenv").config();

const {
  mkdirSync,
  createWriteStream,
  readFileSync,
  writeFileSync,
} = require("fs");
const path = require("path");
const { GoogleGenerativeAI } = require("@google/generative-ai");

/* =========================
   CONFIG
========================= */

const BASE_DIR = path.resolve(__dirname, "..");

const PART = "NIST_Part1";

const PART_FILES_MAP = {
  "PM0290-020-01": {
    features: "features1.json",
    part_context: "part_context1.json",
    machine_context: "machine_context1.json",
    strategy_list: "PM0290-020-01_strategies.json",
  },
  "PM0289-020-01": {
    features: "features2.json",
    part_context: "part_context2.json",
    machine_context: "machine_context2.json",
    strategy_list: "PM0289-020-01_strategies.json",
  },
  "FIXTURE-01": {
    features: "features3.json",
    part_context: "part_context3.json",
    machine_context: "machine_context3.json",
    strategy_list: "FIXTURE-01_strategies.json",
  },
  msc_step_1: {
    features: "features4.json",
    part_context: "part_context4.json",
    machine_context: "machine_context4.json",
    strategy_list: "msc_step_1_strategies.json",
  },
  NIST_Part1: {
    features: "features_NIST_1.json",
    part_context: "part_context_NIST_1.json",
    machine_context: "machine_context_NIST_1.json",
    strategy_list: "NIST_1_strategies.json",
    spatial_context: "NIST_Part1_context.txt",
  },
  NIST_Part2: {
    features: "features_NIST_2.json",
    part_context: "part_context_NIST_2.json",
    machine_context: "machine_context_NIST_1.json",
    strategy_list: "NIST_2_strategies.json",
    spatial_context: "NIST_Part2_context.txt",
  },
};

const CONFIG = {
  FEATURES_FILE_PATH: path.join(
    BASE_DIR,
    `inputs/${PART_FILES_MAP[PART].features}`,
  ),
  PART_CONTEXT_PATH: path.join(
    BASE_DIR,
    `inputs/${PART_FILES_MAP[PART].part_context}`,
  ),
  MACHINE_CONTEXT_PATH: path.join(
    BASE_DIR,
    `inputs/${PART_FILES_MAP[PART].machine_context}`,
  ),
  STRATEGY_LIST_PATH: path.join(
    BASE_DIR,
    `inputs/v4/${PART_FILES_MAP[PART].strategy_list}`,
  ),
  SPATIAL_CONTEXT_PATH: path.join(
    BASE_DIR,
    `inputs/spatial_part_context/${PART_FILES_MAP[PART].spatial_context}`,
  ),
  OUTPUT_DIR: path.join(BASE_DIR, "outputs/v7"),
  LOG_DIR: path.join(BASE_DIR, "logs/v7"),

  PROMPT_PATHS: {
    PART_STRATEGY: path.join(
      BASE_DIR,
      "prompts/v7/part_level_strategy.prompt.txt",
    ),
    FEATURE_REFINEMENT: path.join(
      BASE_DIR,
      "prompts/v7/feature_strategy_refinement.prompt.txt",
    ),
  },

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
   RUN CONTEXT
========================= */

function getRunVersion() {
  const arg = process.argv.find((a) => a.startsWith("--run="));
  if (!arg) {
    throw new Error("Missing required CLI argument: --run=<version>");
  }
  return arg.split("=")[1];
}

const RUN_VERSION = getRunVersion();

/* =========================
   DIRECTORY SETUP
========================= */

mkdirSync(CONFIG.LOG_DIR, { recursive: true });
mkdirSync(CONFIG.OUTPUT_DIR, { recursive: true });

const RUN_LOG_FILE = path.join(CONFIG.LOG_DIR, `run_${RUN_VERSION}.txt`);
const PROMPT_DUMP_DIR = path.join(CONFIG.LOG_DIR, `run_${RUN_VERSION}_prompts`);

mkdirSync(PROMPT_DUMP_DIR, { recursive: true });

const PART_STRATEGY_OUTPUT_FILE = path.join(
  CONFIG.OUTPUT_DIR,
  `part_strategy_run_${RUN_VERSION}.json`,
);

const REFINED_STRATEGY_OUTPUT_FILE = path.join(
  CONFIG.OUTPUT_DIR,
  `refined_strategies_run_${RUN_VERSION}.json`,
);

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
  savePrompt(label, prompt);

  logger.section(`PROMPT → ${label}`);
  logger.log(prompt);

  const result = await model.generateContent({
    contents: [{ role: "User", parts: [{ text: prompt }] }],
    generationConfig: { temperature: 0.2 },
  });
  const response = cleanMarkdownJson(result.response.text());

  logger.section(`MODEL OUTPUT → ${label}`);
  logger.log(response);

  return response;
}

/* =========================
   FILE & GENERIC UTILS
========================= */

function readJson(filePath) {
  return JSON.parse(readFileSync(filePath, "utf-8"));
}

function writeJson(filePath, data) {
  writeFileSync(filePath, JSON.stringify(data, null, 2), "utf-8");
  logger.log(`Saved file → ${filePath}`);
}

function cleanMarkdownJson(text) {
  return text
    .replace(/```json\s*/gi, "")
    .replace(/```/g, "")
    .trim();
}

function safeJsonParse(text) {
  try {
    return JSON.parse(text);
  } catch {
    logger.log("Invalid JSON received from model");
    return null;
  }
}

/* =========================
   CONSTANT CONTEXT
========================= */

const PART_CONTEXT = readJson(CONFIG.PART_CONTEXT_PATH);
const MACHINE_CONTEXT = readJson(CONFIG.MACHINE_CONTEXT_PATH);

logger.section("CONTEXT LOADED");
logger.log({ PART_CONTEXT, MACHINE_CONTEXT });

/* =========================
   PROMPT TEMPLATE UTILS
========================= */

function loadPromptTemplate(filePath) {
  return readFileSync(filePath, "utf-8");
}

function renderPrompt(template, variables) {
  let output = template;
  for (const [key, value] of Object.entries(variables)) {
    output = output.replace(new RegExp(`{{${key}}}`, "g"), value);
  }
  return output;
}

function savePrompt(label, content) {
  const filePath = path.join(PROMPT_DUMP_DIR, `${label}.txt`);
  writeFileSync(filePath, content, "utf-8");
  logger.log(`Saved prompt → ${filePath}`);
}

/* =========================
   PROMPT BUILDERS
========================= */
function buildStrategyRefinementPrompt(feature, baselineStrategy) {
  const template = loadPromptTemplate(CONFIG.PROMPT_PATHS.FEATURE_REFINEMENT);

  return renderPrompt(template, {
    FEATURE_DATA: JSON.stringify(feature, null, 2),
    BASELINE_STRATEGY: JSON.stringify(baselineStrategy, null, 2),
    PART_CONTEXT: JSON.stringify(PART_CONTEXT, null, 2),
    MACHINE_CONTEXT: JSON.stringify(MACHINE_CONTEXT, null, 2),
  });
}

function buildPartStrategyPrompt(features, featureStrategies, spatialContext) {
  const template = loadPromptTemplate(CONFIG.PROMPT_PATHS.PART_STRATEGY);

  return renderPrompt(template, {
    FEATURE_LIST: JSON.stringify(features, null, 2),
    FEATURE_STRATEGIES: JSON.stringify(featureStrategies, null, 2),
    SPATIAL_CONTEXT: JSON.stringify(spatialContext, null, 2),
    PART_CONTEXT: JSON.stringify(PART_CONTEXT, null, 2),
    MACHINE_CONTEXT: JSON.stringify(MACHINE_CONTEXT, null, 2),
  });
}

/* =========================
   PIPELINES
========================= */
// Pipeline to refine strategies individually
async function refineStrategies(features, originalStrategies) {
  const refinedMap = {};

  // Create a map of features by ID for easy lookup
  // Assuming feature objects have an 'id' property. If not, adjust accordingly.
  const featureMap = features.reduce((acc, f) => {
    if (f.feature_id) acc[f.feature_id] = f;
    return acc;
  }, {});

  const strategyKeys = Object.keys(originalStrategies);
  logger.log(`Starting refinement for ${strategyKeys.length} strategies...`);

  for (const [index, key] of strategyKeys.entries()) {
    logger.log(`In process: Refining strategy for feature ${index + 1}`);
    const strategy = originalStrategies[key];
    const feature = featureMap[key];

    // Fallback if feature ID logic doesn't match perfectly,
    // or if strategies are indexed differently.
    if (!feature) {
      logger.log(
        `Warning: Corresponding feature not found for strategy key: ${key}. Skipping refinement.`,
      );
      refinedMap[key] = strategy;
      continue;
    }

    const label = `refine_strategy_${key}`;
    const prompt = buildStrategyRefinementPrompt(feature, strategy);

    // Call Gemini
    const response = await generateWithGemini(prompt, label);
    const parsed = safeJsonParse(response);

    if (parsed) {
      refinedMap[key] = parsed;
    } else {
      logger.log(`Failed to parse refinement for ${key}, keeping original.`);
      refinedMap[key] = strategy;
    }
  }

  return refinedMap;
}

async function generatePartStrategy(
  features,
  featureStrategies,
  spatialContext,
) {
  const prompt = buildPartStrategyPrompt(
    features,
    featureStrategies,
    spatialContext,
  );
  return generateWithGemini(prompt, "part_level_strategy");
}

/* =========================
   MAIN
========================= */

async function run() {
  const startTime = Date.now();

  logger.section("RUN METADATA");
  logger.log({
    run_version: RUN_VERSION,
    model: CONFIG.MODEL_NAME,
    start_time: new Date(startTime).toISOString(),
  });

  const features = readJson(CONFIG.FEATURES_FILE_PATH);
  logger.log(`Total features: ${features.length}`);

  // Cleaning features to contain only necessary data
  const cleanedFeatures = features.map((feat) => ({
    feature_id: feat.feature_id,
    feature_type: feat.feature_type,
    feature_info: feat.feature_info,
    feature_name: feat.feature_name,
    coordinate_system: feat.coordinate_system,
    origin_coordinate_system: feat.origin_coordinate_system,
    cam_specific_names: feat.cam_specific_names,
    position_info: feat.position_info,
  }));

  const spatialContext = loadPromptTemplate(CONFIG.SPATIAL_CONTEXT_PATH);
  const originalFeatureStrategies = readJson(CONFIG.STRATEGY_LIST_PATH);

  // Refinement Step
  logger.section("STEP 1: STRATEGY REFINEMENT");
  const refinedStrategies = await refineStrategies(
    cleanedFeatures,
    originalFeatureStrategies,
  );

  // Save intermediate refined strategies
  writeJson(REFINED_STRATEGY_OUTPUT_FILE, refinedStrategies);

  // Pass refinedStrategies to Part Strategy Prompt
  logger.section("STEP 2: PART LEVEL STRATEGY");
  const partStrategyText = await generatePartStrategy(
    cleanedFeatures,
    refinedStrategies,
    spatialContext,
  );

  const partStrategyJson = safeJsonParse(partStrategyText);
  if (partStrategyJson) {
    writeJson(PART_STRATEGY_OUTPUT_FILE, partStrategyJson);
  }

  const endTime = Date.now();
  const durationMs = endTime - startTime;

  logger.section("RUN COMPLETE");
  logger.log({
    end_time: new Date(endTime).toISOString(),
    total_time_seconds: (durationMs / 1000).toFixed(2),
  });
}

run().catch((err) => {
  logger.section("FATAL ERROR");
  logger.log(err.stack || err);
});
