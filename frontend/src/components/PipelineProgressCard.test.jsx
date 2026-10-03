import { screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import PipelineProgressCard from './PipelineProgressCard';
import { PipelineContext } from '../contexts/pipelineContextStore';
import { renderWithProviders } from '../test/renderWithProviders';

const renderCard = (pipelineStatus) =>
  renderWithProviders(
    <PipelineContext.Provider
      value={{
        pipelineStatus,
        isCardVisible: true,
        isMinimized: false,
        closePipelineCard: vi.fn(),
        toggleMinimize: vi.fn(),
      }}
    >
      <PipelineProgressCard />
    </PipelineContext.Provider>,
  );

describe('PipelineProgressCard', () => {
  it('shows a run skipped under economic authority as a finished state with its reason', () => {
    // #472: a run queued before cutover is skipped by the worker.
    renderCard({
      status: 'skipped',
      current_step: 'skipped',
      percent: 0,
      error_message: 'economic_authority: legacy Theme pipeline is disabled under economic authority',
    });

    expect(screen.getByText('Pipeline Skipped')).toBeInTheDocument();
    expect(screen.getByText(/legacy Theme pipeline is disabled/)).toBeInTheDocument();
  });
});
