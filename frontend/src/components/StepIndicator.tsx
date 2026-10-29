import React from 'react';
import { FlowStep } from '../lib/types';

interface StepIndicatorProps {
  currentStep: FlowStep;
  onSelectStep: (step: FlowStep) => void;
  canNavigateTo: (step: FlowStep) => boolean;
}

const STEPS: { key: FlowStep; label: string }[] = [
  { key: 'connect', label: '1. Elegir Playlist' },
  { key: 'preview', label: '2. Ver Canciones' },
  { key: 'ytconfig', label: '3. Conectar YouTube' },
  { key: 'migrate', label: '4. Transferir' },
  { key: 'summary', label: '5. Listo' },
];

export const StepIndicator: React.FC<StepIndicatorProps> = ({
  currentStep,
  onSelectStep,
  canNavigateTo,
}) => {
  const activeIdx = STEPS.findIndex((s) => s.key === currentStep);

  return (
    <nav className="stepper-nav" aria-label="Pasos de la transferencia">
      <div className="stepper-track">
        {STEPS.map((step, idx) => {
          const isActive = step.key === currentStep;
          const isCompleted = idx < activeIdx;
          const enabled = canNavigateTo(step.key);

          return (
            <button
              key={step.key}
              type="button"
              disabled={!enabled}
              onClick={() => enabled && onSelectStep(step.key)}
              className={`stepper-pill ${isActive ? 'is-active' : ''} ${
                isCompleted ? 'is-completed' : ''
              }`}
            >
              <span className="stepper-dot" aria-hidden="true">
                {isCompleted ? '✓' : idx + 1}
              </span>
              <span className="stepper-label">{step.label}</span>
            </button>
          );
        })}
      </div>
    </nav>
  );
};
