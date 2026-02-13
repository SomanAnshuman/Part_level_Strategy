const path = require("path");
const { readFileSync, writeFileSync } = require("fs");

const BASE_DIR = path.resolve(__dirname, "..");

const PART = "NIST_2";

const CONFIG = {
  INPUT_DATA: path.join(BASE_DIR, `inputs/v4/${PART}_toolpaths.json`),
  OUTPUT_DIR: path.join(BASE_DIR, `inputs/v4`),
};

/**
 * Extracts machining strategies mapped to feature_ids,
 * stripping out tool definitions and parameters.
 *
 * @param {Object} data - The raw JSON input containing machining setups.
 * @returns {Object} - The cleaned strategy map keyed by feature_id.
 */
function extractStrategies(data) {
  const result = {};

  // 1. Traverse Machining Setups
  const setups = data.machiningSetups || [];

  setups.forEach((setup) => {
    // 2. Traverse Features
    const features = setup.features || [];

    features.forEach((feature) => {
      const featureId = feature.feature_id;

      // Skip if no feature_id exists
      if (!featureId) return;

      // Initialize the entry in the result map
      if (!result[featureId]) {
        result[featureId] = { passes: [] };
      }

      // 3. Access Strategies
      const strategiesList = feature.featureInformation?.strategies || [];

      strategiesList.forEach((strategyEntry) => {
        const machStrategies = strategyEntry.machining_strategy || [];

        const passes = machStrategies[0]?.passes ?? [];

        // 4. Map Passes and Clean Operations
        const cleanPasses = passes.map((passItem) => {
          return {
            pass: passItem.pass,
            operations: (passItem.operations || []).map((op) => {
              return {
                operation: op.operation,
                location: op.location,
                tool_paths: [op.tool_paths[0]],
              };
            }),
          };
        });

        // Aggregate the cleaned passes into the feature result
        result[featureId].passes.push(...cleanPasses);
      });
    });
  });

  return result;
}

// --- Usage Example ---

// Assuming 'inputData' is the JSON object provided in your prompt
const inputData = readJson(CONFIG.INPUT_DATA);

function readJson(p) {
  return JSON.parse(readFileSync(p, "utf-8"));
}

function writeOutput(p, d) {
  writeFileSync(p, JSON.stringify(d, null, 2));
}

const extracted = extractStrategies(inputData);
writeOutput(path.join(CONFIG.OUTPUT_DIR, `${PART}_strategies.json`), extracted);
