import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './index.css'
import { createBrowserRouter, RouterProvider } from 'react-router-dom'
// import { loader as sessionLoader } from './routes/sessions'
import ErrorPage from "./error-page"
import SessionList from './components/SessionList'
// import Session from './routes/sessions'

const router = createBrowserRouter([
  {
    path: "/",
    element: <App />,
    errorElement: <ErrorPage />,
    // loader: sessionLoader,
    children:  [
      {
        path: "sessions/",
        element: <SessionList />
      }
    ]
  },
  // {
  //   path: "sessions",
  //   element: <SessionList />
  // }
])

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <RouterProvider router={router} />
  </React.StrictMode>,
)
