import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** Class names joined, later Tailwind classes winning (shadcn/ui's helper). */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
