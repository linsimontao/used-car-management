import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'

import { Console } from './pages/Console'
import { Login } from './pages/Login'
import { VehicleList } from './pages/VehicleList'
import './index.css'

// ルーティング（SPEC §9.1）
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/" element={<Console />} />
        <Route path="/vehicles" element={<VehicleList />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  </StrictMode>,
)
