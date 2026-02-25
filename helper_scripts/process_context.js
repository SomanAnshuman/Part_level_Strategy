const { mkdirSync, readFileSync, writeFileSync, existsSync } = require("fs");
const path = require("path");

// Configuration
const BASE_DIR = path.resolve(__dirname, "..");
const INPUT_DIR = path.join(BASE_DIR, "inputs");
const OUTPUT_DIR = path.join(BASE_DIR, "inputs", "spatial_part_context");

const PARTS = ["NIST_Part1"];

const PART_FILES_MAP = {
  "PM0290-020-01": { features: "features1.json" },
  "PM0289-020-01": { features: "features2.json" },
  "FIXTURE-01": { features: "features3.json" },
  msc_step_1: { features: "features4.json" },
  NIST_Part1: { features: "features_NIST_1.json" },
  NIST_Part2: { features: "features_NIST_2.json" },
};

// Utility to handle floating point inaccuracies (e.g., 50.00000003 -> 50)
function round(value, decimals = 3) {
  return Number(Math.round(value + "e" + decimals) + "e-" + decimals);
}

// Extract the logical "cutting depth" based on the feature type
function getFeatureDepth(feat) {
  if (!feat.feature_info) return 0;

  // Priority 1: Explicit depth
  if (feat.feature_info.depth !== undefined) {
    return feat.feature_info.depth;
  }
  // Priority 2: Face milling uses stock_to_remove as depth
  if (
    feat.feature_type === "face" &&
    feat.feature_info.stock_to_remove !== undefined
  ) {
    return feat.feature_info.stock_to_remove;
  }
  // Priority 3: Edge chamfers use length (or hole_depth if attached to a hole)
  if (feat.feature_type === "edge") {
    return feat.feature_info.length || feat.feature_info.hole_depth || 0;
  }
  return 0;
}

// Ensure output directory exists
if (!existsSync(OUTPUT_DIR)) {
  mkdirSync(OUTPUT_DIR, { recursive: true });
}

// Process each part
for (const partName of PARTS) {
  const fileData = PART_FILES_MAP[partName];
  const inputFilePath = path.join(INPUT_DIR, fileData.features);

  if (!existsSync(inputFilePath)) {
    console.warn(`[SKIP] File not found for ${partName}: ${inputFilePath}`);
    continue;
  }

  const rawData = readFileSync(inputFilePath, "utf8");
  let features = [];
  try {
    features = JSON.parse(rawData);
  } catch {
    console.error(`[ERROR] Invalid JSON in ${fileData.features}`);
    continue;
  }

  // Advanced Data Structure: Group by Vector -> Then group by Plane
  const setupAnalysis = {};

  features.forEach((feat) => {
    const id = feat.feature_id;
    const name = feat.feature_name || feat.feature_type;

    // 1. Extract Approach Vector
    let vx = 0,
      vy = 0,
      vz = 1; // Default Top
    if (feat.coordinate_system) {
      vx = feat.coordinate_system.Zx || 0;
      vy = feat.coordinate_system.Zy || 0;
      vz = feat.coordinate_system.Zz || 0;
    }

    const vectorStr = `[${round(vx)}, ${round(vy)}, ${round(vz)}]`;

    if (!setupAnalysis[vectorStr]) {
      setupAnalysis[vectorStr] = {
        features: [],
        planes: {},
        extents: [],
      };
    }

    setupAnalysis[vectorStr].features.push({ id, name });

    // 2. Calculate Coplanar starting points & Extents using Dot Product
    if (feat.position_info && feat.position_info.length > 0) {
      const pos = feat.position_info[0];

      // DOT PRODUCT: Project the 3D point onto the Approach Vector to find the true Plane value
      const startPlane = round(pos.X * vx + pos.Y * vy + pos.Z * vz);

      // Group into planes for this specific setup vector
      if (!setupAnalysis[vectorStr].planes[startPlane]) {
        setupAnalysis[vectorStr].planes[startPlane] = [];
      }
      setupAnalysis[vectorStr].planes[startPlane].push({ id, name });

      // Calculate Depth Extents
      const depth = round(getFeatureDepth(feat));
      const endPlane = round(startPlane - depth);

      // Check for through features
      let isThrough = "";
      if (
        feat.feature_info &&
        (feat.feature_info.bottom_type === "through" ||
          feat.feature_info.hole_type === "through")
      ) {
        isThrough = " [THROUGH FEATURE]";
      }

      setupAnalysis[vectorStr].extents.push(
        `- ${name} (${id}): Starts at Plane=${startPlane}, Ends at Plane=${endPlane} (Depth: ${depth})${isThrough}`,
      );
    }
  });

  // Generate the Formatted LLM Context String
  let contextString = `\n`;

  for (const [vector, data] of Object.entries(setupAnalysis)) {
    contextString += `=========================================\n`;
    contextString += `SETUP APPROACH VECTOR: ${vector} (Total Features: ${data.features.length})\n`;
    contextString += `=========================================\n`;

    contextString += `Coplanar Groups (Features sharing the same starting plane along this vector):\n`;
    // Sort planes highest to lowest (approaching from outside in)
    const sortedPlanes = Object.keys(data.planes)
      .map(Number)
      .sort((a, b) => b - a);
    for (const plane of sortedPlanes) {
      const featSummaries = data.planes[plane]
        .map((f) => `${f.name} (${f.id})`)
        .join(", ");
      contextString += `   * Plane Value = ${plane}: ${featSummaries}\n`;
    }

    contextString += `\nDepth Penetration Analysis (Relative to Approach Vector):\n`;
    contextString += data.extents.join("\n") + "\n\n";
  }

  // Write to Output
  const outputFilePath = path.join(OUTPUT_DIR, `${partName}_context.txt`);
  writeFileSync(outputFilePath, contextString, "utf8");

  console.log(
    `[SUCCESS] Generated context for ${partName} -> ${outputFilePath}`,
  );
}
