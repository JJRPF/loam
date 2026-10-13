import React, { useEffect, useState } from 'react';

export const OfflineBanner: React.FC = () => {
  const [online, setOnline] = useState(typeof navigator === 'undefined' ? true : navigator.onLine);
  useEffect(() => {
    const up = () => setOnline(true);
    const down = () => setOnline(false);
    window.addEventListener('online', up);
    window.addEventListener('offline', down);
    return () => {
      window.removeEventListener('online', up);
      window.removeEventListener('offline', down);
    };
  }, []);
  if (online) return null;
  return (
    <div
      role="status"
      style={{ position: 'fixed', top: 0, left: 0, right: 0, zIndex: 3000, background: '#1D3B34', color: '#FFFFFF', textAlign: 'center', fontSize: 13, padding: '6px 12px' }}
    >
      Waiting for connection. Routes you viewed recently are under Saved.
    </div>
  );
};

export default OfflineBanner;
