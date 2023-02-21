/**
 * @description Formats Date to a UTC string accepted by the datetime-local input field.
 * @param {Date} date
 * @returns {string}
 */
export function toISOUTCString(date) {
  let month = (date.getMonth() + 1).toString().padStart(2, 0);
  return `${date.getFullYear()}-${month}-${date.getDate()}T${date.getHours()}:${date.getMinutes()}`;
}
