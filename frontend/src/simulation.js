const radians = (degrees) => degrees * Math.PI / 180;

export function distanceKm(a, b) {
  const dlat = radians(b[1] - a[1]), dlon = radians(b[0] - a[0]);
  const h = Math.sin(dlat / 2) ** 2 + Math.cos(radians(a[1])) * Math.cos(radians(b[1])) * Math.sin(dlon / 2) ** 2;
  return 6371 * 2 * Math.atan2(Math.sqrt(h), Math.sqrt(Math.max(0, 1 - h)));
}

export function buildTrack(coordinates) {
  if (!Array.isArray(coordinates) || coordinates.length < 2 || coordinates.some(p => !Array.isArray(p) || p.length !== 2 || p.some(v => !Number.isFinite(v)))) {
    throw new Error('Géométrie de trajet invalide.');
  }
  const cumulative = [0];
  for (let i = 1; i < coordinates.length; i++) cumulative.push(cumulative[i - 1] + distanceKm(coordinates[i - 1], coordinates[i]));
  if (cumulative.at(-1) <= 0) throw new Error('Le trajet doit contenir deux points distincts.');
  return { coordinates, cumulative, total: cumulative.at(-1) };
}

export function sampleTrack(track, fraction) {
  const progress = Math.min(1, Math.max(0, fraction));
  if (progress === 1) return { position: track.coordinates.at(-1), travelled: track.coordinates };
  const target = progress * track.total;
  let i = 1;
  while (i < track.cumulative.length - 1 && track.cumulative[i] <= target) i++;
  const length = track.cumulative[i] - track.cumulative[i - 1];
  const ratio = length > 0 ? (target - track.cumulative[i - 1]) / length : 0;
  const a = track.coordinates[i - 1], b = track.coordinates[i];
  const position = [a[0] + (b[0] - a[0]) * ratio, a[1] + (b[1] - a[1]) * ratio];
  return { position, travelled: [...track.coordinates.slice(0, i), position] };
}

export function advanceSimulation(elapsed, realSeconds, speed, durationSeconds) {
  if (![elapsed, realSeconds, speed, durationSeconds].every(Number.isFinite) || elapsed < 0 || realSeconds < 0 || speed <= 0 || durationSeconds <= 0) {
    throw new Error('Paramètres de simulation invalides.');
  }
  return Math.min(durationSeconds, elapsed + realSeconds * speed);
}
