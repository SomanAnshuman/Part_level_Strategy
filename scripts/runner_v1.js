require("dotenv").config();

const fs = require("fs");
const path = require("path");
const { GoogleGenerativeAI } = require("@google/generative-ai");

/* =========================
   PATH RESOLUTION
========================= */

const ROOT = path.resolve(__dirname, "..");

function r(p) {
  return path.join(ROOT, p);
}

/* =========================
   CONFIG
========================= */

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
  FEATURES_FILE: r(`inputs/${PART_FILES_MAP[PART].features}`),
  PART_CONTEXT_PATH: r(`inputs/${PART_FILES_MAP[PART].part_context}`),
  MACHINE_CONTEXT_PATH: r(`inputs/${PART_FILES_MAP[PART].machine_context}`),

  OUTPUT_DIR: r("outputs/v1"),
  LOG_DIR: r("logs/v1"),

  PROMPT_TEMPLATES: {
    FEATURE_LEVEL: r("prompts/v1/feature_level.prompt.txt"),
    PART_LEVEL: r("prompts/v1/part_level_strategy.prompt.txt"),
    FEATURE_BATCH: r("prompts/v1/feature_batch.prompt.txt"),
  },

  MODEL_NAME: "gemini-pro-latest",
  BATCH_SIZE: 10,
  API_KEY: process.env.GEMINI_API_KEY,
};

if (!CONFIG.API_KEY) {
  throw new Error("Missing GEMINI_API_KEY in .env");
}

/* =========================
   RUN CONTEXT
========================= */

function getRunVersion() {
  const arg = process.argv.find((a) => a.startsWith("--run="));
  if (!arg) throw new Error("Missing CLI arg --run=<version>");
  return arg.split("=")[1];
}

const RUN_VERSION = getRunVersion();

const RUN_DIR = path.join(CONFIG.LOG_DIR, `run_${RUN_VERSION}`);
const PROMPT_DIR = path.join(RUN_DIR, "prompts");
const RESPONSE_DIR = path.join(RUN_DIR, "responses");

[CONFIG.OUTPUT_DIR, CONFIG.LOG_DIR, RUN_DIR, PROMPT_DIR, RESPONSE_DIR].forEach(
  (dir) => fs.mkdirSync(dir, { recursive: true }),
);

const LOG_FILE = path.join(RUN_DIR, "run.log");

/* =========================
   LOGGER
========================= */

function createLogger(file) {
  const stream = fs.createWriteStream(file, { flags: "a" });

  function log(...args) {
    const msg = args
      .map((v) => (typeof v === "string" ? v : JSON.stringify(v, null, 2)))
      .join(" ");
    const line = `[${new Date().toISOString()}] ${msg}\n`;
    stream.write(line);
    console.log(msg);
  }

  function section(title) {
    log("\n==============================");
    log(title);
    log("==============================\n");
  }

  return { log, section };
}

const logger = createLogger(LOG_FILE);

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf-8"));
}

/* =========================
   CONSTANT CONTEXT
========================= */

const PART_CONTEXT = readJson(CONFIG.PART_CONTEXT_PATH);
const MACHINE_CONTEXT = readJson(CONFIG.MACHINE_CONTEXT_PATH);

logger.section("CONTEXT LOADED");
logger.log({ PART_CONTEXT, MACHINE_CONTEXT });

/* =========================
   GEMINI
========================= */

const genAI = new GoogleGenerativeAI(CONFIG.API_KEY);
const model = genAI.getGenerativeModel({ model: CONFIG.MODEL_NAME });

/* =========================
   UTILS
========================= */

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
    logger.log("⚠️ Invalid JSON, saving raw text");
    return null;
  }
}

function loadPromptTemplate(file) {
  return fs.readFileSync(file, "utf-8");
}

function renderPrompt(template, vars) {
  let out = template;
  for (const [k, v] of Object.entries(vars)) {
    out = out.replace(new RegExp(`{{${k}}}`, "g"), v);
  }
  return out;
}

function saveArtifact(dir, name, content) {
  fs.writeFileSync(path.join(dir, name), content, "utf-8");
}

/* =========================
   PIPELINE
========================= */

async function run() {
  const start = Date.now();

  logger.section("RUN METADATA");
  logger.log({
    run: RUN_VERSION,
    model: CONFIG.MODEL_NAME,
    batch_size: CONFIG.BATCH_SIZE,
  });

  const features = JSON.parse(fs.readFileSync(CONFIG.FEATURES_FILE, "utf-8"));
  if (!Array.isArray(features)) throw new Error("features.json must be array");

  logger.log(`Total features: ${features.length}`);

  const batches = chunkArray(features, CONFIG.BATCH_SIZE);

  /* ===== FEATURE LEVEL ===== */

  const featureTemplate = loadPromptTemplate(
    CONFIG.PROMPT_TEMPLATES.FEATURE_LEVEL,
  );
  const featurePrompt = renderPrompt(featureTemplate, {
    TOTAL_BATCHES: batches.length,
  });

  saveArtifact(PROMPT_DIR, "feature_level_prompt.txt", featurePrompt);

  logger.section("FEATURE LEVEL STRATEGY");
  const chat = model.startChat();
  await chat.sendMessage(featurePrompt);

  let lastResponse = "";

  for (let i = 0; i < batches.length; i++) {
    const batchTemplate = loadPromptTemplate(
      CONFIG.PROMPT_TEMPLATES.FEATURE_BATCH,
    );
    const batchPrompt = renderPrompt(batchTemplate, {
      TOTAL_BATCHES: batches.length,
      FEATURE_BATCH: JSON.stringify(batches[i], null, 2),
      CURRENT_BATCH_NUMBER: i + 1,
    });

    saveArtifact(PROMPT_DIR, `batch_${i + 1}.txt`, batchPrompt);

    const res = await chat.sendMessage(batchPrompt);
    lastResponse = res.response.text();

    saveArtifact(RESPONSE_DIR, `batch_${i + 1}_response.txt`, lastResponse);

    logger.log(`Processed batch ${i + 1}/${batches.length}`);
  }

  const cleanedFeatureResponse = cleanMarkdownJson(lastResponse);
  saveArtifact(
    RESPONSE_DIR,
    "feature_level_final.json",
    cleanedFeatureResponse,
  );

  const featureStrategies = safeJsonParse(cleanedFeatureResponse);

  /* ===== PART LEVEL ===== */

  const partTemplate = loadPromptTemplate(CONFIG.PROMPT_TEMPLATES.PART_LEVEL);
  const partPrompt = renderPrompt(partTemplate, {
    PART_CONTEXT: JSON.stringify(PART_CONTEXT, null, 2),
    MACHINE_CONTEXT: JSON.stringify(MACHINE_CONTEXT, null, 2),
    FEATURES: JSON.stringify(features, null, 2),
    FEATURE_STRATEGIES: JSON.stringify(featureStrategies, null, 2),
  });

  saveArtifact(PROMPT_DIR, "part_level_prompt.txt", partPrompt);

  const partResult = await model.generateContent(partPrompt);
  const partResponse = cleanMarkdownJson(partResult.response.text());

  saveArtifact(RESPONSE_DIR, "part_level_strategy.json", partResponse);

  const parsedPart = safeJsonParse(partResponse);
  if (parsedPart) {
    fs.writeFileSync(
      path.join(CONFIG.OUTPUT_DIR, `part_strategy_run_${RUN_VERSION}.json`),
      JSON.stringify(parsedPart, null, 2),
    );
  }

  const duration = ((Date.now() - start) / 1000).toFixed(2);

  logger.section("RUN COMPLETE");
  logger.log({ total_time_seconds: duration });
}

run().catch((err) => {
  logger.section("FATAL ERROR");
  logger.log(err.stack || err);
});
