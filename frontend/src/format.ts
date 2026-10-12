/** "+1,240 ft", or an honest label when no elevation data covers the route. */
export function formatGain(gainFt: number | null | undefined): string {
  return gainFt === null || gainFt === undefined ? 'Elevation unavailable' : `+${Math.round(gainFt).toLocaleString()} ft`;
}
