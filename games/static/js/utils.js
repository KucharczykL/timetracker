/**
 * @description Formats Date to a UTC string accepted by the datetime-local input field.
 * @param {Date} date
 * @returns {string}
 */
export function toISOUTCString(date) {
  function stringAndPad(number) {
    return number.toString().padStart(2, 0);
  }
  const year = date.getFullYear();
  const month = stringAndPad(date.getMonth() + 1);
  const day = stringAndPad(date.getDate());
  const hours = stringAndPad(date.getHours());
  const minutes = stringAndPad(date.getMinutes());
  return `${year}-${month}-${day}T${hours}:${minutes}`;
}
