// The vetted visual renderers (VSL-18): one renderer per kind of the S2 catalogue (VSL-03), its gap additions
// (VSL-04) and the S2 simulations (VSL-08). Board-channel kinds (working_board, knowns_panel) are drawn by the board.
import type { VisualRenderer } from "./contract.js";
import { bankReconciliation, financialStatements, journalEntry, matrixTable, tAccount, trialBalance } from "./accounting.js";
import { balancedEquation, electronShells, energyProfile, particleDiagram, periodicTable } from "./chemistry.js";
import { breakEvenChart, functionGraph, motionGraph, statisticsChart, titrationCurve } from "./graphs.js";
import { libraryDiagram } from "./library.js";
import { bearingDiagram, geometryFigure, numberLine, probabilityTree, transformationGrid, unitCircle, vennDiagram } from "./maths.js";
import { circuit, freeBody, motionDiagram, rayDiagram, waveDiagram } from "./physics.js";
import { electrolysisSetup, electrolysisSimulation } from "./sims/electrolysis.js";
import { equilibriumSetup, equilibriumSimulation } from "./sims/equilibrium.js";
import { functionSetup, functionTransformSimulation } from "./sims/functions.js";
import { gasLawsSimulation, gasSetup } from "./sims/gas.js";
import { ratesSetup, ratesSimulation } from "./sims/rates.js";
import type { ResolvedSpec } from "./contract.js";
import type { SimModel, SimSetup } from "./sims/models.js";
import { circuitSimulation, projectileSim, titrationSimulation } from "./sims/index.js";

export const RENDERERS: readonly VisualRenderer[] = [functionGraph, numberLine, geometryFigure, unitCircle, vennDiagram, statisticsChart, matrixTable, bearingDiagram, freeBody, motionGraph, circuit, rayDiagram, waveDiagram, libraryDiagram, projectileSim, circuitSimulation, balancedEquation, particleDiagram, electronShells, periodicTable, titrationCurve, energyProfile, titrationSimulation, journalEntry, tAccount, trialBalance, financialStatements, bankReconciliation, breakEvenChart, probabilityTree, transformationGrid, motionDiagram, gasLawsSimulation, functionTransformSimulation, electrolysisSimulation, ratesSimulation, equilibriumSimulation];

export type { LabelMode, PartInfo, ResolvedSpec, SimEvent, Size, TableData, Translate, VisualProps, VisualRenderer } from "./contract.js";
export { sample, parse as parseExpression, evaluate, ExprError } from "./expr.js";
export { stepCount, stepForBoard, stepState } from "./steps.js";
export { CONTENT_COLOURS } from "./generated/content_colours.js";
export { parseSvg, svgProblems, reactProps, type SvgNode } from "./library_svg.js";
export { circuitReadings, endPoint, projectile as projectileModel, circuitSim as circuitModel, titrationSim as titrationModel, titrationPh, sig } from "./sims/models.js";
export { runToEnd } from "./sims/SimView.js";
export { electrolysis as electrolysisModel, electrolysisReadings, equilibrium as equilibriumModel, equilibriumTimescale, kcAt, functionTransform as functionModel, gasLaws as gasModel, gasPressure, GAS_CONSTANT, rateConstant, rates as ratesModel, ratesReadings, transformed } from "./sims/science.js";
export { SCENARIOS, scenarioOf, observe as observeScenario, compare as comparePrediction, type Scenario } from "./sims/predict.js";

/** The S3 simulations' setup from a resolved spec (model, starting values, locked controls), by kind. */
export const SIM_SETUPS: Record<string, (spec: ResolvedSpec) => SimSetup<unknown>> = {
  gas_laws_sim: gasSetup as (spec: ResolvedSpec) => SimSetup<unknown>,
  function_transform_sim: functionSetup as (spec: ResolvedSpec) => SimSetup<unknown>,
  electrolysis_sim: electrolysisSetup as (spec: ResolvedSpec) => SimSetup<unknown>,
  rates_sim: ratesSetup as (spec: ResolvedSpec) => SimSetup<unknown>,
  equilibrium_sim: equilibriumSetup as (spec: ResolvedSpec) => SimSetup<unknown>,
};
export type { SimModel, SimSetup };
