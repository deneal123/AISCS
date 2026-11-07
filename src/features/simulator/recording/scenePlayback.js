import { sceneSpikeHistogram } from './electricalTimeline';
import { playableTimeline } from './playableTimeline';
import { directFieldTimeline } from './recordingScope';
import { stimulusSeries } from './targetTimeline';

// A newly placed draft cannot be paired with an earlier run's trace.
export function scenePlayback({ activeField, activeFieldConfig, activeFieldPreview, activeTarget,
  fieldContactDraft, direct, motorReadout, preview, sceneField, verifiedProxyHistogram }) {
  const networkOnly = Boolean(direct && activeField);
  const directTimeline = networkOnly ? directFieldTimeline(activeField) : null;
  if (networkOnly && !directTimeline) return null;
  const stimulus = activeTarget ? stimulusSeries(activeFieldPreview) : null;
  const candidate = activeField ? {
    time_ms: networkOnly ? directTimeline.time_ms : activeTarget?.time_ms || activeFieldPreview?.time_ms,
    signal_uv: networkOnly ? null : activeTarget?.neural_uv || activeFieldPreview?.neural_uv,
    networkOnly,
    stimulus_fraction: networkOnly ? directTimeline.stimulus_fraction : activeTarget ? stimulus?.values : activeFieldPreview?.stimulus_fraction,
    stimulus_time_ms: networkOnly ? directTimeline.stimulus_time_ms : stimulus?.time_ms,
    stimulus_current_na: networkOnly ? activeField.configuration?.current_na
      : activeFieldConfig?.simulation?.current_na,
    electrical: true,
    connectome: {
      kind: sceneField?.result?.manifest?.kind,
      spikes_by_ms: sceneSpikeHistogram(sceneField, activeFieldPreview?.network_spikes_by_ms,
        motorReadout, activeFieldConfig?.simulation?.duration_ms, verifiedProxyHistogram),
    },
  } : fieldContactDraft ? null : preview;
  return playableTimeline(candidate) ? candidate : null;
}
