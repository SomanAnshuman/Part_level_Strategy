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

const PART = "PM0289-020-01";

const PART_FILES_MAP = {
  "PM0290-020-01": {
    features: "features1.json",
    part_context: "part_context1.json",
    machine_context: "machine_context1.json",
  },
  "PM0289-020-01": {
    features: "features2.json",
    part_context: "part_context2.json",
    machine_context: "machine_context2.json",
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
  OUTPUT_DIR: path.join(BASE_DIR, "outputs/v3"),
  LOG_DIR: path.join(BASE_DIR, "logs/v3"),

  PROMPT_PATHS: {
    FEATURE_STRATEGY: path.join(
      BASE_DIR,
      "prompts/v3/feature_strategy.prompt.txt",
    ),
    PART_STRATEGY: path.join(
      BASE_DIR,
      "prompts/v3/part_level_strategy.prompt.txt",
    ),
    FEATURE_TYPE_STRATEGY: path.join(
      BASE_DIR,
      "prompts/v3/feature_type_strategy.prompt.txt",
    ),
  },

  BATCH_SIZE: 1,
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
   DIRECTORY SETUP (FIXED)
========================= */

mkdirSync(CONFIG.LOG_DIR, { recursive: true });
mkdirSync(CONFIG.OUTPUT_DIR, { recursive: true });

const RUN_LOG_FILE = path.join(CONFIG.LOG_DIR, `run_${RUN_VERSION}.txt`);
const PROMPT_DUMP_DIR = path.join(CONFIG.LOG_DIR, `run_${RUN_VERSION}_prompts`);

mkdirSync(PROMPT_DUMP_DIR, { recursive: true });

const FEATURE_STRATEGY_OUTPUT_FILE = path.join(
  CONFIG.OUTPUT_DIR,
  `feature_strategies_run_${RUN_VERSION}.json`,
);

const PART_STRATEGY_OUTPUT_FILE = path.join(
  CONFIG.OUTPUT_DIR,
  `part_strategy_run_${RUN_VERSION}.json`,
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

  const result = await model.generateContent(prompt);
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

function chunkArray(arr, size) {
  const out = [];
  for (let i = 0; i < arr.length; i += size) {
    out.push(arr.slice(i, i + size));
  }
  return out;
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
    logger.log("⚠️ Invalid JSON received from model");
    return null;
  }
}

function groupByFeatureType(features, featureStrategies) {
  const grouped = {};

  for (const feature of features) {
    const featureId = feature.feature_id;
    const featureType = feature.feature_type || "unknown";

    if (!grouped[featureType]) {
      grouped[featureType] = {
        features: [],
        strategies: {},
      };
    }

    grouped[featureType].features.push(feature);

    if (featureStrategies[featureId]) {
      grouped[featureType].strategies[featureId] = featureStrategies[featureId];
    }
  }

  return grouped;
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

function buildFeatureStrategyPrompt(featureBatch) {
  const template = loadPromptTemplate(CONFIG.PROMPT_PATHS.FEATURE_STRATEGY);

  return renderPrompt(template, {
    FEATURE_BATCH: JSON.stringify(featureBatch, null, 2),
    PART_CONTEXT: JSON.stringify(PART_CONTEXT, null, 2),
    MACHINE_CONTEXT: JSON.stringify(MACHINE_CONTEXT, null, 2),
  });
}

function buildPartStrategyPrompt(features, featureTypeStrategies) {
  const template = loadPromptTemplate(CONFIG.PROMPT_PATHS.PART_STRATEGY);

  return renderPrompt(template, {
    CLUSTERING_PROMPT_RESULT: JSON.stringify(featureTypeStrategies, null, 2),
    PART_CONTEXT: JSON.stringify(PART_CONTEXT, null, 2),
    MACHINE_CONTEXT: JSON.stringify(MACHINE_CONTEXT, null, 2),
  });
}

function buildFeatureTypeStrategyPrompt(featureType, features, strategies) {
  const template = loadPromptTemplate(
    CONFIG.PROMPT_PATHS.FEATURE_TYPE_STRATEGY,
  );

  return renderPrompt(template, {
    FEATURE_TYPE: featureType,
    FEATURE_LIST: JSON.stringify(features, null, 2),
    FEATURE_STRATEGIES: JSON.stringify(strategies, null, 2),
    PART_CONTEXT: JSON.stringify(PART_CONTEXT, null, 2),
  });
}

/* =========================
   PIPELINES
========================= */

async function generateFeatureStrategies(features) {
  const batches = chunkArray(features, CONFIG.BATCH_SIZE);
  logger.log(`Processing ${batches.length} feature batches`);

  const merged = {};

  for (let i = 0; i < batches.length; i++) {
    logger.section(`FEATURE BATCH ${i + 1}`);

    const prompt = buildFeatureStrategyPrompt(batches[i]);
    const response = await generateWithGemini(prompt, `feature_batch_${i + 1}`);

    const parsed = safeJsonParse(response);
    if (parsed) Object.assign(merged, parsed);
  }

  return merged;
}

async function generatePartStrategy(features, featureTypeStrategies) {
  const prompt = buildPartStrategyPrompt(features, featureTypeStrategies);
  return generateWithGemini(prompt, "part_level_strategy");
}

async function generateFeatureTypeStrategies(features, featureStrategies) {
  const grouped = groupByFeatureType(features, featureStrategies);

  const results = {};

  for (const [featureType, data] of Object.entries(grouped)) {
    logger.section(`FEATURE TYPE → ${featureType}`);

    const prompt = buildFeatureTypeStrategyPrompt(
      featureType,
      data.features,
      data.strategies,
    );

    const response = await generateWithGemini(
      prompt,
      `feature_type_${featureType}`,
    );

    const parsed = safeJsonParse(response);
    if (parsed) {
      results[featureType] = parsed;
    }
  }

  return results;
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
    batch_size: CONFIG.BATCH_SIZE,
    start_time: new Date(startTime).toISOString(),
  });

  const features = readJson(CONFIG.FEATURES_FILE_PATH);
  logger.log(`Total features: ${features.length}`);

  const featureStrategies = await generateFeatureStrategies(features);
  writeJson(FEATURE_STRATEGY_OUTPUT_FILE, featureStrategies);

  const featureTypeStrategies = await generateFeatureTypeStrategies(
    features,
    featureStrategies,
  );

  writeJson(
    path.join(
      CONFIG.OUTPUT_DIR,
      `feature_type_strategies_run_${RUN_VERSION}.json`,
    ),
    featureTypeStrategies,
  );

  const partStrategyText = await generatePartStrategy(
    features,
    featureTypeStrategies,
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
