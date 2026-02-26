require("dotenv").config();
const { GoogleGenAI } = require("@google/genai");
const {
  createWriteStream,
  mkdirSync,
  readFileSync,
  writeFileSync,
} = require("fs");
const path = require("path");

/* =========================
   ENVIRONMENT & CLI SETUP
========================= */
const BASE_DIR = process.cwd();

// Allow running via CLI: node helper_scripts/extract_rationale.js <PART_NAME>
const PART = process.argv[2];
const SHOULD_DECLARE_FILES = true;

if (!PART) {
  console.error(
    "Error: Please provide a PART name as a command line argument.",
  );
  console.error("Example: node generate_rationale.js <PART_NAME>");
  process.exit(1);
}

const PART_FILES_MAP = {
  "PM0290-020-01": {
    features: "features1.json",
    strategy_list: "PM0290-020-01_strategies.json",
  },
  "PM0289-020-01": {
    features: "features2.json",
    strategy_list: "PM0289-020-01_strategies.json",
  },
  "FIXTURE-01": {
    features: "features3.json",
    strategy_list: "FIXTURE-01_strategies.json",
  },
  msc_step_1: {
    features: "features4.json",
    strategy_list: "msc_step_1_strategies.json",
  },
  NIST_Part1: {
    features: "features_NIST_1.json",
    strategy_list: "NIST_1_strategies.json",
  },
  NIST_Part2: {
    features: "features_NIST_2.json",
    strategy_list: "NIST_2_strategies.json",
  },
};

if (!PART_FILES_MAP[PART]) {
  console.error(`Error: Part "${PART}" not found in PART_FILES_MAP.`);
  process.exit(1);
}

const CONFIG = {
  FEATURES_FILE_PATH: path.join(
    BASE_DIR,
    `inputs/${PART_FILES_MAP[PART].features}`,
  ),
  STRATEGY_LIST_PATH: path.join(
    BASE_DIR,
    `inputs/v4/${PART_FILES_MAP[PART].strategy_list}`,
  ),
  OUTPUT_DIR: path.join(
    BASE_DIR,
    `outputs/rationale/${SHOULD_DECLARE_FILES ? "by_files" : "wo_files"}`,
  ),
  LOG_DIR: path.join(
    BASE_DIR,
    `logs/rationale/${SHOULD_DECLARE_FILES ? "by_files" : "wo_files"}`,
  ),
  PROMPT_PATHS: {
    EXTRACT_RATIONALE: path.join(
      BASE_DIR,
      `prompts/helper_prompts/extract_rationale${SHOULD_DECLARE_FILES ? "_by_files" : ""}.prompt.txt`,
    ),
  },
};

const RAG_FILES_MAP = {
  simple_hole: ["SIMPLE_HOLE_RULES_WITH_RATIONALE.txt"],
  taper_hole: ["TAPER_HOLE_MACHINING_RULES_WITH_RATIONALE.txt"],
  thread_hole: ["THREAD_HOLE_MACHINING_RULES_WITH_RATIONALE.txt"],
  side_face: ["SIDE_FACE_MACHINING_RULES_WITH_RATIONALE.txt"],
  top_face: ["TOP_FACE_MACHINING_RULES_WITH_RATIONALE.txt"],
  bottom_face: ["BOTTOM_FACE_MACHINING_RULES_WITH_RATIONALE.txt"],
  groove: ["GROOVE_MACHINING_RULES_WITH_RATIONALE.txt"],
  pocket_2d: ["POCKET_2D_MACHINING_RULES_WITH_RATIONALE.txt"],
  slot: ["SLOT_MACHINING_RULES_WITH_RATIONALE.txt"],
  pocket_with_island: ["POCKET_WITH_ISLAND_MACHINING_RULES_WITH_RATIONALE.txt"],
  chamfer: ["CHAMFER_MACHINING_RULES_WITH_RATIONALE.txt"],
  fillet: ["FILLET_MACHINING_RULES_WITH_RATIONALE.txt"],
};

const common_files = ["STRATEGY_GDNT_RULES_WITH_RATIONALE.txt"];

/* =========================
   DIRECTORY SETUP
========================= */
mkdirSync(CONFIG.LOG_DIR, { recursive: true });
mkdirSync(CONFIG.OUTPUT_DIR, { recursive: true });

const RUN_LOG_FILE = path.join(CONFIG.LOG_DIR, `${PART}.txt`);
const PROMPT_DUMP_DIR = path.join(CONFIG.LOG_DIR, `${PART}_prompts`);
mkdirSync(PROMPT_DUMP_DIR, { recursive: true });

const RATIONALE_OUTPUT_FILE = path.join(
  CONFIG.OUTPUT_DIR,
  `${PART}_rationale.json`,
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
   VERTEX AI INITIALIZATION
========================= */
const ai = new GoogleGenAI({
  apiKey: process.env.GOOGLE_CLOUD_API_KEY,
  vertexai: true,
});
const model = "gemini-3.1-pro-preview";

const tools = [
  {
    retrieval: {
      vertexRagStore: {
        ragResources: [
          {
            ragCorpus:
              "projects/596922971010/locations/asia-south1/ragCorpora/4611686018427387904",
          },
        ],
      },
    },
  },
];

const generationConfig = {
  maxOutputTokens: 65535,
  temperature: 0.2, // TODO: figure out best temp for strategy generation
  topP: 0.95,
  thinkingConfig: { thinkingLevel: "HIGH" },
  safetySettings: [
    { category: "HARM_CATEGORY_HATE_SPEECH", threshold: "OFF" },
    { category: "HARM_CATEGORY_DANGEROUS_CONTENT", threshold: "OFF" },
    { category: "HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold: "OFF" },
    { category: "HARM_CATEGORY_HARASSMENT", threshold: "OFF" },
  ],
  tools: tools,
};

/* =========================
   UTILS
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

function readJson(filePath) {
  return JSON.parse(readFileSync(filePath, "utf-8"));
}

function writeJson(filePath, data) {
  writeFileSync(filePath, JSON.stringify(data, null, 2), "utf-8");
  logger.log(`Saved file → ${filePath}`);
}

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/* =========================
   MAIN EXECUTION
========================= */
async function processAllFeatures() {
  const startTime = Date.now();
  logger.section(`Starting Rationale Generation for ${PART}`);

  // 1. Load data
  const featuresArray = readJson(CONFIG.FEATURES_FILE_PATH);
  const strategiesObj = readJson(CONFIG.STRATEGY_LIST_PATH);
  const promptTemplate = loadPromptTemplate(
    CONFIG.PROMPT_PATHS.EXTRACT_RATIONALE,
  );

  // 2. Map features by feature_id for fast lookup
  const featureMap = {};
  for (const feature of featuresArray) {
    featureMap[feature.feature_id] = feature;
  }

  // 3. Iterate through strategies
  let processedCount = 0;
  const totalStrategies = Object.keys(strategiesObj).length;

  for (const [feature_id, strategyData] of Object.entries(strategiesObj)) {
    processedCount++;
    logger.log(
      `\nProcessing feature ${processedCount}/${totalStrategies}: ${feature_id}`,
    );

    // Skip empty passes
    if (!strategyData.passes || strategyData.passes.length === 0) {
      logger.log(`Skipping - No passes generated for this feature.`);
      strategiesObj[feature_id].rationale = "No machining passes generated.";
      continue;
    }

    const featureContext = featureMap[feature_id];
    if (!featureContext) {
      logger.log(
        `Warning: feature_id ${feature_id} not found in features.json. Skipping.`,
      );
      continue;
    }

    // 4. Render Prompt
    // Passing only the crucial sub-objects to keep context window focused
    let promptText = renderPrompt(promptTemplate, {
      FEATURE_INFO: JSON.stringify(
        {
          feature_type: featureContext.feature_type,
          feature_info: featureContext.feature_info,
          feature_name: featureContext.feature_name,
        },
        null,
        2,
      ),
      GENERATED_STRATEGY: JSON.stringify(strategyData.passes, null, 2),
    });

    if (SHOULD_DECLARE_FILES) {
      let rule_files_array =
        RAG_FILES_MAP[featureContext.feature_name].concat(common_files);
      if (featureContext.feature_info.hasOwnProperty("island_info")) {
        rule_files_array = rule_files_array.concat(
          RAG_FILES_MAP.pocket_with_island,
        );
      }
      let rule_files = "";
      for (const item of rule_files_array) rule_files += item + "\n";

      promptText = renderPrompt(promptText, {
        LIST_OF_FILES: rule_files,
      });
    }

    savePrompt(`feature_${feature_id}`, promptText);

    // 5. Call LLM
    try {
      logger.log(`Generating rationale via RAG...`);
      const req = {
        model: model,
        contents: [{ role: "user", parts: [{ text: promptText }] }],
        config: generationConfig,
      };
      strategiesObj[feature_id].rationale = "";

      const response = await ai.models.generateContentStream(req);

      for await (const chunk of response) {
        if (chunk.text) {
          strategiesObj[feature_id].rationale += chunk.text;
        } else {
          strategiesObj[feature_id].rationale += JSON.stringify(chunk) + "\n";
        }
      }
      logger.log(
        `Rationale generated successfully as following:\n${strategiesObj[feature_id].rationale}`,
      );
    } catch (error) {
      logger.log(
        `Error generating rationale for ${feature_id}: ${error.message}`,
      );
      strategiesObj[feature_id].rationale = "Error generating rationale.";
    }

    // 6. Rate Limit Delay (2 seconds to avoid slamming Vertex endpoint)
    await delay(2000);
  }

  // 7. Save final aggregated JSON
  logger.section(`Writing Final Output`);
  writeJson(RATIONALE_OUTPUT_FILE, strategiesObj);
  logger.log(`Finished processing for ${PART}`);

  const endTime = Date.now();
  const durationMs = endTime - startTime;
  logger.log({
    end_time: new Date(endTime).toISOString(),
    total_time_seconds: (durationMs / 1000).toFixed(2),
  });
}

processAllFeatures();
