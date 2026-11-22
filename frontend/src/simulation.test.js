import test from 'node:test';
import assert from 'node:assert/strict';
import { buildTrack, sampleTrack, advanceSimulation } from './simulation.js';

test('progress follows distance rather than vertex count', () => {
  const track = buildTrack([[0, 0], [1, 0], [4, 0]]);
  assert.ok(Math.abs(sampleTrack(track, .5).position[0] - 2) < 1e-9);
});
test('start, end and clamping preserve coordinates', () => {
  const points = [[-7, 33], [-6, 34]], track = buildTrack(points);
  assert.deepEqual(sampleTrack(track, -1).position, points[0]);
  assert.deepEqual(sampleTrack(track, 2).position, points[1]);
});
test('duplicate vertices do not create invalid coordinates', () => {
  const track = buildTrack([[0, 0], [0, 0], [1, 0]]);
  assert.ok(sampleTrack(track, 0).position.every(Number.isFinite));
  assert.throws(() => buildTrack([[0, 0], [0, 0]]));
});
test('elapsed time respects playback speed and ends exactly', () => {
  assert.equal(advanceSimulation(0, 2, 120, 1000), 240);
  assert.equal(advanceSimulation(900, 2, 120, 1000), 1000);
  assert.throws(() => advanceSimulation(0, -1, 120, 1000));
});
