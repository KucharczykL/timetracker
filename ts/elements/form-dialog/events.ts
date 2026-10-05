import type { CreatedOption } from "../../generated/form-dialog.js";

/** Dispatched on `document`: shown data went stale. */
export const PAGE_STALE = "page:stale";

/** On the opening link; preventDefault() takes it. */
export const FORM_DIALOG_CREATED = "form-dialog:created";
export type FormDialogCreatedDetail = Readonly<CreatedOption>;

declare global {
  interface HTMLElementEventMap {
    [FORM_DIALOG_CREATED]: CustomEvent<FormDialogCreatedDetail>;
  }
}
