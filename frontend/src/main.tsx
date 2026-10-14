import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { redirectToPublicOrigin } from './services/origin'

// An old install of the app on another origin (e.g. the Funnel host) moves to the public origin first.
if (!redirectToPublicOrigin()) {
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  )
}
