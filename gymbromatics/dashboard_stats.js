/* Pure kinematics over the current, possibly manually edited repetition. */
function calculateRepStats(samples, rep, fps) {
  const segment = samples.slice(rep.start, rep.end + 1);
  const ascent = samples.slice(rep.bottom, rep.end + 1);
  const knees = segment.map(s => s.knee).filter(Number.isFinite);
  const speeds = ascent.map(s => s.velocity).filter(Number.isFinite);
  let pause = null;
  // Missing hip samples make the pause unknown, rather than zero.
  if (segment.every(s => Number.isFinite(s.hip_y_smoothed_px) && Number.isFinite(s.hip_velocity))) {
    const positions = segment.map(s => s.hip_y_smoothed_px);
    const bottomY = Math.max(...positions);
    const excursion = bottomY - Math.min(...positions);
    const peakSpeed = Math.max(...segment.map(s => Math.abs(s.hip_velocity)));
    const slow = i => samples[i].hip_y_smoothed_px >= bottomY - excursion * 0.05 &&
      Math.abs(samples[i].hip_velocity) <= peakSpeed * 0.1;
    if (excursion > 0 && peakSpeed > 0) {
      pause = 0;
      if (slow(rep.bottom)) {
        let first = rep.bottom, last = rep.bottom;
        while (first > rep.start && slow(first - 1)) first--;
        while (last < rep.end && slow(last + 1)) last++;
        const duration = (last - first) / fps;
        pause = duration >= 0.2 ? duration : 0;
      }
    }
  }
  return {
    duration: (rep.end - rep.start) / fps,
    knee: knees.length ? Math.min(...knees) : null,
    kneePartial: knees.length > 0 && knees.length < segment.length,
    pause,
    peak: speeds.length ? Math.max(0, ...speeds) : null,
    peakPartial: speeds.length > 0 && speeds.length < ascent.length,
  };
}
