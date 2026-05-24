export type Verdict = "low" | "mid" | "high";

export function classify(value: number, flag: boolean): Verdict {
  if (value < 10 && flag) {
    return "low";
  } else if (value < 100) {
    return "mid";
  }
  return "high";
}

export const sumPositive = (values: number[]): number => {
  let total = 0;
  for (const v of values) {
    if (v > 0) {
      total += v;
    }
  }
  return total;
};
