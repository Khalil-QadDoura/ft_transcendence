import { createBrowserRouter } from "react-router-dom";
import { Welcome } from "../features/home/Welcome";
export const router = createBrowserRouter([
  { path: "*", element: <Welcome /> },
]);
