import "./App.css";
import Nav from "./components/Nav";
import { Outlet, useLoaderData } from "react-router-dom";

function App() {
  

  return (
    <>
      <div className="dark:bg-gray-800 min-h-screen">
        <Nav />
        <Outlet />
      </div>
      {/* {% load version %} */}
      {/* <span className="fixed left-2 bottom-2 text-xs text-slate-300 dark:text-slate-600">{% version %} ({% version_date %})</span> */}
    </>
  );
}

export default App;
