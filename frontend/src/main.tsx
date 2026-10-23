import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { SharedRoutePage, tokenFromPath } from './components/SharedRoutePage'
import { FriendInvitePage } from './components/FriendInvitePage'
import { redirectToPublicOrigin } from './services/origin'

/** /r/<token> (a shared route) and /friends/invite/<token> are their own small pages: signed out works, and
 * the planner behind App (geolocation, route search) never starts. */
function pickPage() {
  const path = window.location.pathname
  if (path.startsWith('/r/')) return <SharedRoutePage source={{ kind: 'link', token: tokenFromPath(path, '/r/') }} />
  if (path.startsWith('/friends/invite/')) return <FriendInvitePage token={tokenFromPath(path, '/friends/invite/')} />
  return <App />
}

// An old install of the app on another origin (e.g. the Funnel host) moves to the public origin first.
if (!redirectToPublicOrigin()) {
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      {pickPage()}
    </StrictMode>,
  )
}
