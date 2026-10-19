// Telling a failed chunk load from any other error (#296 R6): an old tab after a
// deploy asks for route chunks whose hashed names are gone. Each browser words it
// differently, and Vite's preload helper adds its own.
const CHUNK_MESSAGES = [
  /failed to fetch dynamically imported module/i, // Chromium
  /error loading dynamically imported module/i, // Firefox
  /importing a module script failed/i, // Safari
  /unable to preload css/i, // Vite, a route's stylesheet
];

/** The kit's ErrorState, which RouteError loads lazily. main.tsx asks for it as the
 * app starts, so a tab left open over a deploy still has it. */
export const loadErrorState = () => import("@/components/error-state");

export function isChunkLoadError(error: unknown): boolean {
  if (!(error instanceof Error)) {
    return false;
  }
  return error.name === "ChunkLoadError" || CHUNK_MESSAGES.some((re) => re.test(error.message));
}
