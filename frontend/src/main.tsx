import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import { AuthProvider } from "./features/auth/AuthProvider";
import { Providers } from "./app/providers";
import { routes } from "./app/router";
import "./app/styles.css";
const router = createBrowserRouter(routes);
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Providers>
      <AuthProvider>
        <RouterProvider router={router} />
      </AuthProvider>
    </Providers>
  </StrictMode>,
);
