import type { CreatedOption } from "../../generated/form-dialog.js";

/** Dispatched on `document`: shown data went stale. */
export const PAGE_STALE = "page:stale";

/** On the opening link; preventDefault() takes it. */
export const FORM_DIALOG_CREATED = "form-dialog:created";
export type FormDialogCreatedDetail = Readonly<CreatedOption>;

/** Load a URL as the dialog's baseline. */
export const FORM_DIALOG_RELOAD = "form-dialog:reload";
export interface FormDialogReloadDetail {
  url: string;
}

declare global {
  interface HTMLElementEventMap {
    [FORM_DIALOG_CREATED]: CustomEvent<FormDialogCreatedDetail>;
    [FORM_DIALOG_RELOAD]: CustomEvent<FormDialogReloadDetail>;
  }
}
