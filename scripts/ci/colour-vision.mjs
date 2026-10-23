import Color from "colorjs.io";
// Machado severity-1 matrices, applied to linear sRGB. Published numeric coefficients:
// https://www.inf.ufrgs.br/~oliveira/pubs_files/CVD_Simulation/CVD_Simulation.html
// https://github.com/colour-science/colour/blob/develop/colour/blindness/datasets/machado2010.py
export const MATRICES = {
  protanopia: [[.152286, 1.052583, -.204868], [.114503, .786281, .099216], [-.003882, -.048116, 1.051998]],
  deuteranopia: [[.367322, .860646, -.227968], [.280085, .672501, .047413], [-.011820, .042940, .968881]],
  tritanopia: [[1.255528, -.076749, -.178779], [-.078411, .930809, .147602], [.004733, .691367, .303900]],
};
export function simulate(value, mode) {
  const rgb = new Color(value).to("srgb-linear").coords;
  return new Color("srgb-linear", MATRICES[mode].map((row) => Math.max(0, Math.min(1, row.reduce((sum, coefficient, i) => sum + coefficient * rgb[i], 0)))));
}
export function colourVisionReport(tokens) {
  const roles = ["verified", "hint", "misconception", "highlight", "series-1", "series-2", "series-3", "series-4"];
  const rows = [];
  const resolve = (role, theme, seen = new Set()) => {
    if (seen.has(role)) throw new Error(`Cyclic colour alias: ${role}`);
    seen.add(role);
    return tokens.aliases[role] ? resolve(tokens.aliases[role], theme, seen) : tokens.color[role][theme];
  };
  for (const theme of ["light", "dark"]) for (const mode of Object.keys(MATRICES)) for (let i = 0; i < roles.length; i++) for (let j = i + 1; j < roles.length; j++) {
    const a = resolve(roles[i], theme), b = resolve(roles[j], theme);
    const distance = simulate(a, mode).deltaE(simulate(b, mode), "2000");
    rows.push({ theme, mode, roles: [roles[i], roles[j]], colours: [a, b], delta_e_2000: Number(distance.toFixed(4)), pass: distance >= 10 });
  }
  return { candidate_acceptance: false, method: "Machado severity 1, linear sRGB clipping, CIEDE2000", threshold: 10, failures: rows.filter((r) => !r.pass), rows };
}
