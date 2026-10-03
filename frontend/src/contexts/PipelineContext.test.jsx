import { act, render } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { PipelineProvider } from './PipelineContext';
import { usePipeline } from './usePipeline';

const api = vi.hoisted(() => ({ getPipelineStatus: vi.fn() }));
vi.mock('../api/themes', () => api);

let pipeline;
function Capture() {
  pipeline = usePipeline();
  return null;
}

describe('PipelineProvider', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it('stops polling once a run reports skipped', async () => {
    // #472: a run queued before cutover to economic authority is skipped.
    vi.useFakeTimers();
    api.getPipelineStatus.mockResolvedValue({ status: 'skipped', error_message: 'economic_authority' });
    render(
      <QueryClientProvider client={new QueryClient()}>
        <PipelineProvider>
          <Capture />
        </PipelineProvider>
      </QueryClientProvider>,
    );

    act(() => pipeline.startPipeline('run-1'));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10000);
    });

    expect(api.getPipelineStatus).toHaveBeenCalledTimes(1);
    expect(pipeline.isPipelineRunning).toBe(false);
    expect(pipeline.isCardVisible).toBe(true);
  });
});
