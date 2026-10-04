// Every jsdom suite starts with an empty stack.
import { afterEach } from "vitest";
import { resetSurfacesForTests } from "../elements/surface-stack.js";

if (typeof window !== "undefined") afterEach(resetSurfacesForTests);
