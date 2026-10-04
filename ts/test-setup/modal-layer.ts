// Every jsdom suite starts with no modal.
import { afterEach } from "vitest";
import { resetModalLayerForTests } from "../elements/modal-layer.js";

if (typeof window !== "undefined") afterEach(resetModalLayerForTests);
