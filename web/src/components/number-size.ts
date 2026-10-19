// The sizes a number comes in, shared by LapTime, Gap and Position so a lap row's
// figures match: sm in a phone's lap table, md in text, xl in the session hero.
export type NumberSize = "sm" | "md" | "xl";

export const NUMBER_SIZES: Record<NumberSize, string> = {
  sm: "num text-sm",
  md: "num text-base",
  xl: "num-xl",
};
