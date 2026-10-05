import type { CreatedOption } from "../../generated/form-dialog.js";

/** Dispatched on `document`: shown data went stale. */
export const PAGE_STALE = "page:stale";

/** Fired on the opening link; take to keep. */
export const FORM_DIALOG_CREATED = "form-dialog:created";
export type FormDialogCreatedDetail = CreatedOption;
