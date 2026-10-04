import { Navigate, Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import Chaos from './pages/Chaos'
import Expirations from './pages/Expirations'
import Flags from './pages/Flags'
import Ingest from './pages/Ingest'
import People from './pages/People'
import Pipeline from './pages/Pipeline'
import Referrals from './pages/Referrals'
import Settings from './pages/Settings'
import Staffing from './pages/Staffing'

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Ingest />} />
        <Route path="pipeline" element={<Pipeline />} />
        <Route path="flags" element={<Flags />} />
        <Route path="people" element={<People />} />
        <Route path="staffing" element={<Staffing />} />
        <Route path="expirations" element={<Expirations />} />
        <Route path="referrals" element={<Referrals />} />
        <Route path="chaos" element={<Chaos />} />
        <Route path="settings" element={<Settings />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
