import type { CreatedOption } from "../../generated/form-dialog.js";

/** Dispatched on `document`: shown data went stale. */
export const PAGE_STALE = "page:stale";

/** Dispatched on the opening link; take it to keep the row. */
export const FORM_DIALOG_CREATED = "form-dialog:created";
export type FormDialogCreatedDetail = CreatedOption;
