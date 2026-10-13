import React from 'react';
import { useAppConfig } from '../services/config';

const linkStyle: React.CSSProperties = {
  color: 'inherit', textDecoration: 'underline', display: 'inline-flex', alignItems: 'center', minHeight: 44
};

/** Privacy · Terms · Attributions · Source code (the source link is what AGPL section 13 asks network users be offered). */
export const LegalLinks: React.FC<{ style?: React.CSSProperties }> = ({ style }) => {
  const { source_url } = useAppConfig();
  return (
    <nav
      aria-label="Legal"
      style={{
        display: 'flex', flexWrap: 'wrap', gap: '0 14px', fontSize: 12, color: 'var(--color-text-secondary, #A0B5AE)', ...style
      }}
    >
      <a href="/legal/privacy/" target="_blank" rel="noopener" style={linkStyle}>Privacy</a>
      <a href="/legal/terms/" target="_blank" rel="noopener" style={linkStyle}>Terms</a>
      <a href="/legal/attributions/" target="_blank" rel="noopener" style={linkStyle}>Attributions</a>
      <a href={source_url} target="_blank" rel="noopener noreferrer" style={linkStyle}>Source code</a>
    </nav>
  );
};

/** Shown where people sign in. */
export const SignInAgreement: React.FC = () => (
  <p style={{ fontSize: 12, color: 'var(--color-text-secondary)', margin: 0 }}>
    By continuing you agree to the{' '}
    <a href="/legal/terms/" target="_blank" rel="noopener" style={{ color: 'inherit', textDecoration: 'underline' }}>Terms</a>{' '}
    and acknowledge the{' '}
    <a href="/legal/privacy/" target="_blank" rel="noopener" style={{ color: 'inherit', textDecoration: 'underline' }}>Privacy Policy</a>.
  </p>
);
