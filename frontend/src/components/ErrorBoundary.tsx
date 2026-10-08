import { Component, type ErrorInfo, type ReactNode } from 'react';

interface Props {
  children: ReactNode;
  fallbackTitle?: string;
  onReset?: () => void;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  public override state: State = {
    hasError: false,
    error: null
  };

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  public override componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('Uncaught error caught by ErrorBoundary:', error, errorInfo);
  }

  public override render() {
    if (this.state.hasError) {
      return (
        <div
          style={{
            padding: 24,
            backgroundColor: 'var(--color-card-bg, #FFFFFF)',
            borderRadius: 8,
            border: '1px solid var(--color-divider, #D1D8D8)',
            margin: '16px 0',
            textAlign: 'center'
          }}
        >
          <div style={{ fontSize: 28, marginBottom: 8 }}>⚠️</div>
          <h3 style={{ fontSize: 16, fontWeight: 700, color: 'var(--color-text-primary, #1D3B34)', marginBottom: 6 }}>
            {this.props.fallbackTitle || 'Unable to display view'}
          </h3>
          <p style={{ fontSize: 13, color: 'var(--color-text-secondary, #42675E)', marginBottom: 16, lineHeight: 1.4 }}>
            {this.state.error?.message || 'An unexpected error occurred while rendering.'}
          </p>
          <button
            type="button"
            className="btn-primary"
            onClick={() => {
              this.setState({ hasError: false, error: null });
              this.props.onReset?.();
            }}
            style={{ minHeight: 36, padding: '6px 16px', fontSize: 13 }}
          >
            Reset to Plan
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}
