// The three sizes every pit wall page is checked at (ADR 0003 point 5).
import type { PlaywrightTestOptions } from "@playwright/test";

export interface Viewport {
  name: string;
  use: Partial<PlaywrightTestOptions>;
}

export const VIEWPORTS: Viewport[] = [
  {
    name: "phone",
    use: { viewport: { width: 390, height: 844 }, deviceScaleFactor: 3, isMobile: true, hasTouch: true },
  },
  {
    name: "ipad",
    use: { viewport: { width: 820, height: 1180 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true },
  },
  {
    name: "desktop",
    use: { viewport: { width: 1440, height: 900 } },
  },
];
