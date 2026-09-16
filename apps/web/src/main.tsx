import React from 'react'
import ReactDOM from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import App from './App'
import './styles.css'
import './terminal.css'
import './theme.css'

const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode><QueryClientProvider client={client}><App /></QueryClientProvider></React.StrictMode>,
)
