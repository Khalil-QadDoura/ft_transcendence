import { createBrowserRouter } from "react-router-dom";
import { Welcome } from "../features/home/Welcome";
import { ComponentPreview } from "../features/dev/ComponentPreview";

export const router = createBrowserRouter([
  ...(import.meta.env.DEV
    ? [{ path: "/dev/components", element: <ComponentPreview /> }]
    : []),
  { path: "*", element: <Welcome /> },
]);
